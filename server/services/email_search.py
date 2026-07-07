"""On-demand Gmail search for the assistant, plus filing an email attachment to the
Vault.

Read-only search over the ACTING user's own connected Google account(s) — the same
read-only Gmail connection the memory-scan and receipts features use. The assistant
calls search() when the user asks about something in their email, and
file_attachment() when they want to keep a document (invoice, certificate, policy)
from an email in the Hub's Vault.

Both functions are SYNC and blocking (googleapiclient), so the async assistant wraps
them in asyncio.to_thread. They never raise into the chat flow — failures come back
as data the model can relay.
"""

from __future__ import annotations

import base64
import logging
import uuid

from server import database as db
from server.services import documents as doc_files
from server.services import gmail_memory  # reuse _gmail / _headers / _body_text

logger = logging.getLogger(__name__)


def is_available(user_id: str) -> bool:
    """True when the user has at least one connected Google account to search."""
    return bool(db.list_google_accounts(user_id))


def _accounts(user_id: str):
    for pub in db.list_google_accounts(user_id):
        acct = db.get_google_account_internal(pub["id"])
        if acct:
            yield pub, acct


def _collect_attachments(payload: dict, out: list) -> None:
    body = payload.get("body") or {}
    fn = payload.get("filename") or ""
    if fn and body.get("attachmentId"):
        out.append({"filename": fn, "mime": payload.get("mimeType", ""),
                    "size": body.get("size"), "att_id": body["attachmentId"]})
    for part in payload.get("parts") or []:
        _collect_attachments(part, out)


def search(user_id: str, query: str, limit: int = 8) -> dict:
    """Search the user's Gmail. Returns {results, needs_reconnect, searched_accounts}.
    Each result: {account, message_id, date, from, subject, snippet, attachments[]}."""
    from googleapiclient.errors import HttpError

    q = (query or "").strip()
    if not q:
        return {"results": [], "error": "Please give me something to search for."}
    if not is_available(user_id):
        return {"results": [], "error": "No Google account is connected — link Gmail in Settings first."}

    limit = max(1, min(int(limit or 8), 12))
    results: list[dict] = []
    needs_reconnect: list[str] = []
    searched: list[str] = []
    for pub, acct in _accounts(user_id):
        email = pub.get("email", "")
        searched.append(email)
        try:
            svc = gmail_memory._gmail(acct["token_json"])
            listing = svc.users().messages().list(userId="me", q=q, maxResults=limit).execute()
        except HttpError as exc:
            if getattr(exc.resp, "status", 0) in (401, 403):
                needs_reconnect.append(email)
            else:
                logger.warning("Gmail search failed for %s: %s", email, exc)
            continue
        except Exception:
            logger.exception("Gmail search error for %s", email)
            continue
        for m in listing.get("messages", [])[:limit]:
            try:
                full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            except Exception:
                continue
            payload = full.get("payload", {}) or {}
            h = gmail_memory._headers(payload)
            atts: list[dict] = []
            _collect_attachments(payload, atts)
            results.append({
                "account": email,
                "message_id": m["id"],
                "date": h.get("date", ""),
                "from": h.get("from", "")[:120],
                "subject": h.get("subject", "")[:200],
                "snippet": gmail_memory._body_text(payload)[:600],
                "attachments": [a["filename"] for a in atts],
            })
    return {"results": results, "needs_reconnect": needs_reconnect, "searched_accounts": searched}


def file_attachment(user_id: str, message_id: str, filename: str | None = None) -> dict:
    """Download attachment(s) from a specific email and save them to the Vault.
    If `filename` is given, only that one; otherwise every attachment the Vault accepts.
    Returns {ok, saved:[{filename, document_id, name}], skipped:[...]}."""
    from googleapiclient.errors import HttpError

    mid = (message_id or "").strip()
    if not mid:
        return {"ok": False, "error": "Which email? I need the message to pull the attachment from."}

    for pub, acct in _accounts(user_id):
        try:
            svc = gmail_memory._gmail(acct["token_json"])
            full = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        except HttpError:
            continue  # message not in this account (id is per-mailbox) — try the next
        except Exception:
            logger.exception("Fetching email %s failed", mid)
            continue

        payload = full.get("payload", {}) or {}
        subject = gmail_memory._headers(payload).get("subject", "Email attachment")
        atts: list[dict] = []
        _collect_attachments(payload, atts)
        if filename:
            atts = [a for a in atts if a["filename"] == filename]
        if not atts:
            return {"ok": False, "error": "That email has no matching attachment to save."}

        saved: list[dict] = []
        skipped: list[dict] = []
        for a in atts:
            try:
                data = svc.users().messages().attachments().get(
                    userId="me", messageId=mid, id=a["att_id"]).execute()
                content = base64.urlsafe_b64decode(data["data"])
            except Exception:
                skipped.append({"filename": a["filename"], "reason": "could not download"})
                continue
            try:
                doc_files.validate_upload(a["filename"], len(content))
            except ValueError as exc:
                skipped.append({"filename": a["filename"], "reason": str(exc)})
                continue
            doc_files.ensure_upload_dir()
            doc_id = uuid.uuid4().hex[:12]
            stored = f"{doc_id}_{doc_files.safe_filename(a['filename'])}"
            path = doc_files.UPLOAD_DIR / stored
            try:
                path.write_bytes(content)
                doc = db.create_document({
                    "id": doc_id,
                    "name": f"{subject} — {a['filename']}"[:120],
                    "category": "other",
                    "expiry": "",
                    "notes": f"Saved from email ({pub.get('email','')})",
                    "file_name": a["filename"],
                    "file_path": stored,
                    "mime_type": doc_files.mime_for_path(path),
                    "file_size": len(content),
                    "user_id": user_id,
                })
                saved.append({"filename": a["filename"], "document_id": doc_id,
                              "name": doc.get("name") if isinstance(doc, dict) else None})
            except Exception:
                logger.exception("Saving attachment %s failed", a["filename"])
                skipped.append({"filename": a["filename"], "reason": "could not save"})
        return {"ok": bool(saved), "saved": saved, "skipped": skipped}

    return {"ok": False, "error": "I couldn't find that email in your connected account(s)."}
