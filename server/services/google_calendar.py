"""Google Calendar OAuth + multi-account, multi-calendar sync.

Each person can connect several Google accounts (e.g. personal + work). Each
connection is a row in `google_accounts`; syncing pulls events from every
selected calendar in that account. Re-sync replaces that account's events.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from server import database as db

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Google Calendar not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
    }


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8090/api/auth/google/callback").strip()


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def authorization_url(state: str) -> tuple[str, str]:
    """Returns (url, code_verifier). The verifier must be stored and passed back
    to exchange_code() — without it Google rejects the token exchange (PKCE)."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true", state=state
    )
    return url, flow.code_verifier


def exchange_code(code: str, code_verifier: str | None = None) -> dict:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    return json.loads(flow.credentials.to_json())


def _credentials(token_json: str):
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)


def _service(creds):
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def account_email(token_json: str) -> str:
    """The primary calendar's id is the account's email address."""
    creds = _credentials(token_json)
    cal = _service(creds).calendars().get(calendarId="primary").execute()
    return cal.get("id", "") or ""


def sync_account(account: dict) -> int:
    """Sync every selected calendar of one connected account (decrypted token_json)."""
    creds = _credentials(account["token_json"])
    service = _service(creds)
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=120)).isoformat()

    db.delete_events_for_google_account(account["id"])
    count = 0
    try:
        cal_items = service.calendarList().list().execute().get("items", [])
    except Exception:
        cal_items = [{"id": "primary", "primary": True}]

    for cal in cal_items:
        if not (cal.get("primary") or cal.get("selected")):
            continue
        cal_id = cal.get("id", "primary")
        cal_name = cal.get("summaryOverride") or cal.get("summary") or ""
        try:
            events_result = (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )
        except Exception as exc:
            logger.warning("Calendar %s list failed: %s", cal_id, exc)
            continue
        for item in events_result.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            start_at = start.get("dateTime") or start.get("date", "")
            if not start_at:
                continue
            db.create_google_event(
                user_id=account["user_id"],
                google_account_id=account["id"],
                google_id=item.get("id", ""),
                title=item.get("summary", "Busy"),
                start=start_at,
                end=end.get("dateTime") or end.get("date"),
                all_day="date" in start,
                location=item.get("location"),
                calendar_name=cal_name,
            )
            count += 1

    try:
        db.update_google_account_token(account["id"], creds.to_json())
    except Exception:
        pass
    db.mark_google_account_synced(account["id"])
    db.set_setting("google_last_sync", datetime.now().strftime("%H:%M today"))
    logger.info("Synced %d events for Google account %s", count, account.get("email"))
    return count


def sync_all() -> dict:
    results = {}
    for pub in db.list_google_accounts():
        acct = db.get_google_account_internal(pub["id"])
        if not acct:
            continue
        try:
            results[acct["email"]] = sync_account(acct)
        except Exception as exc:
            logger.exception("Google sync failed for %s", acct.get("email"))
            results[acct.get("email", acct["id"])] = f"error: {exc}"
    return results


def push_event_to_google(user_id: str, event: dict) -> str | None:
    """Write a portal event to the user's first connected Google account."""
    accounts = db.list_google_accounts(user_id)
    if not accounts:
        return None
    acct = db.get_google_account_internal(accounts[0]["id"])
    if not acct:
        return None
    service = _service(_credentials(acct["token_json"]))
    body: dict = {"summary": event["title"], "location": event.get("location") or ""}
    if event.get("all_day"):
        body["start"] = {"date": event["start"][:10]}
        body["end"] = {"date": (event.get("end") or event["start"])[:10]}
    else:
        body["start"] = {"dateTime": event["start"], "timeZone": "Europe/London"}
        body["end"] = {"dateTime": event.get("end") or event["start"], "timeZone": "Europe/London"}
    created = service.events().insert(calendarId="primary", body=body).execute()
    return created.get("id")
