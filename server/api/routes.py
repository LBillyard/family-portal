"""REST API routes."""

import json
import logging
import os
import secrets
import time

from datetime import date, datetime, timedelta
from urllib.parse import quote

from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from server import auth, database as db
from server.services import csv_import, dashboard as dash, documents as doc_files, google_calendar, openrouter, open_banking
from server.services import assistant as ai_assistant, media as media_files, subscriptions as sub_svc
from server.services import memory as mem_svc, gmail_memory, gmail_inbox
from server.services import activity as activity_svc, briefing as briefing_svc, renewals as renewals_svc
from server.services import finance_merge, notifications as notify_svc, receipts as receipt_svc
from server.services import search as search_svc, trips as trips_svc, categorize as cz
from server.services import weather as weather_svc, gmail_receipts, push as push_svc
from server.services import whatsapp as whatsapp_svc, whatsapp_meta, whatsapp_twilio
from server.services import insights, networth, occasions, vehicles as vehicles_svc
from shared.schemas import (
    AccountUpdate,
    AppointmentCreate,
    AppointmentUpdate,
    AssetCreate,
    AssetUpdate,
    AssistantChatRequest,
    BillCreate,
    BillLock,
    BillUpdate,
    BudgetCreate,
    BudgetUpdate,
    CareItemCreate,
    CareItemUpdate,
    ChangePasswordRequest,
    ChecklistToggleRequest,
    ChoreCreate,
    ChoreUpdate,
    DependentCreate,
    DependentUpdate,
    TransactionCategoryUpdate,
    DocumentCreate,
    EmailReceiptImport,
    EventCreate,
    EventUpdate,
    HolidayIdeaRequest,
    InventoryCreate,
    InventoryUpdate,
    LoginRequest,
    MaintenanceCreate,
    MaintenanceUpdate,
    MealPlanUpsert,
    MediaUpdate,
    MemberUpdate,
    MemoryCreate,
    MemoryImport,
    MemoryUpdate,
    NotificationPrefsUpdate,
    OccasionCreate,
    OccasionUpdate,
    InboxImport,
    PushSubscribe,
    RecipeCreate,
    RecipeUpdate,
    SavingsGoalCreate,
    SavingsGoalUpdate,
    SearchQuery,
    ShoppingItemCreate,
    SubscriptionUpdate,
    TaskCreate,
    TaskUpdate,
    TradespersonCreate,
    TradespersonUpdate,
    TransactionCreate,
    TransferCreate,
    TripCreate,
    TripPackingRequest,
    TripUpdate,
    VehicleCreate,
    VehicleUpdate,
    WishlistCreate,
    WishlistUpdate,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --- Login brute-force throttle (per-email sliding window; single-worker in-memory) ---
_LOGIN_MAX = 8
_LOGIN_WINDOW = 300  # seconds
_login_fails: dict[str, list[float]] = {}


def _login_key(email: str) -> str:
    return (email or "").strip().lower()


def _login_blocked(key: str) -> bool:
    now = time.time()
    fails = [t for t in _login_fails.get(key, []) if now - t < _LOGIN_WINDOW]
    _login_fails[key] = fails
    return len(fails) >= _LOGIN_MAX


@router.post("/auth/login")
def login(body: LoginRequest, request: Request):
    key = _login_key(body.email)
    if _login_blocked(key):
        raise HTTPException(status_code=429, detail="Too many attempts — wait 5 minutes and try again")
    user = auth.authenticate(body.email, body.password)
    if not user:
        _login_fails.setdefault(key, []).append(time.time())
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _login_fails.pop(key, None)
    request.session.clear()
    request.session["user"] = user
    return {"user": user}


@router.post("/auth/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(require_user)):
    full = db.get_user(user["id"])
    if not full or not auth.verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    db.update_user_password(user["id"], auth.hash_password(body.new_password))
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user": user}


# --- Google Calendar OAuth ---

@router.get("/auth/google/start")
def google_start(request: Request, user: dict = Depends(require_user)):
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google Calendar not configured — add credentials to .env")
    state = secrets.token_urlsafe(16)
    url, verifier = google_calendar.authorization_url(state)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user"] = user["id"]
    request.session["google_oauth_verifier"] = verifier
    return RedirectResponse(url)


def _clear_google_oauth_session(request: Request) -> None:
    request.session.pop("google_oauth_state", None)
    request.session.pop("google_oauth_user", None)
    request.session.pop("google_oauth_verifier", None)


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        _clear_google_oauth_session(request)
        return RedirectResponse("/?google_error=1")
    expected = request.session.get("google_oauth_state")
    user_id = request.session.get("google_oauth_user")
    verifier = request.session.get("google_oauth_verifier")
    if not expected or state != expected or not user_id:
        _clear_google_oauth_session(request)
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    session_user = request.session.get("user")
    if session_user and session_user.get("id") != user_id:
        _clear_google_oauth_session(request)
        return RedirectResponse(f"/?google_error={quote('Session mismatch — sign in and try again')}")
    try:
        token = google_calendar.exchange_code(code, verifier)
        token_json = __import__("json").dumps(token)
        email = google_calendar.account_email(token_json)
        account_id = db.upsert_google_account(user_id, email, token_json)
        internal = db.get_google_account_internal(account_id)
        google_calendar.sync_account(internal)
    except Exception as exc:
        _clear_google_oauth_session(request)
        return RedirectResponse(f"/?google_error={quote(str(exc)[:120])}")
    _clear_google_oauth_session(request)
    return RedirectResponse("/?google_connected=1")


@router.get("/google/accounts")
def google_accounts_list(_: dict = Depends(require_user)):
    return {"accounts": db.list_google_accounts(), "configured": google_calendar.is_configured()}


@router.delete("/google/accounts/{account_id}")
def google_account_disconnect(account_id: str, _: dict = Depends(require_user)):
    ok = db.delete_google_account(account_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Google account not found")
    return {"ok": True}


@router.post("/calendar/sync")
def calendar_sync(_: dict = Depends(require_user)):
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google Calendar not configured")
    results = google_calendar.sync_all()
    return {"synced": results, "google_last": db.get_setting("google_last_sync", "just now")}


# --- WhatsApp (provider dispatcher: Twilio or Meta) ---

# In-memory de-dupe of processed inbound message ids (providers may re-deliver).
_whatsapp_seen: set[str] = set()


def _dedup(mid: str | None) -> bool:
    """True if this message id was already handled."""
    if mid and mid in _whatsapp_seen:
        return True
    if mid:
        _whatsapp_seen.add(mid)
    return False


@router.get("/whatsapp/webhook")
def whatsapp_verify(request: Request):
    """Meta webhook verification handshake (public, no auth)."""
    params = request.query_params
    challenge = whatsapp_meta.verify_webhook(
        params.get("hub.mode", ""),
        params.get("hub.verify_token", ""),
        params.get("hub.challenge", ""),
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Verification failed")
    return PlainTextResponse(challenge)


@router.post("/whatsapp/webhook")
async def whatsapp_receive(request: Request):
    """Inbound messages from Meta (public, verified by signature + number allowlist)."""
    # Only accept the ACTIVE provider's webhook, and never without a signing secret —
    # otherwise anyone could POST forged payloads at the inactive endpoint.
    if whatsapp_svc.provider() != "meta" or not os.environ.get("WHATSAPP_APP_SECRET", "").strip():
        raise HTTPException(status_code=403, detail="Webhook not enabled")
    raw = await request.body()
    if not whatsapp_meta.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="Bad signature")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return {"ok": True}
    for msg in whatsapp_meta.parse_inbound(payload):
        if _dedup(msg.get("id")):
            continue
        await _handle_whatsapp_message(msg)
    return {"ok": True}


@router.post("/whatsapp/twilio")
async def whatsapp_twilio_receive(request: Request):
    """Inbound messages from Twilio (public, form-encoded, X-Twilio-Signature verified)."""
    if whatsapp_svc.provider() != "twilio":
        raise HTTPException(status_code=403, detail="Webhook not enabled")
    form = dict((await request.form()))
    url = os.environ.get("PUBLIC_URL", "").rstrip("/") + "/api/whatsapp/twilio"
    if not whatsapp_twilio.validate_request(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Bad signature")
    for msg in whatsapp_twilio.parse_inbound(form):
        if _dedup(msg.get("id")):
            continue
        await _handle_whatsapp_message(msg)
    return PlainTextResponse("<Response></Response>", media_type="application/xml")


async def _handle_whatsapp_message(msg: dict) -> None:
    frm = msg.get("from", "")
    text = (msg.get("text") or "").strip()
    media = msg.get("media") or []
    # A media-only message (photo with no caption) has empty text but must still run.
    if not frm or (not text and not media):
        return
    user = db.get_user_by_phone(frm)
    if not user:
        # Unknown number — ignore silently (don't reply to strangers). This is the
        # security gate: only linked household members can add media or chat.
        logger.warning("WhatsApp message from unlinked number %s — ignoring", frm)
        return

    # --- Ingest any attached photos/videos into the family media library ---
    added = 0
    if media:
        for m in media:
            url = m.get("url")
            ext = media_files.ext_for_content_type(m.get("content_type"))
            if not url or not ext:
                continue
            try:
                data_bytes, _ct = await whatsapp_twilio.download_media(url)
            except Exception:
                logger.exception("WhatsApp media download failed for %s", frm)
                continue  # one bad download must not break the rest
            is_video = ext in media_files.VIDEO_EXTENSIONS
            cap = media_files.VIDEO_MAX_BYTES if is_video else media_files.PHOTO_MAX_BYTES
            if len(data_bytes) > cap:
                logger.warning("WhatsApp media too large (%d bytes) — skipping", len(data_bytes))
                continue
            try:
                media_files.ensure_media_dir()
                mid = __import__("uuid").uuid4().hex[:12]
                stored = f"{mid}_whatsapp{ext}"
                (media_files.MEDIA_DIR / stored).write_bytes(data_bytes)
                db.create_media({
                    "id": mid,
                    "title": f"WhatsApp {'video' if is_video else 'photo'}",
                    "media_type": media_files.media_type_for_ext(ext),
                    "file_name": stored,
                    "file_path": stored,
                    "mime_type": m.get("content_type"),
                    "file_size": len(data_bytes),
                    "user_id": user["id"],
                    "source": "whatsapp",
                })
                added += 1
            except Exception:
                logger.exception("Saving WhatsApp media failed for %s", frm)
        if added:
            try:
                await whatsapp_svc.send_text(frm, f"📸 Added {added} to your photos.")
            except Exception:
                logger.exception("Failed to send WhatsApp media reply to %s", frm)

    # --- Handle text (if any) with the AI, exactly as before ---
    # A media-only message (no text) skips the AI — just the photos reply above.
    if not text:
        return
    try:
        if not ai_assistant.is_configured():
            await whatsapp_svc.send_text(frm, "The assistant isn't set up yet — add OPENROUTER_API_KEY.")
            return
        result = await ai_assistant.chat(user, text, channel="whatsapp")
        reply = (result.get("reply") or "Done.").strip()
    except Exception:
        logger.exception("WhatsApp AI handling failed")
        reply = "Sorry — something went wrong handling that. Try again?"
    try:
        await whatsapp_svc.send_text(frm, reply)
    except Exception:
        logger.exception("Failed to send WhatsApp reply to %s", frm)


@router.get("/whatsapp/status")
def whatsapp_status(_: dict = Depends(require_user)):
    return {"configured": whatsapp_svc.is_configured()}


@router.post("/whatsapp/test-digest")
async def whatsapp_test_digest(user: dict = Depends(require_user)):
    """Send the current user their digest now (for testing)."""
    if not whatsapp_svc.is_configured():
        raise HTTPException(status_code=503, detail="WhatsApp not configured — add WHATSAPP_* to .env")
    full = db.get_user(user["id"])
    phone = (full or {}).get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Add your phone number in Settings → Household first")
    weather_line = await weather_svc.today_line()
    line = briefing_svc.whatsapp_digest_line(full, weather=weather_line)
    try:
        await whatsapp_svc.send_digest(phone, line)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "sent_to": phone, "preview": line}


@router.get("/integrations")
def integrations(_: dict = Depends(require_user)):
    return {
        "google_calendar": google_calendar.is_configured(),
        "openrouter": openrouter.is_configured(),
        "open_banking": open_banking.is_configured(),
        "google_last_sync": db.get_setting("google_last_sync", "never"),
        "banking_last_sync": db.get_setting("banking_last_sync", "never"),
    }


# --- Open Banking (TrueLayer) ---

@router.get("/banking/providers")
def banking_providers(_: dict = Depends(require_user)):
    return {"providers": open_banking.list_providers(), "configured": open_banking.is_configured()}


@router.get("/banking/connections")
def banking_connections(_: dict = Depends(require_user)):
    return {"connections": db.list_bank_connections()}


@router.get("/banking/connect/{provider_id}")
def banking_connect(provider_id: str, request: Request, user: dict = Depends(require_user)):
    if not open_banking.is_configured():
        raise HTTPException(status_code=503, detail="Open Banking not configured — add TrueLayer credentials to .env")
    provider = open_banking.provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Unknown bank provider")
    state = secrets.token_urlsafe(16)
    db.save_banking_oauth_state(state, user["id"], provider_id)
    request.session["banking_oauth_state"] = state
    request.session["banking_oauth_provider"] = provider_id
    request.session["banking_oauth_user"] = user["id"]
    url = open_banking.authorization_url(
        state=state,
        provider_id=provider_id,
        user_email=user["email"],
    )
    return RedirectResponse(url)


@router.get("/banking/callback")
async def banking_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    error_desc = request.query_params.get("error_description", "")
    if error:
        msg = quote(error_desc or error)
        return RedirectResponse(f"/?bank_error={msg}")

    oauth = db.pop_banking_oauth_state(state) if state else None
    user_id = oauth["user_id"] if oauth else request.session.get("banking_oauth_user")
    provider_id = oauth["provider_id"] if oauth else request.session.get("banking_oauth_provider")

    if not user_id or not provider_id:
        msg = quote("Connection link expired — open the portal and try Connect bank again")
        return RedirectResponse(f"/?bank_error={msg}")
    if not oauth:
        session_state = request.session.get("banking_oauth_state")
        if not session_state or state != session_state:
            msg = quote("Session lost — use the Cloudflare portal URL for the whole flow, not localhost")
            return RedirectResponse(f"/?bank_error={msg}")
    if not code:
        msg = quote("Bank did not return an authorisation code")
        return RedirectResponse(f"/?bank_error={msg}")

    provider = open_banking.provider_by_id(provider_id) or {"name": provider_id}
    try:
        tokens = await open_banking.exchange_code(code)
        expires = open_banking.token_expires_at(int(tokens.get("expires_in", 3600)))
        conn = db.create_bank_connection(
            user_id=user_id,
            provider_id=provider_id,
            provider_name=provider.get("name", provider_id),
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            token_expires_at=expires,
        )
        internal = db.get_bank_connection_internal(conn["id"])
        if internal:
            await open_banking.sync_connection(internal, db)
    except Exception as exc:
        logger.exception("Banking callback failed")
        return RedirectResponse(f"/?bank_error={quote(str(exc)[:120])}")
    request.session.pop("banking_oauth_state", None)
    request.session.pop("banking_oauth_provider", None)
    request.session.pop("banking_oauth_user", None)
    return RedirectResponse("/?bank_connected=1")


@router.post("/banking/sync")
async def banking_sync(_: dict = Depends(require_user)):
    if not open_banking.is_configured():
        raise HTTPException(status_code=503, detail="Open Banking not configured")
    results = []
    for conn in db.list_bank_connections():
        internal = db.get_bank_connection_internal(conn["id"])
        if not internal:
            continue
        try:
            synced = await open_banking.sync_connection(internal, db)
            results.append({"provider": conn["provider_name"], **synced})
        except RuntimeError as exc:  # expired consent/tokens — surface as needs_reauth
            db.set_connection_status(conn["id"], "needs_reauth")
            results.append({"provider": conn["provider_name"], "error": str(exc)})
        except Exception as exc:
            results.append({"provider": conn["provider_name"], "error": str(exc)})
    sub_svc.refresh_subscriptions()
    db.reconcile_locked_bills()  # a new bank payment may auto-clear a locked bill
    return {"synced": results, "banking_last": db.get_setting("banking_last_sync", "just now")}


@router.delete("/banking/connections/{connection_id}")
def banking_disconnect(connection_id: str, _: dict = Depends(require_user)):
    if not db.get_bank_connection_internal(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    db.delete_bank_connection(connection_id)
    return {"ok": True}


# --- Dashboard & calendar ---

@router.get("/dashboard")
def api_dashboard(_: dict = Depends(require_user)):
    db.reconcile_locked_bills()  # keep "Bills due soon" in sync with locked-bill payments
    return dash.build_dashboard()


@router.get("/calendar")
def api_calendar(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "events": db.list_events()}


@router.post("/events")
def create_event(body: EventCreate, user: dict = Depends(require_user)):
    if body.user_id and body.user_id not in {u["id"] for u in db.list_users()}:
        raise HTTPException(status_code=400, detail="Unknown household member")
    end = body.end or body.start
    all_day = body.all_day or (len(body.start) == 10)
    uid = body.user_id or user["id"]
    event = db.create_event(
        {
            "title": body.title,
            "start": body.start,
            "end": end,
            "all_day": all_day,
            "user_id": body.user_id,
            "location": body.location,
        },
        user["id"],
    )
    if google_calendar.is_configured():
        try:
            gid = google_calendar.push_event_to_google(uid, event, account_id=body.google_account_id)
            if gid:
                db.set_event_google_written(event["id"], gid)  # sync must skip it (no dupes)
        except Exception as exc:
            logger.warning("Google write-back failed: %s", exc)
    activity_svc.log(user, "created", "event", f"Added event: {body.title}", entity_id=event["id"])
    return event


@router.patch("/events/{event_id}")
def update_event_route(event_id: str, body: EventUpdate, user: dict = Depends(require_user)):
    existing = db.get_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    if existing.get("source") == "google" or existing.get("google_account_id"):
        raise HTTPException(status_code=400, detail="Google events can't be edited here — change them in Google Calendar")
    event = db.update_event(event_id, body.model_dump(exclude_unset=True))
    activity_svc.log(user, "updated", "event", f"Updated event: {event['title']}", entity_id=event_id)
    return event


@router.delete("/events/{event_id}")
def delete_event_route(event_id: str, user: dict = Depends(require_user)):
    existing = db.get_event(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    if existing.get("source") == "google" or existing.get("google_account_id"):
        raise HTTPException(status_code=400, detail="Google events can't be deleted here — remove them in Google Calendar")
    db.delete_event(event_id)
    activity_svc.log(user, "deleted", "event", f"Removed event: {existing['title']}", entity_id=event_id)
    return {"ok": True}


# --- Finances ---

@router.get("/finances")
def api_finances(_: dict = Depends(require_user)):
    merged = finance_merge.build_merged_recurring()  # links matched bills → subscriptions
    if db.reconcile_locked_bills():  # auto-mark locked bills paid/unpaid from bank payments
        merged = finance_merge.build_merged_recurring()  # bills changed — rebuild so both views agree
    return {
        "bills": db.list_bills(),
        "transactions": db.list_transactions(),
        "accounts": db.list_accounts(),
        "budgets": db.list_budgets(),
        "savings_goals": db.list_savings_goals(),
        "summary": db.finance_summary(),
        "connections": db.list_bank_connections(),
        "banking_configured": open_banking.is_configured(),
        "merged_recurring": merged,
        "category_breakdown": db.category_breakdown(),
        "categories": cz.CATEGORIES,
    }


@router.get("/accounts")
def api_accounts(include_hidden: bool = False, _: dict = Depends(require_user)):
    return {"accounts": db.list_accounts(include_hidden=include_hidden)}


@router.patch("/accounts/{account_id}")
def update_account(account_id: str, body: AccountUpdate, user: dict = Depends(require_user)):
    data = body.model_dump(exclude_unset=True)
    acct = None
    if data.get("name") is not None:
        acct = db.rename_account(account_id, data["name"])
    if data.get("hidden") is not None:
        acct = db.set_account_hidden(account_id, data["hidden"])
    if acct is None:
        raise HTTPException(status_code=404, detail="Account not found")
    activity_svc.log(user, "updated", "account", f"Account updated: {acct['name']}", entity_id=account_id)
    return acct


@router.patch("/transactions/{txn_id}")
def recategorize_transaction(txn_id: str, body: TransactionCategoryUpdate, _: dict = Depends(require_user)):
    txn = db.get_transaction(txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if body.learn and txn.get("merchant_key"):
        n = db.learn_and_reclassify(txn["merchant_key"], body.category, source="user")
        return {"ok": True, "category": body.category, "reclassified": n}
    db.set_transaction_category(txn_id, body.category)
    return {"ok": True, "category": body.category, "reclassified": 1}


@router.post("/finances/categorize")
def categorize_all(_: dict = Depends(require_user)):
    return db.apply_categorization()


@router.post("/finances/categorize-ai")
async def categorize_ai(_: dict = Depends(require_user)):
    if not openrouter.is_configured():
        raise HTTPException(status_code=503, detail="OpenRouter not configured — set OPENROUTER_API_KEY")
    merchants = db.get_uncategorized_merchants(60)
    if not merchants:
        return {"suggested": 0, "reclassified": 0}
    try:
        suggestions = await cz.ai_suggest(merchants)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI categorisation failed: {exc}") from exc
    reclassified = 0
    for desc, info in suggestions.items():
        key = cz.normalize_merchant(desc)
        reclassified += db.learn_and_reclassify(key, info["category"], info.get("display_name"), source="ai")
    return {"suggested": len(suggestions), "reclassified": reclassified}


@router.post("/bills")
def create_bill(body: BillCreate, _: dict = Depends(require_user)):
    return db.create_bill(body.model_dump())


@router.patch("/bills/{bill_id}")
def update_bill_route(bill_id: str, body: BillUpdate, _: dict = Depends(require_user)):
    bill = db.update_bill(bill_id, body.model_dump(exclude_unset=True))
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.delete("/bills/{bill_id}")
def delete_bill_route(bill_id: str, _: dict = Depends(require_user)):
    if not db.delete_bill(bill_id):
        raise HTTPException(status_code=404, detail="Bill not found")
    return {"ok": True}


@router.post("/bills/{bill_id}/pay")
def pay_bill(bill_id: str, _: dict = Depends(require_user)):
    bill = db.mark_bill_paid(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.post("/bills/{bill_id}/lock")
def lock_bill(bill_id: str, body: BillLock, _: dict = Depends(require_user)):
    """Lock a bill to a detected bank payment (subscription) so it auto-marks paid."""
    existing = db.get_bill(bill_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Bill not found")
    sub_id = body.subscription_id or existing.get("subscription_id")
    if not sub_id:
        raise HTTPException(status_code=400, detail="No matching bank payment to lock this bill to.")
    db.set_bill_lock(bill_id, sub_id, locked=True)
    db.reconcile_locked_bills()
    return db.get_bill(bill_id)


@router.post("/bills/{bill_id}/unlock")
def unlock_bill(bill_id: str, _: dict = Depends(require_user)):
    bill = db.set_bill_lock(bill_id, locked=False)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.post("/budgets")
def create_budget_route(body: BudgetCreate, user: dict = Depends(require_user)):
    budget = db.create_budget(body.category, body.monthly_limit)
    activity_svc.log(user, "created", "budget", f"Set budget for {body.category}")
    return budget


@router.patch("/budgets/{category}")
def update_budget_route(category: str, body: BudgetUpdate, _: dict = Depends(require_user)):
    budget = db.update_budget(category, body.monthly_limit)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


@router.delete("/budgets/{category}")
def delete_budget_route(category: str, _: dict = Depends(require_user)):
    if not db.delete_budget(category):
        raise HTTPException(status_code=404, detail="Budget not found")
    return {"ok": True}


@router.post("/savings-goals")
def create_savings_goal_route(body: SavingsGoalCreate, user: dict = Depends(require_user)):
    goal = db.create_savings_goal(body.model_dump())
    activity_svc.log(user, "created", "savings", f"Added savings goal: {body.name}")
    return goal


@router.patch("/savings-goals/{goal_id}")
def update_savings_goal_route(goal_id: str, body: SavingsGoalUpdate, _: dict = Depends(require_user)):
    goal = db.update_savings_goal(goal_id, body.model_dump(exclude_unset=True))
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    return goal


@router.delete("/savings-goals/{goal_id}")
def delete_savings_goal_route(goal_id: str, _: dict = Depends(require_user)):
    if not db.delete_savings_goal(goal_id):
        raise HTTPException(status_code=404, detail="Savings goal not found")
    return {"ok": True}


# --- Family memory (RAG) ---

@router.get("/memory")
def api_memory(_: dict = Depends(require_user)):
    return {
        "facts": db.list_memory_facts(include_embedding=False),
        "categories": mem_svc.CATEGORIES,
        "enabled": mem_svc.is_enabled(),
        "subjects": [{"id": "family", "name": "Family"}]
        + [{"id": u["id"], "name": u["name"]} for u in db.list_users()],
    }


@router.post("/memory")
async def create_memory(body: MemoryCreate, user: dict = Depends(require_user)):
    if not mem_svc.is_enabled():
        raise HTTPException(status_code=503, detail="Memory needs OpenRouter — set OPENROUTER_API_KEY.")
    try:
        fact = await mem_svc.add_manual(body.text, body.category, body.subject, body.pinned)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not save memory: {exc}") from exc
    if not fact:
        raise HTTPException(status_code=400, detail="Empty fact")
    activity_svc.log(user, "created", "memory", f"Remembered: {body.text[:60]}")
    return fact


@router.patch("/memory/{fact_id}")
async def update_memory(fact_id: str, body: MemoryUpdate, _: dict = Depends(require_user)):
    try:
        fact = await mem_svc.edit(fact_id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not update memory: {exc}") from exc
    if not fact:
        raise HTTPException(status_code=404, detail="Memory not found")
    return fact


@router.delete("/memory/{fact_id}")
def delete_memory(fact_id: str, _: dict = Depends(require_user)):
    if not db.delete_memory_fact(fact_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@router.post("/memory/scan-email")
async def scan_email_memory(user: dict = Depends(require_user)):
    """Scan connected Gmail for durable facts worth remembering (read-only, no writes)."""
    if not mem_svc.is_enabled():
        raise HTTPException(status_code=503, detail="Memory needs OpenRouter — set OPENROUTER_API_KEY.")
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google not configured")
    try:
        return await gmail_memory.scan_for_facts(user["id"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Email scan failed: {exc}") from exc


@router.post("/memory/import-email")
async def import_email_memory(body: MemoryImport, user: dict = Depends(require_user)):
    """Store the facts the user picked from an email scan."""
    try:
        stored = await gmail_memory.commit([f.model_dump() for f in body.facts])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not save: {exc}") from exc
    if stored:
        activity_svc.log(user, "created", "memory", f"Added {len(stored)} fact(s) from email")
    return {"imported": len(stored), "facts": stored}


# --- Inbox auto-file (bookings / appointments / renewable documents from email) ---

@router.post("/inbox/scan")
async def inbox_scan(user: dict = Depends(require_user)):
    """Scan connected Gmail for actionable bookings/appointments/documents (read-only)."""
    if not openrouter.is_configured():
        raise HTTPException(status_code=503, detail="OpenRouter not configured — set OPENROUTER_API_KEY")
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google not configured")
    try:
        return await gmail_inbox.scan_for_items(user["id"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Inbox scan failed: {exc}") from exc


@router.post("/inbox/import")
async def inbox_import(body: InboxImport, user: dict = Depends(require_user)):
    """File the items the user picked from an inbox scan into trips/appointments/documents."""
    result = await gmail_inbox.commit([i.model_dump() for i in body.items])
    if result.get("created"):
        activity_svc.log(user, "created", "inbox", f"Filed {result['created']} item(s) from email")
    return result


@router.post("/transactions")
def create_transaction(body: TransactionCreate, _: dict = Depends(require_user)):
    # Resolve to a REAL account id: accept a valid id, else map a name, else default.
    account_id = db.resolve_account_id(body.account_id)
    if not account_id:
        raise HTTPException(status_code=400, detail="No account to log against yet — connect a bank or import a CSV first.")
    amount = body.amount
    if body.category != "Income" and amount > 0:
        amount = -abs(amount)
    elif body.category == "Income":
        amount = abs(amount)
    else:
        amount = -abs(amount)
    return db.create_transaction({
        "description": body.description,
        "amount": amount,
        "category": body.category,
        "account_id": account_id,
        "date": body.date,
    })


CSV_MAX_BYTES = 5 * 1024 * 1024


@router.post("/finances/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    account: str = "",
    _: dict = Depends(require_user),
):
    raw = await file.read()
    if len(raw) > CSV_MAX_BYTES:
        raise HTTPException(status_code=400, detail="CSV file too large (max 5 MB)")
    content = raw.decode("utf-8-sig", errors="replace")
    account_id = db.resolve_account_id(account or None)  # may be None: rows import unattached
    try:
        rows = csv_import.parse_csv(content, default_account=account_id)
        count = db.import_transactions(rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"imported": count}


@router.post("/finances/transfer")
def transfer_funds(body: TransferCreate, user: dict = Depends(require_user)):
    accounts = {a["id"]: a for a in db.list_accounts()}
    names = {a["name"]: a["id"] for a in db.list_accounts()}
    src = body.from_account if body.from_account in accounts else names.get(body.from_account)
    dst = body.to_account if body.to_account in accounts else names.get(body.to_account)
    if not src or not dst:
        raise HTTPException(status_code=400, detail="Unknown account")
    if src == dst:
        raise HTTPException(status_code=400, detail="Choose two different accounts")
    note = body.note or "Transfer"
    result = db.create_transfer(src, dst, body.amount, note, body.date)  # atomic: both legs or neither
    activity_svc.log(user, "created", "transaction", f"Transfer £{result['amount']:.2f}: {result['from']} → {result['to']}")
    return result


def _csv_safe(value) -> str:
    """Neutralise CSV/formula injection: a cell starting with = + - @ (or a
    control char) is executed as a formula by Excel/Sheets. Prefix with a
    single quote so it's treated as text."""
    s = "" if value is None else str(value)
    if s and (s[0] in "=+-@\t\r" or s[0] == "\x00"):
        return "'" + s
    return s


@router.get("/finances/export")
def export_transactions(_: dict = Depends(require_user)):
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["Date", "Description", "Category", "Account", "Amount"])
    for t in db.list_transactions(limit=100000):
        writer.writerow([
            _csv_safe(t["date"]),
            _csv_safe(t["description"]),
            _csv_safe(t["category"]),
            _csv_safe(t["account"]),
            f"{t['amount']:.2f}",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transactions.csv"'},
    )


# --- Subscriptions ---

@router.get("/subscriptions")
def api_subscriptions(_: dict = Depends(require_user)):
    return sub_svc.refresh_subscriptions()


@router.post("/subscriptions/scan")
def scan_subscriptions(_: dict = Depends(require_user)):
    return sub_svc.refresh_subscriptions()


@router.patch("/subscriptions/{sub_id}")
def patch_subscription(sub_id: str, body: SubscriptionUpdate, _: dict = Depends(require_user)):
    data = body.model_dump(exclude_unset=True)
    sub = db.update_subscription(sub_id, data)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    all_items = db.list_subscriptions(include_ignored=True)
    visible = [s for s in all_items if s["status"] not in ("ignored", "lapsed")]
    return {
        "subscription": sub,
        "summary": sub_svc.build_summary(all_items),
        "subscriptions": visible,
    }


# --- Spending insights & net worth ---

@router.get("/finances/insights")
def api_finances_insights(_: dict = Depends(require_user)):
    return insights.build_insights()


@router.get("/finances/networth")
def api_finances_networth(_: dict = Depends(require_user)):
    return networth.build_networth()


@router.get("/finances/networth-trend")
def api_finances_networth_trend(_: dict = Depends(require_user)):
    return networth.build_networth_trend()


@router.get("/finances/spend-trend")
def api_finances_spend_trend(_: dict = Depends(require_user)):
    return insights.build_spend_trend()


@router.get("/assets")
def api_assets(_: dict = Depends(require_user)):
    return {"assets": db.list_assets()}


@router.post("/assets")
def create_asset_route(body: AssetCreate, _: dict = Depends(require_user)):
    return {"asset": db.create_asset(body.model_dump())}


@router.patch("/assets/{asset_id}")
def update_asset_route(asset_id: str, body: AssetUpdate, _: dict = Depends(require_user)):
    asset = db.update_asset(asset_id, body.model_dump(exclude_unset=True))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"asset": asset}


@router.delete("/assets/{asset_id}")
def delete_asset_route(asset_id: str, _: dict = Depends(require_user)):
    if not db.delete_asset(asset_id):
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"ok": True}


# --- Appointments ---

@router.get("/appointments")
def api_appointments(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "appointments": db.list_appointments()}


@router.post("/appointments")
def create_appointment(body: AppointmentCreate, user: dict = Depends(require_user)):
    if body.user_id and body.user_id not in {u["id"] for u in db.list_users()}:
        raise HTTPException(status_code=400, detail="Unknown household member")
    return db.create_appointment(body.model_dump(), user["id"])


@router.patch("/appointments/{appt_id}")
def update_appointment(appt_id: str, body: AppointmentUpdate, user: dict = Depends(require_user)):
    appt = db.update_appointment(appt_id, body.model_dump(exclude_unset=True))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    activity_svc.log(user, "updated", "appointment", f"Updated appointment: {appt['title']}", entity_id=appt_id)
    return appt


@router.delete("/appointments/{appt_id}")
def delete_appointment(appt_id: str, user: dict = Depends(require_user)):
    existing = {a["id"]: a for a in db.list_appointments()}
    if appt_id not in existing:
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.delete_appointment(appt_id)
    activity_svc.log(user, "deleted", "appointment", f"Removed appointment: {existing[appt_id]['title']}", entity_id=appt_id)
    return {"ok": True}


@router.post("/appointments/sync-calendar")
def sync_appointments_to_calendar(user: dict = Depends(require_user)):
    from datetime import date as _date

    today = _date.today().isoformat()
    existing = {(e["user_id"], e["title"], (e.get("start") or "")[:16]) for e in db.list_events()}
    created = 0
    for a in db.list_appointments():
        if a["status"] != "upcoming" or (a.get("datetime") or "")[:10] < today:
            continue
        title = f"{a['title']} — {a['provider']}"
        if (a["user_id"], title, (a.get("datetime") or "")[:16]) in existing:
            continue
        event = db.create_event(
            {
                "title": title,
                "start": a["datetime"],
                "end": a["datetime"],
                "all_day": False,
                "location": a.get("location"),
                "user_id": a["user_id"],
            },
            user["id"],
        )
        if google_calendar.is_configured():
            try:
                gid = google_calendar.push_event_to_google(a["user_id"], event)
                if gid:
                    db.set_event_google_written(event["id"], gid)  # sync must skip it (no dupes)
            except Exception:
                pass
        created += 1
    activity_svc.log(user, "synced", "appointment", f"Synced {created} appointment(s) to calendar")
    return {"created": created}


# --- Holidays & AI ---

@router.get("/holidays")
def api_holidays(_: dict = Depends(require_user)):
    return {"trips": db.list_trips(), "ideas": db.list_holiday_ideas()}


@router.post("/holidays/trips")
def create_trip(body: TripCreate, _: dict = Depends(require_user)):
    return db.create_trip(body.model_dump())


@router.patch("/holidays/trips/{trip_id}")
def update_trip(trip_id: str, body: TripUpdate, user: dict = Depends(require_user)):
    trip = db.update_trip(trip_id, body.model_dump(exclude_unset=True))
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    activity_svc.log(user, "updated", "trip", f"Updated trip: {trip['title']}", entity_id=trip_id)
    return trip


@router.delete("/holidays/trips/{trip_id}")
def delete_trip_route(trip_id: str, user: dict = Depends(require_user)):
    trip = next((t for t in db.list_trips() if t["id"] == trip_id), None)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    db.delete_trip(trip_id)
    activity_svc.log(user, "deleted", "trip", f"Removed trip: {trip['title']}", entity_id=trip_id)
    return {"ok": True}


@router.post("/holidays/trips/{trip_id}/checklist/toggle")
def toggle_trip_checklist(trip_id: str, body: ChecklistToggleRequest, _: dict = Depends(require_user)):
    if not db.get_trip_detail(trip_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    ident = body.item_id or body.label
    if not ident:
        raise HTTPException(status_code=400, detail="item_id required")
    if not db.toggle_checklist_item(trip_id, ident, body.item_type):
        raise HTTPException(status_code=404, detail="Checklist item not found")
    return db.get_trip_detail(trip_id)


@router.post("/holidays/ideas/generate")
async def generate_ideas(body: HolidayIdeaRequest, _: dict = Depends(require_user)):
    try:
        ideas = await openrouter.generate_holiday_ideas(body.prompt, body.model)
        saved = db.create_holiday_ideas(ideas)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}") from exc
    return {"ideas": saved}


@router.post("/holidays/ideas/{idea_id}/toggle")
def toggle_idea(idea_id: str, _: dict = Depends(require_user)):
    idea = db.toggle_idea_saved(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


# --- AI Assistant ---

@router.get("/assistant/status")
def assistant_status(_: dict = Depends(require_user)):
    return {"configured": ai_assistant.is_configured()}


@router.get("/assistant/history")
def assistant_history(user: dict = Depends(require_user)):
    return {"messages": ai_assistant.get_history(user["id"])}


@router.post("/assistant/chat")
async def assistant_chat(body: AssistantChatRequest, user: dict = Depends(require_user)):
    if not ai_assistant.is_configured():
        raise HTTPException(status_code=503, detail="OpenRouter not configured — set OPENROUTER_API_KEY in .env")
    try:
        return await ai_assistant.chat(user, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/assistant/clear")
def assistant_clear(user: dict = Depends(require_user)):
    ai_assistant.clear_history(user["id"])
    return {"ok": True}


@router.post("/assistant/confirm/{action_id}")
async def assistant_confirm(action_id: str, user: dict = Depends(require_user)):
    result = await ai_assistant.confirm_action(action_id, user)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    activity_svc.log(user, "confirmed", "assistant", result.get("summary", "Confirmed AI action"))
    return result


# --- Briefing, search, activity, renewals, maintenance ---

@router.get("/briefing")
def api_briefing(user: dict = Depends(require_user)):
    return briefing_svc.build_briefing(user)


@router.get("/weather")
async def api_weather(days: int = 7, _: dict = Depends(require_user)):
    """Multi-day forecast for the header widget. Follows an upcoming/ongoing holiday."""
    data = await weather_svc.forecast(days=max(1, min(days, 14)))
    if not data:
        return {"configured": False}
    return {"configured": True, **data}


@router.get("/search")
def api_search(q: str = "", _: dict = Depends(require_user)):
    query = (q or "").strip()
    results = search_svc.search_all(query) if query else []
    # label/meta mirror title/subtitle for the existing search UI (back-compat).
    for r in results:
        r.setdefault("label", r["title"])
        r.setdefault("meta", r["subtitle"])
    return {"query": query, "results": results}


@router.post("/search")
def api_search_post(body: SearchQuery, _: dict = Depends(require_user)):
    return search_svc.search(body.query)


@router.get("/activity")
def api_activity(limit: int = 50, _: dict = Depends(require_user)):
    return {"items": db.list_activity(limit=limit)}


@router.get("/renewals")
def api_renewals(days: int = 90, _: dict = Depends(require_user)):
    return renewals_svc.build_renewal_calendar(days_ahead=days)


@router.get("/maintenance")
def api_maintenance(_: dict = Depends(require_user)):
    return {"items": db.list_maintenance()}


@router.post("/maintenance")
def create_maintenance(body: MaintenanceCreate, user: dict = Depends(require_user)):
    item = db.create_maintenance({**body.model_dump(), "user_id": user["id"]})
    activity_svc.log(user, "created", "maintenance", f"Added maintenance: {body.title}", entity_id=item["id"])
    return item


@router.patch("/maintenance/{item_id}")
def patch_maintenance(item_id: str, body: MaintenanceUpdate, user: dict = Depends(require_user)):
    item = db.update_maintenance(item_id, body.model_dump(exclude_unset=True))
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    activity_svc.log(user, "updated", "maintenance", f"Updated maintenance: {item['title']}", entity_id=item_id)
    return item


@router.post("/maintenance/{item_id}/done")
def maintenance_done(item_id: str, user: dict = Depends(require_user)):
    item = db.mark_maintenance_done(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    activity_svc.log(user, "completed", "maintenance", f"Serviced: {item['title']}", entity_id=item_id)
    return item


@router.delete("/maintenance/{item_id}")
def delete_maintenance(item_id: str, user: dict = Depends(require_user)):
    item = db.get_maintenance(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete_maintenance(item_id)
    activity_svc.log(user, "deleted", "maintenance", f"Removed maintenance: {item['title']}", entity_id=item_id)
    return {"ok": True}


@router.get("/finances/merged")
def api_merged_finances(_: dict = Depends(require_user)):
    return finance_merge.build_merged_recurring()


@router.get("/holidays/trips/{trip_id}")
def api_trip_detail(trip_id: str, _: dict = Depends(require_user)):
    trip = trips_svc.get_trip_detail(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


@router.post("/holidays/trips/{trip_id}/packing")
def add_trip_packing(trip_id: str, body: TripPackingRequest, user: dict = Depends(require_user)):
    if not db.get_trip_detail(trip_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    packing = trips_svc.add_packing_list(trip_id, body.template)
    activity_svc.log(user, "updated", "trip", f"Added packing list to trip", entity_id=trip_id)
    return {"packing": packing}


@router.post("/holidays/trips/{trip_id}/documents/{doc_id}")
def link_trip_doc(trip_id: str, doc_id: str, user: dict = Depends(require_user)):
    if not db.get_trip_detail(trip_id):
        raise HTTPException(status_code=404, detail="Trip not found")
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    db.link_trip_document(trip_id, doc_id)
    activity_svc.log(user, "linked", "trip", f"Linked document to trip", entity_id=trip_id, meta={"document_id": doc_id})
    return {"ok": True}


@router.delete("/holidays/trips/{trip_id}/documents/{doc_id}")
def unlink_trip_doc(trip_id: str, doc_id: str, user: dict = Depends(require_user)):
    db.unlink_trip_document(trip_id, doc_id)
    return {"ok": True}


@router.post("/finances/scan-receipt")
async def scan_receipt(
    file: UploadFile = File(...),
    account: str = Form(""),
    user: dict = Depends(require_user),
):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")
    mime = file.content_type or "image/jpeg"
    try:
        result = await receipt_svc.scan_and_log_transaction(content, mime, user, account)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Receipt scan failed: {exc}") from exc
    activity_svc.log(
        user,
        "created",
        "transaction",
        f"Receipt scan: {result['transaction']['description']}",
        entity_id=result["transaction"]["id"],
    )
    return result


@router.post("/finances/scan-email")
async def scan_email_receipts(user: dict = Depends(require_user)):
    """Scan the user's connected Gmail accounts for receipt emails; returns drafts (no writes)."""
    if not openrouter.is_configured():
        raise HTTPException(status_code=503, detail="OpenRouter not configured — required for receipt OCR")
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google not configured")
    try:
        result = await gmail_receipts.scan_for_user(user["id"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Email scan failed: {exc}") from exc
    return result


@router.post("/finances/import-email-receipts")
def import_email_receipts(body: EmailReceiptImport, user: dict = Depends(require_user)):
    """Commit reviewed email-receipt drafts into the ledger."""
    drafts = [d.model_dump() for d in body.drafts]
    created = gmail_receipts.commit_drafts(drafts, user, account_id=body.account_id or None)
    for txn in created:
        activity_svc.log(user, "created", "transaction", f"Email receipt: {txn['description']}", entity_id=txn["id"])
    return {"imported": len(created), "transactions": created}


@router.post("/notifications/send-reminders")
def send_reminders(_: dict = Depends(require_user)):
    return notify_svc.send_renewal_reminders()


@router.get("/notifications/log")
def notification_log(_: dict = Depends(require_user)):
    return {"items": db.list_notification_log()}


# --- Notification preferences ---

@router.get("/notifications/prefs")
def get_notification_prefs(_: dict = Depends(require_user)):
    return db.get_notification_prefs()


@router.patch("/notifications/prefs")
def update_notification_prefs(body: NotificationPrefsUpdate, _: dict = Depends(require_user)):
    return db.update_notification_prefs(body.model_dump(exclude_unset=True))


# --- Web Push (VAPID) ---

@router.get("/push/vapid-key")
def push_vapid_key(_: dict = Depends(require_user)):
    return {"key": push_svc.get_public_key(), "enabled": push_svc.is_configured()}


@router.post("/push/subscribe")
def push_subscribe(body: PushSubscribe, user: dict = Depends(require_user)):
    sub = db.add_push_subscription(user["id"], body.endpoint, body.p256dh, body.auth)
    return {"ok": True, "subscription": sub}


@router.post("/push/unsubscribe")
async def push_unsubscribe(request: Request, endpoint: str = "", _: dict = Depends(require_user)):
    ep = (endpoint or "").strip()
    if not ep:
        try:
            data = await request.json()
        except Exception:
            data = None
        ep = ((data or {}).get("endpoint") or "").strip()
    if not ep:
        raise HTTPException(status_code=400, detail="endpoint required")
    return {"ok": db.delete_push_subscription(ep)}


@router.post("/push/test")
def push_test(_: dict = Depends(require_user)):
    count = push_svc.notify("The Hub", "Test notification ✅")
    return {"sent": count}


# --- Tradespeople (household contacts directory) ---

@router.get("/tradespeople")
def list_tradespeople(_: dict = Depends(require_user)):
    return {"tradespeople": db.list_tradespeople()}


@router.post("/tradespeople")
def create_tradesperson(body: TradespersonCreate, user: dict = Depends(require_user)):
    person = db.create_tradesperson(body.model_dump())
    activity_svc.log(user, "created", "tradesperson", f"Added contact: {person['name']}", entity_id=person["id"])
    return person


@router.patch("/tradespeople/{person_id}")
def update_tradesperson(person_id: str, body: TradespersonUpdate, user: dict = Depends(require_user)):
    person = db.update_tradesperson(person_id, body.model_dump(exclude_unset=True))
    if not person:
        raise HTTPException(status_code=404, detail="Tradesperson not found")
    activity_svc.log(user, "updated", "tradesperson", f"Updated contact: {person['name']}", entity_id=person_id)
    return person


@router.delete("/tradespeople/{person_id}")
def delete_tradesperson(person_id: str, user: dict = Depends(require_user)):
    if not db.delete_tradesperson(person_id):
        raise HTTPException(status_code=404, detail="Tradesperson not found")
    activity_svc.log(user, "deleted", "tradesperson", "Removed contact", entity_id=person_id)
    return {"ok": True}


# --- Shopping list (shared household) ---

@router.get("/shopping")
def api_shopping(_: dict = Depends(require_user)):
    return {"items": db.list_shopping_items()}


@router.post("/shopping")
def create_shopping_item_route(body: ShoppingItemCreate, user: dict = Depends(require_user)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Item text is required")
    return {"item": db.create_shopping_item(text, added_by=user["id"])}


@router.patch("/shopping/{item_id}")
def set_shopping_item_done_route(
    item_id: str, done: bool = Body(..., embed=True), _: dict = Depends(require_user)
):
    item = db.set_shopping_item_done(item_id, done)
    if item is None:
        raise HTTPException(status_code=404, detail="Shopping item not found")
    return {"item": item}


@router.delete("/shopping/{item_id}")
def delete_shopping_item_route(item_id: str, _: dict = Depends(require_user)):
    if not db.delete_shopping_item(item_id):
        raise HTTPException(status_code=404, detail="Shopping item not found")
    return {"ok": True}


@router.post("/shopping/clear-done")
def clear_done_shopping_route(_: dict = Depends(require_user)):
    return {"cleared": db.clear_done_shopping_items()}


# --- Meal planner (weekly dinners) ---

@router.get("/meals")
def api_meals(start: str = "", end: str = "", _: dict = Depends(require_user)):
    """Meals for a date range. With no range, defaults to the current week (Mon..Sun)."""
    if not start or not end:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        start = monday.isoformat()
        end = (monday + timedelta(days=6)).isoformat()
    return {"meals": db.list_meal_plans(start, end), "start": start, "end": end}


@router.put("/meals")
def upsert_meal_route(body: MealPlanUpsert, _: dict = Depends(require_user)):
    title = (body.title or "").strip()
    day = (body.date or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Meal title is required")
    if len(day) != 10 or day.count("-") != 2:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format")
    return {"meal": db.upsert_meal_plan(day, title, body.ingredients or "")}


@router.delete("/meals/{day}")
def delete_meal_route(day: str, _: dict = Depends(require_user)):
    if not db.delete_meal_plan(day):
        raise HTTPException(status_code=404, detail="No meal planned for that day")
    return {"ok": True}


@router.post("/meals/{day}/to-shopping")
def meal_to_shopping_route(day: str, user: dict = Depends(require_user)):
    """Add a planned meal's ingredients to the shared shopping list."""
    meal = db.get_meal_plan(day)
    if not meal:
        raise HTTPException(status_code=404, detail="No meal planned for that day")
    raw = meal.get("ingredients") or ""
    parts = [p.strip() for chunk in raw.split("\n") for p in chunk.split(",")]
    added: list[str] = []
    for text in parts:
        if not text:
            continue
        db.create_shopping_item(text, added_by=user["id"])
        added.append(text)
    return {"added": added}


# --- Tasks & documents ---

@router.get("/tasks")
def api_tasks(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "tasks": db.list_tasks()}


@router.post("/tasks")
async def create_task(body: TaskCreate, user: dict = Depends(require_user)):
    users = db.list_users()
    assignee = body.assignee_id
    if assignee and assignee not in ("luke", "partner"):
        name_map = {u["name"].lower(): u["id"] for u in users}
        assignee = name_map.get(assignee.lower(), assignee)
    if assignee and assignee not in {u["id"] for u in users}:  # null = unassigned, always allowed
        raise HTTPException(status_code=400, detail="Unknown household member")
    task = db.create_task({**body.model_dump(), "assignee_id": assignee})
    await ai_assistant.notify_task_assignee(task, user)  # ping the other person if it's theirs
    return task


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskUpdate, user: dict = Depends(require_user)):
    before = db.get_task(task_id)
    if not before:
        raise HTTPException(status_code=404, detail="Task not found")
    patch = body.model_dump(exclude_unset=True, exclude={"notify"})
    if patch.get("assignee_id"):  # null = unassign, always allowed
        users = db.list_users()
        if patch["assignee_id"] not in ("luke", "partner"):
            name_map = {u["name"].lower(): u["id"] for u in users}
            patch["assignee_id"] = name_map.get(patch["assignee_id"].lower(), patch["assignee_id"])
        if patch["assignee_id"] not in {u["id"] for u in users}:
            raise HTTPException(status_code=400, detail="Unknown household member")
    task = db.update_task(task_id, patch)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    reassigned = "assignee_id" in patch and patch["assignee_id"] != before.get("assignee")
    if body.notify:
        # Ticking Notify sends to the task's owner on THIS save, whether or not the
        # owner changed. (No-ops when the owner is the sender or the task is
        # unassigned — you don't get pinged about your own task.)
        verb = "reassigned a task to you" if reassigned else "updated a task for you"
        await ai_assistant.notify_task_assignee(task, user, verb=verb)
    return task


@router.delete("/tasks/{task_id}")
def delete_task_route(task_id: str, _: dict = Depends(require_user)):
    if not db.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


# --- Chores (rotating household chores) ---

@router.get("/chores")
def api_chores(_: dict = Depends(require_user)):
    return {"chores": db.list_chores()}


@router.post("/chores")
def create_chore_route(body: ChoreCreate, _: dict = Depends(require_user)):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Chore title is required")
    return {"chore": db.create_chore(body.model_dump())}


@router.patch("/chores/{chore_id}")
def update_chore_route(chore_id: str, body: ChoreUpdate, _: dict = Depends(require_user)):
    chore = db.update_chore(chore_id, body.model_dump(exclude_unset=True))
    if chore is None:
        raise HTTPException(status_code=404, detail="Chore not found")
    return {"chore": chore}


@router.delete("/chores/{chore_id}")
def delete_chore_route(chore_id: str, _: dict = Depends(require_user)):
    ok = db.delete_chore(chore_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chore not found")
    return {"ok": ok}


@router.post("/chores/{chore_id}/done")
def complete_chore_route(chore_id: str, _: dict = Depends(require_user)):
    from server.services import chores as chores_svc

    c = chores_svc.complete_chore(chore_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Chore not found")
    return {"chore": c}


@router.get("/documents")
def api_documents(category: str = "all", _: dict = Depends(require_user)):
    return {
        "documents": db.list_documents(category if category != "all" else None),
        "categories": doc_files.DOCUMENT_CATEGORIES,
    }


@router.post("/documents")
def create_document(body: DocumentCreate, user: dict = Depends(require_user)):
    return db.create_document({**body.model_dump(), "user_id": user["id"]})


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("other"),
    expiry: str = Form(""),
    notes: str = Form(""),
    user: dict = Depends(require_user),
):
    content = await file.read()
    try:
        doc_files.validate_upload(file.filename or "file", len(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_files.ensure_upload_dir()
    doc_id = __import__("uuid").uuid4().hex[:12]
    safe = doc_files.safe_filename(file.filename or "document")
    stored = f"{doc_id}_{safe}"
    path = doc_files.UPLOAD_DIR / stored
    path.write_bytes(content)

    doc = db.create_document({
        "id": doc_id,
        "name": name.strip(),
        "category": doc_files.validate_category(category),
        "expiry": expiry.strip(),
        "notes": notes.strip(),
        "file_name": file.filename,
        "file_path": stored,
        "mime_type": doc_files.mime_for_path(path),
        "file_size": len(content),
        "user_id": user["id"],
    })
    return doc


@router.get("/documents/{doc_id}/file")
def download_document(doc_id: str, _: dict = Depends(require_user)):
    doc = db.get_document(doc_id)
    if not doc or not doc.get("file_path"):
        raise HTTPException(status_code=404, detail="File not found")
    path = doc_files.UPLOAD_DIR / doc["file_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        path,
        filename=doc.get("file_name") or doc["name"],
        media_type=doc_files.mime_for_path(path),
        content_disposition_type="attachment",
    )


@router.delete("/documents/{doc_id}")
def remove_document(doc_id: str, _: dict = Depends(require_user)):
    found, file_path = db.delete_document(doc_id)
    if not found:
        raise HTTPException(status_code=404, detail="Document not found")
    if file_path:  # metadata-only documents have no file to clean up
        disk = doc_files.UPLOAD_DIR / file_path
        if disk.is_file():
            disk.unlink()
    return {"ok": True}


# --- Family media ---

@router.get("/media")
def api_media(trip_id: str = "", _: dict = Depends(require_user)):
    tid = trip_id if trip_id and trip_id != "all" else None
    return {
        "items": db.list_media(tid),
        "trips": db.list_trips(),
    }


@router.post("/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    title: str = Form(""),
    caption: str = Form(""),
    trip_id: str = Form(""),
    taken_at: str = Form(""),
    user: dict = Depends(require_user),
):
    # Validate the extension up-front so we never stream a rejected file to disk;
    # the cap depends on photo vs video.
    ext = Path(file.filename or "").suffix.lower()
    if ext not in media_files.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type not allowed. Photos: {', '.join(sorted(media_files.PHOTO_EXTENSIONS))}; "
                f"videos: {', '.join(sorted(media_files.VIDEO_EXTENSIONS))}"
            ),
        )
    media_type = media_files.media_type_for_ext(ext)
    cap = media_files.VIDEO_MAX_BYTES if ext in media_files.VIDEO_EXTENSIONS else media_files.PHOTO_MAX_BYTES

    if trip_id:
        trips = {t["id"] for t in db.list_trips()}
        if trip_id not in trips:
            raise HTTPException(status_code=400, detail="Invalid trip")

    media_files.ensure_media_dir()
    mid = __import__("uuid").uuid4().hex[:12]
    safe = media_files.safe_filename(file.filename or "media")
    stored = f"{mid}_{safe}"
    path = media_files.MEDIA_DIR / stored

    # Stream to disk in chunks — never buffer a whole (possibly 500MB) video in RAM.
    try:
        written = await media_files.stream_upload_to_disk(file, path, cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    item = db.create_media({
        "id": mid,
        "title": title.strip() or Path(file.filename or "Photo").stem,
        "caption": caption.strip(),
        "media_type": media_type,
        "trip_id": trip_id or None,
        "file_name": file.filename,
        "file_path": stored,
        "mime_type": media_files.mime_for_path(path),
        "file_size": written,
        "taken_at": taken_at.strip(),
        "user_id": user["id"],
        "source": "upload",
    })
    return item


@router.get("/media/storage")
def media_storage(_: dict = Depends(require_user)):
    return media_files.storage_stats()


@router.get("/media/{media_id}/file")
def serve_media(media_id: str, _: dict = Depends(require_user)):
    item = db.get_media(media_id)
    if not item or not item.get("file_path"):
        raise HTTPException(status_code=404, detail="Media not found")
    path = media_files.MEDIA_DIR / item["file_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        path,
        filename=item.get("file_name") or item["title"],
        media_type=media_files.mime_for_path(path),
        content_disposition_type="inline",
    )


@router.patch("/media/{media_id}")
def patch_media(media_id: str, body: MediaUpdate, _: dict = Depends(require_user)):
    data = body.model_dump(exclude_unset=True)
    if "trip_id" in data and data["trip_id"]:
        trips = {t["id"] for t in db.list_trips()}
        if data["trip_id"] not in trips:
            raise HTTPException(status_code=400, detail="Invalid trip")
    item = db.update_media(media_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found")
    return item


@router.delete("/media/{media_id}")
def remove_media(media_id: str, _: dict = Depends(require_user)):
    file_path = db.delete_media(media_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Media not found")
    disk = media_files.MEDIA_DIR / file_path
    if disk.is_file():
        disk.unlink()
    return {"ok": True}


@router.patch("/members/{user_id}")
def update_member(user_id: str, body: MemberUpdate, actor: dict = Depends(require_user)):
    member = db.update_user(user_id, body.model_dump(exclude_unset=True))
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    activity_svc.log(actor, "updated", "member", f"Updated member: {member['name']}", entity_id=user_id)
    return member


def _iso_or_none(value: str | None) -> str | None:
    """Return value if it parses as ISO-8601, else None (drops legacy junk like 'just now')."""
    if not value:
        return None
    try:
        datetime.fromisoformat(value)
        return value
    except (ValueError, TypeError):
        return None


@router.get("/settings")
def api_settings(_: dict = Depends(require_user)):
    users = [db.user_public(u) for u in db.list_users()]
    google_last = _iso_or_none(db.get_setting("google_last_sync", None))
    banking_last = _iso_or_none(db.get_setting("banking_last_sync", None))
    last_sync = max([t for t in (google_last, banking_last) if t], default=None)
    return {
        "users": users,
        "documents": db.list_documents(),
        "sync": {
            "google_last": google_last,
            "banking_last": banking_last,
            "last_sync": last_sync,
            "auto_sync": "hourly",
            "status": "ok",
        },
        "google_accounts": db.list_google_accounts(),
        "integrations": {
            "google_calendar": google_calendar.is_configured(),
            "openrouter": openrouter.is_configured(),
            "open_banking": open_banking.is_configured(),
            "email": notify_svc.is_configured(),
            "google_writeback": google_calendar.is_configured(),
            "receipt_scan": openrouter.is_configured(),
            "whatsapp": whatsapp_svc.is_configured(),
            "weather": weather_svc.is_configured(),
        },
        "notification_log": db.list_notification_log(10),
    }


# --- Occasions (annual birthdays / anniversaries with countdowns) ---

@router.get("/occasions")
def api_occasions(_: dict = Depends(require_user)):
    return {"occasions": occasions.upcoming_occasions()}


@router.post("/occasions")
def create_occasion_route(body: OccasionCreate, _: dict = Depends(require_user)):
    if not (body.title or "").strip() or not (body.date or "").strip():
        raise HTTPException(status_code=400, detail="Title and date are required")
    return {"occasion": db.create_occasion(body.model_dump())}


@router.patch("/occasions/{occasion_id}")
def update_occasion_route(occasion_id: str, body: OccasionUpdate, _: dict = Depends(require_user)):
    occasion = db.update_occasion(occasion_id, body.model_dump(exclude_unset=True))
    if occasion is None:
        raise HTTPException(status_code=404, detail="Occasion not found")
    return {"occasion": occasion}


@router.delete("/occasions/{occasion_id}")
def delete_occasion_route(occasion_id: str, _: dict = Depends(require_user)):
    if not db.delete_occasion(occasion_id):
        raise HTTPException(status_code=404, detail="Occasion not found")
    return {"ok": True}


# --- Inventory (household items & warranties) ---

@router.get("/inventory")
def api_inventory(_: dict = Depends(require_user)):
    return {"items": db.list_inventory()}


@router.post("/inventory")
def create_inventory_route(body: InventoryCreate, _: dict = Depends(require_user)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Item name is required")
    return {"item": db.create_inventory_item(body.model_dump())}


@router.patch("/inventory/{item_id}")
def update_inventory_route(item_id: str, body: InventoryUpdate, _: dict = Depends(require_user)):
    item = db.update_inventory_item(item_id, body.model_dump(exclude_unset=True))
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return {"item": item}


@router.delete("/inventory/{item_id}")
def delete_inventory_route(item_id: str, _: dict = Depends(require_user)):
    if not db.delete_inventory_item(item_id):
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return {"ok": True}


# --- Vehicles (cars & their MOT/tax/insurance/service renewals) ---

@router.get("/vehicles")
def api_vehicles(_: dict = Depends(require_user)):
    return {"vehicles": db.list_vehicles()}


@router.post("/vehicles")
def create_vehicle_route(body: VehicleCreate, _: dict = Depends(require_user)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Vehicle name is required")
    return {"vehicle": db.create_vehicle(body.model_dump())}


@router.patch("/vehicles/{vehicle_id}")
def update_vehicle_route(vehicle_id: str, body: VehicleUpdate, _: dict = Depends(require_user)):
    vehicle = db.update_vehicle(vehicle_id, body.model_dump(exclude_unset=True))
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"vehicle": vehicle}


@router.delete("/vehicles/{vehicle_id}")
def delete_vehicle_route(vehicle_id: str, _: dict = Depends(require_user)):
    if not db.delete_vehicle(vehicle_id):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"ok": True}


@router.post("/vehicles/lookup")
async def vehicle_lookup_route(reg: str = Body(..., embed=True), _: dict = Depends(require_user)):
    """Auto-fill a vehicle from its number plate via the optional DVLA lookup.

    Dormant without a key: returns {"configured": False} with a helpful message so
    the UI can point the user at DVLA_API_KEY rather than erroring."""
    if not vehicles_svc.is_lookup_configured():
        return {
            "configured": False,
            "message": "Reg lookup isn't set up — add a free DVLA API key (DVLA_API_KEY) to enable auto-fill.",
        }
    try:
        result = await vehicles_svc.lookup_reg(reg)
    except ValueError:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    except RuntimeError as exc:
        # Keep the UI non-crashing: surface the message at 200 so it can be shown inline.
        return {"configured": True, "error": str(exc)}
    return {"configured": True, **result}


# --- Recipes (household recipe book, plans into the meal planner) ---

@router.get("/recipes")
def api_recipes(_: dict = Depends(require_user)):
    return {"recipes": db.list_recipes()}


@router.post("/recipes")
def create_recipe_route(body: RecipeCreate, _: dict = Depends(require_user)):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Recipe title is required")
    return {"recipe": db.create_recipe(body.model_dump())}


@router.patch("/recipes/{recipe_id}")
def update_recipe_route(recipe_id: str, body: RecipeUpdate, _: dict = Depends(require_user)):
    recipe = db.update_recipe(recipe_id, body.model_dump(exclude_unset=True))
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"recipe": recipe}


@router.delete("/recipes/{recipe_id}")
def delete_recipe_route(recipe_id: str, _: dict = Depends(require_user)):
    if not db.delete_recipe(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"ok": True}


@router.post("/recipes/{recipe_id}/plan")
def plan_recipe_route(
    recipe_id: str, date: str = Body(..., embed=True), _: dict = Depends(require_user)
):
    """Drop a recipe onto the meal planner for a given day (reuses upsert_meal_plan)."""
    recipe = db.get_recipe(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    day = (date or "").strip()
    if len(day) != 10 or day.count("-") != 2:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format")
    meal = db.upsert_meal_plan(day, recipe["title"], recipe.get("ingredients") or "")
    return {"meal": meal}


# --- Dependents (children & pets) with their care items ---

@router.get("/dependents")
def api_dependents(_: dict = Depends(require_user)):
    return {"dependents": db.list_dependents()}


@router.post("/dependents")
def create_dependent_route(body: DependentCreate, _: dict = Depends(require_user)):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Name is required")
    return {"dependent": db.create_dependent(body.model_dump())}


@router.patch("/dependents/{dependent_id}")
def update_dependent_route(dependent_id: str, body: DependentUpdate, _: dict = Depends(require_user)):
    dependent = db.update_dependent(dependent_id, body.model_dump(exclude_unset=True))
    if dependent is None:
        raise HTTPException(status_code=404, detail="Dependent not found")
    return {"dependent": dependent}


@router.delete("/dependents/{dependent_id}")
def delete_dependent_route(dependent_id: str, _: dict = Depends(require_user)):
    if not db.delete_dependent(dependent_id):
        raise HTTPException(status_code=404, detail="Dependent not found")
    return {"ok": True}


# --- Care items (vaccinations, check-ups, grooming, etc.) ---

@router.get("/care")
def api_care(dependent_id: str = "", _: dict = Depends(require_user)):
    return {"items": db.list_care_items(dependent_id or None)}


@router.post("/care")
def create_care_route(body: CareItemCreate, _: dict = Depends(require_user)):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Care item title is required")
    if not (body.dependent_id or "").strip() or not db.get_dependent(body.dependent_id):
        raise HTTPException(status_code=400, detail="Unknown dependent")
    return {"item": db.create_care_item(body.model_dump())}


@router.patch("/care/{item_id}")
def update_care_route(item_id: str, body: CareItemUpdate, _: dict = Depends(require_user)):
    item = db.update_care_item(item_id, body.model_dump(exclude_unset=True))
    if item is None:
        raise HTTPException(status_code=404, detail="Care item not found")
    return {"item": item}


@router.post("/care/{item_id}/done")
def care_done_route(item_id: str, _: dict = Depends(require_user)):
    item = db.update_care_item(item_id, {"done": True})
    if item is None:
        raise HTTPException(status_code=404, detail="Care item not found")
    return {"item": item}


@router.delete("/care/{item_id}")
def delete_care_route(item_id: str, _: dict = Depends(require_user)):
    if not db.delete_care_item(item_id):
        raise HTTPException(status_code=404, detail="Care item not found")
    return {"ok": True}


# --- Wishlist (gift ideas & things the household wants) ---

@router.get("/wishlist")
def api_wishlist(person: str = "", _: dict = Depends(require_user)):
    return {"items": db.list_wishlist_items(person or None)}


@router.post("/wishlist")
def create_wishlist_route(body: WishlistCreate, _: dict = Depends(require_user)):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Wishlist title is required")
    return {"item": db.create_wishlist_item(body.model_dump())}


@router.patch("/wishlist/{item_id}")
def update_wishlist_route(item_id: str, body: WishlistUpdate, _: dict = Depends(require_user)):
    item = db.update_wishlist_item(item_id, body.model_dump(exclude_unset=True))
    if item is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"item": item}


@router.post("/wishlist/{item_id}/purchased")
def set_wishlist_purchased_route(
    item_id: str, purchased: bool = Body(..., embed=True), _: dict = Depends(require_user)
):
    item = db.update_wishlist_item(item_id, {"purchased": bool(purchased)})
    if item is None:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"item": item}


@router.delete("/wishlist/{item_id}")
def delete_wishlist_route(item_id: str, _: dict = Depends(require_user)):
    if not db.delete_wishlist_item(item_id):
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    return {"ok": True}
