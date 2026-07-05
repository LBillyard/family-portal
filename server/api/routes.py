"""REST API routes."""

import logging
import secrets

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from server import auth, database as db
from server.services import csv_import, dashboard as dash, documents as doc_files, google_calendar, openrouter, open_banking
from server.services import assistant as ai_assistant
from shared.schemas import (
    AppointmentCreate,
    AssistantChatRequest,
    BillCreate,
    DocumentCreate,
    EventCreate,
    HolidayIdeaRequest,
    LoginRequest,
    TaskCreate,
    TaskUpdate,
    TransactionCreate,
    TripCreate,
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
    return db.create_event(
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
        },
        "notifications": [],
    }
