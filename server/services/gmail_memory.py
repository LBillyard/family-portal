"""Scan Gmail for durable facts to add to the family memory.

Reuses the read-only Gmail connection (same scope as receipts). Pulls fact-rich
emails (insurance, memberships, renewals, bookings, confirmations, registrations),
runs their text through the AI to extract lasting facts worth remembering
(car make/reg/insurer, subscriptions, home/appliance details, addresses...),
dedupes against what's already known, and returns candidates for the user to
review and pick. Nothing is written until the user imports their selection.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re

import httpx

from server import database as db
from server.services import google_calendar, memory

logger = logging.getLogger(__name__)

# Fact-rich inbox slice — avoids scanning marketing/newsletter noise.
QUERY = (
    'newer_than:1y ('
    'insurance OR policy OR renewal OR renews OR membership OR booking OR confirmation '
    'OR warranty OR "MOT" OR service OR subscription OR registration OR reservation '
    'OR "policy number" OR account'
    ')'
)
MAX_MESSAGES = 40
BATCH = 6  # emails per extraction call
BODY_CHARS = 1400


class NeedsReconnect(Exception):
    """The account lacks the Gmail scope (connected before it was added)."""


def _gmail(token_json: str):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=google_calendar._credentials(token_json), cache_discovery=False)


def _headers(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in (payload.get("headers") or [])}


def _body_text(payload: dict) -> str:
    """Best-effort plain-text body from a Gmail payload (falls back to stripped HTML)."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part):
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
            except Exception:
                decoded = ""
            if mime == "text/plain":
                plain.append(decoded)
            elif mime == "text/html":
                html.append(decoded)
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    text = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(html))
    return re.sub(r"\s+", " ", text).strip()


_SYS = """You extract DURABLE, PERSONAL/HOUSEHOLD facts worth remembering about a FAMILY from their emails. This is a family assistant's memory — it cares about home and personal life, NOT work or business.

Return ONLY JSON, no markdown: {"facts":[{"text": str, "category": "people|places|preferences|possessions", "subject": "family|luke|laura", "source": int}]}

KEEP (only genuinely useful personal/household facts):
- Vehicles: make/model/registration, insurer, policy renewal month.
- Home: the home address, appliance/furniture warranties, home energy/broadband/mobile provider, home services (cleaner, gardener) and their schedule.
- Personal subscriptions & memberships the family actually uses (streaming, VPN, gym, clubs).
- Family/people facts: relatives, kids, pets, key personal dates.
- Personal insurance/policies (home, car, travel, pet, life).

IGNORE (do NOT extract — return nothing for these):
- Anything about their WORK or BUSINESS: company accounts, business energy/premises, invoices, clients, staff, terms of business.
- Developer/technical/cloud/IT: AWS, hosting, servers, domains, SEO, Search Console, API/dev tools, dashboards.
- Marketing, sales outreach, newsletters, "you might like", offers, or speculative "considering" language.
- Verification/2FA codes, receipts for single purchases, delivery updates, password resets.
- Anything trivial, one-off, or time-limited.

RULES:
- If an email is work/business/technical/marketing, skip it entirely — quality over quantity, a near-empty result is fine.
- Each fact a short standalone sentence, e.g. "The car is a blue BMW 3 Series, reg AB12 CDE", "Home broadband is Starlink", "They have a weekly cleaner".
- "subject" = whose it is: "luke", "laura" or "family". "source" = the [n] number of the email.
- DO NOT repeat anything in ALREADY KNOWN, even reworded. Never invent or guess details."""


def _model() -> str:
    return os.environ.get("OPENROUTER_DEFAULT_MODEL", "").strip() or "openai/gpt-4o-mini"


async def _extract_batch(emails: list[dict], known: list[str]) -> list[dict]:
    blocks = [f"[{e['n']}] From: {e['from']} | Subject: {e['subject']}\n{e['body'][:BODY_CHARS]}" for e in emails]
    known_block = "\n".join(f"- {k}" for k in known[:150]) or "(nothing yet)"
    user = f"ALREADY KNOWN (do not repeat):\n{known_block}\n\nEMAILS:\n" + "\n\n".join(blocks)
    payload = {
        "model": _model(),
        "messages": [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=memory._headers(), json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content).get("facts", [])
    except ValueError:
        return []


async def _scan_account(acct: dict, known: list[str], known_norm: set[str], limit: int) -> tuple[list[dict], int]:
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
        for f in await _extract_batch(batch, known):
            text = (f.get("text") or "").strip()
            if not text or memory._norm(text) in known_norm:
                continue
            src = by_n.get(f.get("source")) or {}
            candidates.append({
                "text": text,
                "category": f.get("category") if f.get("category") in memory.CATEGORIES else "preferences",
                "subject": memory._subject_from_name(f.get("subject")),
                "source_from": src.get("from", ""),
                "source_subject": src.get("subject", ""),
            })
    return candidates, len(emails)


async def scan_for_facts(user_id: str, limit: int = MAX_MESSAGES) -> dict:
    """Scan a user's connected Google accounts for durable facts. Read-only, no writes."""
    known = [f["text"] for f in db.list_memory_facts(include_embedding=False)]
    known_norm = {memory._norm(k) for k in known}
    candidates: list[dict] = []
    needs_reconnect: list[str] = []
    scanned = 0
    for pub in db.list_google_accounts(user_id):
        acct = db.get_google_account_internal(pub["id"])
        if not acct:
            continue
        try:
            found, n = await _scan_account(acct, known, known_norm, limit)
            candidates.extend(found)
            scanned += n
        except NeedsReconnect as exc:
            needs_reconnect.append(str(exc))
        except Exception:
            logger.exception("Gmail memory scan failed for %s", pub.get("email"))

    # Dedupe candidates against each other (same fact can appear in several emails).
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        key = memory._norm(c["text"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return {"candidates": unique, "needs_reconnect": needs_reconnect, "scanned": scanned}


async def commit(facts: list[dict]) -> list[dict]:
    """Store the user's chosen facts in memory (tagged as sourced from email)."""
    stored: list[dict] = []
    for f in facts:
        text = (f.get("text") or "").strip()
        if not text:
            continue
        saved = await memory.remember(
            text, category=f.get("category"),
            subject=memory._subject_from_name(f.get("subject")), source="email",
        )
        if saved:
            stored.append(saved)
    return stored
