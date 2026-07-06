"""Scan Gmail for receipts and turn them into expense drafts.

Uses the read-only Gmail scope granted when a Google account is connected. Finds
recent receipt-like emails with image attachments, runs each attachment through
the existing OpenRouter receipt OCR (server.services.receipts), and returns draft
expenses for review. Nothing is written to the ledger unless the caller commits.

Requires the account to have been connected AFTER the gmail.readonly scope was
added — otherwise the Gmail calls 403 and we surface `needs_reconnect`.
"""

from __future__ import annotations

import base64
import logging

from server import database as db
from server.services import google_calendar, receipts

logger = logging.getLogger(__name__)

# Gmail search: recent, likely-receipt, with an attachment.
QUERY = 'newer_than:60d has:attachment (receipt OR invoice OR "order confirmation" OR purchase)'
IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp", "image/heic")
MAX_MESSAGES = 12  # cap OCR calls (cost/latency)


class NeedsReconnect(Exception):
    """Raised when the account lacks the Gmail scope (connected before it existed)."""


def _gmail(token_json: str):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=google_calendar._credentials(token_json), cache_discovery=False)


def _headers(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in (payload.get("headers") or [])}


def _image_attachments(payload: dict) -> list[tuple[str, str]]:
    """Return (attachmentId, mimeType) for image parts, walking nested parts."""
    out: list[tuple[str, str]] = []

    def walk(part):
        if part.get("mimeType") in IMAGE_MIMES:
            att = (part.get("body") or {}).get("attachmentId")
            if att:
                out.append((att, part["mimeType"]))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    return out


async def scan_account(account_internal: dict, limit: int = MAX_MESSAGES) -> list[dict]:
    """Return draft expenses parsed from receipt emails in one Google account."""
    from googleapiclient.errors import HttpError

    try:
        svc = _gmail(account_internal["token_json"])
        listing = svc.users().messages().list(userId="me", q=QUERY, maxResults=limit).execute()
    except HttpError as exc:
        if exc.resp.status in (401, 403):
            raise NeedsReconnect(account_internal.get("email", "account"))
        raise

    drafts: list[dict] = []
    for msg in listing.get("messages", []):
        mid = msg["id"]
        try:
            full = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        except Exception:
            continue
        payload = full.get("payload") or {}
        hdrs = _headers(payload)
        for att_id, mime in _image_attachments(payload):
            try:
                att = svc.users().messages().attachments().get(userId="me", messageId=mid, id=att_id).execute()
                raw = base64.urlsafe_b64decode(att["data"])
                extracted = await receipts.parse_receipt(raw, mime)
            except Exception as exc:
                logger.info("Skipped attachment on message %s: %s", mid, exc)
                continue
            drafts.append({
                "message_id": mid,
                "email_subject": hdrs.get("subject", ""),
                "email_from": hdrs.get("from", ""),
                "account_email": account_internal.get("email", ""),
                "description": extracted["description"],
                "amount": extracted["amount"],
                "date": extracted["date"],
                "category": extracted["category"],
                "merchant": extracted.get("merchant", ""),
            })
            break  # one receipt per email is plenty
    return drafts


async def scan_for_user(user_id: str, limit: int = MAX_MESSAGES) -> dict:
    """Scan all of a user's connected Google accounts. Returns drafts + status."""
    accounts = db.list_google_accounts(user_id)
    drafts: list[dict] = []
    needs_reconnect: list[str] = []
    for pub in accounts:
        acct = db.get_google_account_internal(pub["id"])
        if not acct:
            continue
        try:
            drafts.extend(await scan_account(acct, limit=limit))
        except NeedsReconnect as exc:
            needs_reconnect.append(str(exc))
        except Exception:
            logger.exception("Gmail scan failed for %s", pub.get("email"))
    return {"drafts": drafts, "needs_reconnect": needs_reconnect, "scanned_accounts": len(accounts)}


def commit_drafts(drafts: list[dict], user: dict, account_id: str = "joint") -> list[dict]:
    """Insert reviewed drafts into the ledger as transactions (+ receipt records)."""
    import json as _json

    created = []
    for d in drafts:
        amount = float(d.get("amount") or 0)
        if amount > 0:
            amount = -abs(amount)
        txn = db.create_transaction({
            "description": d.get("description") or d.get("merchant") or "Email receipt",
            "amount": round(amount, 2),
            "category": d.get("category") or "Other",
            "date": d.get("date") or None,
            "account_id": account_id,
        })
        db.create_receipt({
            "transaction_id": txn["id"],
            "user_id": user["id"],
            "merchant": d.get("merchant", ""),
            "extracted_json": _json.dumps(d),
        })
        created.append(txn)
    return created
