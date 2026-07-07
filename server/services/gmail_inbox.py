"""Scan Gmail for actionable bookings/appointments/renewable documents and file them.

Mirrors gmail_memory.py: reuses the same read-only Gmail connection, pulls a
booking/travel/appointment slice of the inbox, runs the text through the AI to
extract CONCRETE, DATED items (trips, appointments, renewable documents), dedupes
them, and returns candidates for the user to review. Nothing is written until the
user imports their selection via commit().
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from server import database as db
from server.services import memory
from server.services.gmail_memory import NeedsReconnect, _body_text, _gmail, _headers

logger = logging.getLogger(__name__)

# Actionable-inbox slice — bookings, travel, appointments, renewable documents.
QUERY = (
    'newer_than:1y ('
    'booking OR reservation OR itinerary OR flight OR flights OR hotel OR "e-ticket" '
    'OR ticket OR appointment OR confirmed OR confirmation OR reserved '
    'OR insurance OR policy OR warranty OR passport OR renewal OR "MOT"'
    ')'
)
MAX_MESSAGES = 40
BATCH = 6  # emails per extraction call
BODY_CHARS = 1400

# Per-kind fields we accept from the model (everything else is dropped).
_KIND_FIELDS = {
    "trip": ("destination", "start", "end"),
    "appointment": ("provider", "datetime", "category"),
    "document": ("expiry_date", "notes"),
}

_SYS = """You extract CONCRETE, DATED bookings, appointments, and renewable documents from a family's emails so they can be filed into a household organiser.

Return ONLY JSON, no markdown: {"items":[{"kind":"trip|appointment|document","title": str, "source": int, ...per-kind fields}]}

