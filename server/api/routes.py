"""REST API routes."""

import logging
import secrets

from urllib.parse import quote

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from server import auth, database as db
from server.services import csv_import, dashboard as dash, documents as doc_files, google_calendar, openrouter, open_banking
from server.services import assistant as ai_assistant, media as media_files, subscriptions as sub_svc
from server.services import activity as activity_svc, briefing as briefing_svc, renewals as renewals_svc
from server.services import finance_merge, notifications as notify_svc, receipts as receipt_svc
from server.services import search as search_svc, trips as trips_svc
from shared.schemas import (
    AppointmentCreate,
    AssistantChatRequest,
    BillCreate,
    DocumentCreate,
    EventCreate,
    HolidayIdeaRequest,
    LoginRequest,
    MaintenanceCreate,
    MaintenanceUpdate,
    MediaUpdate,
    SearchQuery,
    SubscriptionUpdate,
    TaskCreate,
    TaskUpdate,
    TransactionCreate,
    TripCreate,
    TripPackingRequest,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/auth/login")
def login(body: LoginRequest, request: Request):
    user = auth.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session.clear()
    request.session["user"] = user
    return {"user": user}


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
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user"] = user["id"]
    url = google_calendar.authorization_url(state)
    return RedirectResponse(url)


def _clear_google_oauth_session(request: Request) -> None:
    request.session.pop("google_oauth_state", None)
    request.session.pop("google_oauth_user", None)


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        _clear_google_oauth_session(request)
        return RedirectResponse("/?google_error=1")
    expected = request.session.get("google_oauth_state")
    user_id = request.session.get("google_oauth_user")
    if not expected or state != expected or not user_id:
        _clear_google_oauth_session(request)
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    session_user = request.session.get("user")
    if session_user and session_user.get("id") != user_id:
        _clear_google_oauth_session(request)
        return RedirectResponse(f"/?google_error={quote('Session mismatch — sign in and try again')}")
    try:
        token = google_calendar.exchange_code(code)
        db.save_google_token(user_id, __import__("json").dumps(token))
        google_calendar.sync_user_calendar(user_id)
    except Exception as exc:
        _clear_google_oauth_session(request)
        return RedirectResponse(f"/?google_error={quote(str(exc)[:80])}")
    _clear_google_oauth_session(request)
    return RedirectResponse("/?google_connected=1")


@router.post("/calendar/sync")
def calendar_sync(_: dict = Depends(require_user)):
    if not google_calendar.is_configured():
        raise HTTPException(status_code=503, detail="Google Calendar not configured")
    results = google_calendar.sync_all_users()
    return {"synced": results, "google_last": db.get_setting("google_last_sync", "just now")}


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
        except Exception as exc:
            results.append({"provider": conn["provider_name"], "error": str(exc)})
    sub_svc.refresh_subscriptions()
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
    return dash.build_dashboard()


@router.get("/calendar")
def api_calendar(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "events": db.list_events()}


@router.post("/events")
def create_event(body: EventCreate, user: dict = Depends(require_user)):
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
            google_calendar.push_event_to_google(uid, event)
        except Exception as exc:
            logger.warning("Google write-back failed: %s", exc)
    activity_svc.log(user, "created", "event", f"Added event: {body.title}", entity_id=event["id"])
    return event


# --- Finances ---

@router.get("/finances")
def api_finances(_: dict = Depends(require_user)):
    return {
        "bills": db.list_bills(),
        "transactions": db.list_transactions(),
        "accounts": db.list_accounts(),
        "budgets": db.list_budgets(),
        "savings_goals": db.list_savings_goals(),
        "summary": db.finance_summary(),
        "connections": db.list_bank_connections(),
        "banking_configured": open_banking.is_configured(),
        "merged_recurring": finance_merge.build_merged_recurring(),
    }


@router.post("/bills")
def create_bill(body: BillCreate, _: dict = Depends(require_user)):
    return db.create_bill(body.model_dump())


@router.post("/bills/{bill_id}/pay")
def pay_bill(bill_id: str, _: dict = Depends(require_user)):
    bill = db.mark_bill_paid(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.post("/transactions")
def create_transaction(body: TransactionCreate, _: dict = Depends(require_user)):
    account_map = {a["name"]: a["id"] for a in db.list_accounts()}
    account_id = body.account_id
    if account_id and account_id not in account_map.values():
        account_id = account_map.get(account_id, "starling")
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
        "account_id": account_id or "joint",
        "date": body.date,
    })


