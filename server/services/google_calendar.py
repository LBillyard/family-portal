"""Google Calendar OAuth and sync."""

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


def authorization_url(state: str) -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
    return url


def exchange_code(code: str) -> dict:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())
    flow.fetch_token(code=code)
    creds = flow.credentials
    return json.loads(creds.to_json())


def _credentials(token_json: str):
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)


def sync_user_calendar(user_id: str) -> int:
    """Pull primary calendar events for the next 120 days. Returns count synced."""
    user = db.get_user(user_id)
    if not user or not user.get("google_token_json"):
        return 0

    from googleapiclient.discovery import build

    creds = _credentials(user["google_token_json"])
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=120)).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )

    count = 0
    for item in events_result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        all_day = "date" in start
        start_at = start.get("dateTime") or start.get("date", "")
        end_at = end.get("dateTime") or end.get("date")
        if not start_at:
            continue
        db.upsert_google_event(
            user_id=user_id,
            google_id=item["id"],
            title=item.get("summary", "Busy"),
            start=start_at,
            end=end_at,
            all_day=all_day,
            location=item.get("location"),
        )
        count += 1

    db.set_setting("google_last_sync", datetime.now().strftime("%H:%M today"))
    logger.info("Synced %d Google events for user %s", count, user_id)
    return count


def sync_all_users() -> dict:
    results = {}
    for user in db.list_users():
        if user.get("google_token_json"):
            try:
                results[user["id"]] = sync_user_calendar(user["id"])
            except Exception as exc:
                logger.exception("Google sync failed for %s", user["id"])
                results[user["id"]] = f"error: {exc}"
    return results


def push_event_to_google(user_id: str, event: dict) -> str | None:
    """Create a portal event on the user's Google Calendar. Returns Google event id."""
    user = db.get_user(user_id)
    if not user or not user.get("google_token_json"):
        return None

    from googleapiclient.discovery import build

    creds = _credentials(user["google_token_json"])
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    body: dict = {
        "summary": event["title"],
        "location": event.get("location") or "",
    }
    if event.get("all_day"):
        start_d = event["start"][:10]
        end_d = (event.get("end") or event["start"])[:10]
        body["start"] = {"date": start_d}
        body["end"] = {"date": end_d}
    else:
        body["start"] = {"dateTime": event["start"], "timeZone": "Europe/London"}
        body["end"] = {"dateTime": event.get("end") or event["start"], "timeZone": "Europe/London"}

    created = service.events().insert(calendarId="primary", body=body).execute()
    gid = created.get("id")
    if gid and event.get("id"):
        db.set_event_google_written(event["id"], gid)
    return gid