Per-kind fields (include ONLY when you actually know them — never guess):
- trip: {"destination": str, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
- appointment: {"provider": str, "datetime": "YYYY-MM-DDTHH:MM", "category": str}
- document: {"expiry_date": "YYYY-MM-DD", "notes": str}

ONLY extract:
- A "trip" is the FAMILY TRAVELLING/STAYING AWAY: a flight, a hotel/apartment stay, a holiday or getaway with a destination. A parcel/furniture/grocery DELIVERY to the house is NOT a trip.
- An "appointment" is a confirmed date/time the family ATTENDS IN PERSON: medical, dental, a property viewing, a service visit, a booked class/event with a real date. It must be something they actually go to.
- A "document" is a renewable/expiring record worth a reminder: insurance policy, warranty, passport, MOT/road tax, or a membership/subscription with a renewal or expiry date.

SKIP entirely (return nothing for these):
- Marketing, newsletters, promotions, "you might like", offers, webinars/events they did not actually register for.
- Purchase receipts / order confirmations for goods, and parcel/delivery notifications (a delivery is neither a trip nor an appointment).
- Security/account notifications: "new device login", login/sign-in attempts, verification/OTP/2FA codes, password resets — these have a timestamp but are NOT appointments.
- Vague, speculative, undated or "considering" mentions.
- Anything without a clear, concrete title.

The timestamp an email was SENT is never itself an appointment time — only extract a date/time that the email states the event actually happens.

RULES:
- "title" is a short human label, e.g. "Flights to Barcelona", "Dentist check-up", "Car insurance renewal".
- Use ISO dates/datetimes. Omit any field you don't know.
- "source" = the [n] number of the email the item came from.
- Quality over quantity — {"items":[]} is a perfectly good answer."""


def _model() -> str:
    """Classifying bookings/appointments/documents from messy email needs solid
    instruction-following (gpt-4o-mini mislabels e.g. a furniture delivery as a
    'trip' and a login-alert as an 'appointment'). Use a stronger model, matching
    trip_intel; overridable via INBOX_EXTRACT_MODEL / OPENROUTER_SMART_MODEL."""
    return (os.environ.get("INBOX_EXTRACT_MODEL", "").strip()
            or os.environ.get("OPENROUTER_SMART_MODEL", "").strip()
            or "openai/gpt-4o")


def _str(value) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _clean_item(raw: dict, source_subject: str) -> dict | None:
    """Validate one model item into a storable candidate, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    kind = _str(raw.get("kind")).lower()
    title = _str(raw.get("title"))
    if kind not in _KIND_FIELDS or not title:
        return None
    item: dict = {"kind": kind, "title": title, "source_subject": source_subject}
    for field in _KIND_FIELDS[kind]:
        val = _str(raw.get(field))
        if val:
            item[field] = val
    return item


async def _extract_batch(emails: list[dict]) -> list[dict]:
    blocks = [f"[{e['n']}] From: {e['from']} | Subject: {e['subject']}\n{e['body'][:BODY_CHARS]}" for e in emails]
    user = "EMAILS:\n" + "\n\n".join(blocks)
    payload = {
        "model": _model(),
        "messages": [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions", headers=memory._headers(), json=payload
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content).get("items", [])
    except ValueError:
        return []


async def _scan_account(acct: dict, limit: int) -> tuple[list[dict], int]:
    from googleapiclient.errors import HttpError

    try:
        svc = _gmail(acct["token_json"])
        listing = svc.users().messages().list(userId="me", q=QUERY, maxResults=limit).execute()
    except HttpError as exc:
        if exc.resp.status in (401, 403):
            raise NeedsReconnect(acct.get("email", "account"))
        raise

    emails: list[dict] = []
    for msg in listing.get("messages", [])[:limit]:
        try:
            full = svc.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        except Exception:
            continue
        payload = full.get("payload", {}) or {}
        hdrs = _headers(payload)
        emails.append({
            "n": len(emails) + 1, "subject": hdrs.get("subject", ""),
            "from": hdrs.get("from", ""), "date": hdrs.get("date", ""),
            "body": _body_text(payload),
        })

    candidates: list[dict] = []
    for start in range(0, len(emails), BATCH):
        batch = emails[start:start + BATCH]
        by_n = {e["n"]: e for e in batch}
        for raw in await _extract_batch(batch):
            src = by_n.get(raw.get("source")) or {}
            item = _clean_item(raw, src.get("subject", ""))
            if item:
                candidates.append(item)
    return candidates, len(emails)


def _dedupe_key(item: dict) -> str:
    return f"{item.get('kind')}:{memory._norm(item.get('title', ''))}"


async def scan_for_items(user_id: str, limit: int = MAX_MESSAGES) -> dict:
    """Scan a user's connected Google accounts for actionable items. Read-only, no writes."""
    candidates: list[dict] = []
    needs_reconnect: list[str] = []
    scanned = 0
    for pub in db.list_google_accounts(user_id):
        acct = db.get_google_account_internal(pub["id"])
        if not acct:
            continue
        try:
            found, n = await _scan_account(acct, limit)
            candidates.extend(found)
            scanned += n
        except NeedsReconnect as exc:
            needs_reconnect.append(str(exc))
        except Exception:
            logger.exception("Gmail inbox scan failed for %s", pub.get("email"))

    # Dedupe candidates by normalised (kind + title) — the same booking often
    # arrives as several emails (confirmation, reminder, itinerary...).
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        key = _dedupe_key(c)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return {"candidates": unique, "needs_reconnect": needs_reconnect, "scanned": scanned}


async def commit(items: list[dict]) -> dict:
    """File the user's chosen items into the DB. Best-effort — one failure never
    blocks the rest. Returns {"created": N, "by_kind": {...}}."""
    users = db.list_users()
    default_user = users[0]["id"] if users else None
    created = 0
    by_kind: dict[str, int] = {}
    for item in items:
        kind = _str(item.get("kind")).lower()
        title = _str(item.get("title"))
        if kind not in _KIND_FIELDS or not title:
            continue
        try:
            if kind == "trip":
                db.create_trip({
                    "title": title,
                    "destination": item.get("destination"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "status": "booked",
                })
            elif kind == "appointment":
                appt = {
                    "title": title,
                    "provider": item.get("provider") or "",
                    "datetime": item.get("datetime") or "",
                    "user_id": item.get("user_id"),
                }
                if item.get("category"):
                    appt["category"] = item["category"]
                db.create_appointment(appt, default_user=default_user)
            elif kind == "document":
                # Populate BOTH expiry columns from the one date: expiry_date feeds
                # the renewal reminder, expiry feeds the Vault status badge.
                exp = item.get("expiry_date")
                db.create_document({
                    "name": title,
                    "category": "personal",
                    "expiry": exp,
                    "expiry_date": exp,
                    "notes": item.get("notes") or "",
                })
        except Exception:
            logger.exception("Failed to file inbox item %r", title)
            continue
        created += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"created": created, "by_kind": by_kind}