CSV_MAX_BYTES = 5 * 1024 * 1024


@router.post("/finances/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    account: str = "joint",
    _: dict = Depends(require_user),
):
    raw = await file.read()
    if len(raw) > CSV_MAX_BYTES:
        raise HTTPException(status_code=400, detail="CSV file too large (max 5 MB)")
    content = raw.decode("utf-8-sig", errors="replace")
    try:
        rows = csv_import.parse_csv(content, default_account=account)
        count = db.import_transactions(rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"imported": count}


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
    visible = [s for s in all_items if s["status"] != "ignored"]
    return {
        "subscription": sub,
        "summary": sub_svc.build_summary(all_items),
        "subscriptions": visible,
    }


# --- Appointments ---

@router.get("/appointments")
def api_appointments(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "appointments": db.list_appointments()}


@router.post("/appointments")
def create_appointment(body: AppointmentCreate, user: dict = Depends(require_user)):
    return db.create_appointment(body.model_dump(), user["id"])


# --- Holidays & AI ---

@router.get("/holidays")
def api_holidays(_: dict = Depends(require_user)):
    return {"trips": db.list_trips(), "ideas": db.list_holiday_ideas()}


@router.post("/holidays/trips")
def create_trip(body: TripCreate, _: dict = Depends(require_user)):
    return db.create_trip(body.model_dump())


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


@router.get("/search")
def api_search(q: str = "", _: dict = Depends(require_user)):
    return search_svc.search(q)


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
    account: str = Form("joint"),
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


@router.post("/notifications/send-reminders")
def send_reminders(_: dict = Depends(require_user)):
    return notify_svc.send_renewal_reminders()


@router.get("/notifications/log")
def notification_log(_: dict = Depends(require_user)):
    return {"items": db.list_notification_log()}


# --- Tasks & documents ---

@router.get("/tasks")
def api_tasks(_: dict = Depends(require_user)):
    return {"users": [db.user_public(u) for u in db.list_users()], "tasks": db.list_tasks()}


@router.post("/tasks")
def create_task(body: TaskCreate, _: dict = Depends(require_user)):
    assignee = body.assignee_id
    if assignee and assignee not in ("luke", "partner"):
        name_map = {u["name"].lower(): u["id"] for u in db.list_users()}
        assignee = name_map.get(assignee.lower(), assignee)
    return db.create_task({**body.model_dump(), "assignee_id": assignee})


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskUpdate, _: dict = Depends(require_user)):
    task = db.update_task(task_id, body.model_dump(exclude_unset=True))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


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
    file_path = db.delete_document(doc_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Document not found")
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
    content = await file.read()
    try:
        ext, media_type = media_files.validate_upload(file.filename or "file", len(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if trip_id:
        trips = {t["id"] for t in db.list_trips()}
        if trip_id not in trips:
            raise HTTPException(status_code=400, detail="Invalid trip")

    media_files.ensure_media_dir()
    mid = __import__("uuid").uuid4().hex[:12]
    safe = media_files.safe_filename(file.filename or "media")
    stored = f"{mid}_{safe}"
    path = media_files.MEDIA_DIR / stored
    path.write_bytes(content)

    item = db.create_media({
        "id": mid,
        "title": title.strip() or Path(file.filename or "Photo").stem,
        "caption": caption.strip(),
        "media_type": media_type,
        "trip_id": trip_id or None,
        "file_name": file.filename,
        "file_path": stored,
        "mime_type": media_files.mime_for_path(path),
        "file_size": len(content),
        "taken_at": taken_at.strip(),
        "user_id": user["id"],
    })
    return item


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


@router.get("/settings")
def api_settings(_: dict = Depends(require_user)):
    users = [db.user_public(u) for u in db.list_users()]
    return {
        "users": users,
        "documents": db.list_documents(),
        "sync": {"google_last": db.get_setting("google_last_sync", "never"), "status": "ok"},
        "integrations": {
            "google_calendar": google_calendar.is_configured(),
            "openrouter": openrouter.is_configured(),
            "open_banking": open_banking.is_configured(),
            "email": notify_svc.is_configured(),
            "google_writeback": google_calendar.is_configured(),
            "receipt_scan": openrouter.is_configured(),
        },
        "notification_log": db.list_notification_log(10),
    }
