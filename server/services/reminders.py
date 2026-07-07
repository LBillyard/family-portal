"""Unified household reminders — appointments, bills, renewals, document expiries.

`run_reminders()` is called by the reminders job (see server/jobs/reminders.py,
run by a systemd timer the ops agent owns). It reads the household notification
preferences and, for each enabled category, sends WhatsApp reminders for anything
falling due within `reminder_lead_days`.

Every reminder is de-duplicated through db.was_notified()/db.mark_notified() with a
stable per-item key, so a daily run only ever pings once per event (appointments),
once per due cycle (bills/renewals), or once per document. Sending is best-effort:
one failure never blocks the rest, and an item is only marked notified once at
least one message for it went out (so a WhatsApp outage retries next run).

Reminders go out via whatsapp.send_text (a free-form message that delivers when the
recipient's 24h WhatsApp window is open), not the business-initiated digest template.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from server import database as db
from server.services import renewals as renewals_svc
from server.services import whatsapp

logger = logging.getLogger(__name__)

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").split("+")[0])
    except (ValueError, TypeError):
        return None


def _fmt_date(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month]}"


def _fmt_when(dt: datetime, has_time: bool) -> str:
    base = _fmt_date(dt.date())
    return f"{base} at {dt.strftime('%H:%M')}" if has_time else base


def _next_due(day: int, today: date) -> date:
    """Next occurrence of a monthly due-day (clamped to 28 for short months, wraps month)."""
    day = min(max(int(day), 1), 28)
    if day >= today.day:
        return today.replace(day=day)
    month = today.month % 12 + 1
    year = today.year + (1 if today.month == 12 else 0)
    return date(year, month, day)


def _household() -> list[tuple[str, str]]:
    """(name, phone) for every household member with a phone number."""
    out: list[tuple[str, str]] = []
    for u in db.list_users():
        full = db.get_user(u["id"]) or u
        phone = (full.get("phone") or "").strip()
        if phone:
            out.append((full.get("name") or "", phone))
    return out


async def _send_one(phone: str, body: str) -> bool:
    try:
        await whatsapp.send_text(phone, body)
        return True
    except Exception:
        logger.exception("Reminder send to %s failed", phone)
        return False


def _push(title: str, body: str, badge: int | None = None) -> None:
    """Best-effort web-push mirror of a reminder. A bonus channel that reaches a
    subscribed device even outside the WhatsApp 24h window; never blocks the run
    and never affects reminder de-duplication. Imported lazily so push (and its
    optional pywebpush dependency) is never a hard requirement here.
    `badge` sets the home-screen app-icon count on the recipient's device."""
    try:
        from server.services import push

        push.notify(title, body, badge_count=badge)
    except Exception:
        logger.debug("Push notify failed (non-fatal)", exc_info=True)


async def _remind_household(recipients: list[tuple[str, str]], body: str) -> int:
    """Send `body` to every household recipient. Returns messages successfully sent."""
    sent = 0
    for _name, phone in recipients:
        if await _send_one(phone, body):
            sent += 1
    return sent


async def run_reminders() -> dict:
    """Send all due reminders, honouring the household notification preferences.

    Returns {"sent": int, "checked": int} on a normal run, or
    {"sent": 0, "skipped": "disabled"} when the master switch is off.
    """
    prefs = db.get_notification_prefs()
    if not prefs.get("master_enabled"):
        return {"sent": 0, "skipped": "disabled"}

    lead = int(prefs.get("reminder_lead_days") or 2)
    today = date.today()
    household = _household()
    sent = 0
    checked = 0
    alerts = 0  # distinct alert items pushed this run → home-screen icon badge count

    # --- Appointments: remind the appointment's OWNER (worded to them as "you"). ---
    if prefs.get("appointment_reminders"):
        for a in db.list_appointments():
            if a.get("status") != "upcoming":
                continue
            dt = _parse_dt(a.get("datetime"))
            if not dt:
                continue
            days_until = (dt.date() - today).days
            if not (0 <= days_until <= lead):  # today..lead days ahead only
                continue
            checked += 1
            key = f"appt:{a['id']}"
            if db.was_notified(key):
                continue
            owner = db.get_user(a.get("user_id")) or {}
            phone = (owner.get("phone") or "").strip()
            if not phone:
                continue
            when = _fmt_when(dt, has_time="T" in (a.get("datetime") or ""))
            whose = "you"  # the recipient IS the owner, so address them directly
            provider = a.get("provider") or ""
            at = f" at {provider}" if provider else ""
            body = f"⏰ Reminder: {a['title']}{at} on {when} ({whose})"
            if await _send_one(phone, body):
                sent += 1
                alerts += 1
                _push(a["title"], body, badge=alerts)  # bonus channel — after the WhatsApp send, same item
                db.mark_notified(key)

    # --- Bills: unpaid, next due-day within lead. Reminds the whole household. ---
    if prefs.get("bill_reminders"):
        for bill in db.list_bills():
            if bill.get("paid") or not bill.get("due_day"):
                continue
            due = _next_due(bill["due_day"], today)
            days_until = (due - today).days
            if not (0 <= days_until <= lead):
                continue
            checked += 1
            key = f"bill:{bill['id']}:{due.isoformat()}"
            if db.was_notified(key):
                continue
            amount = bill.get("amount")
            amt = f" (£{amount:.2f})" if isinstance(amount, (int, float)) else ""
            body = f"💷 Reminder: {bill['name']}{amt} due {_fmt_date(due)}"
            if await _remind_household(household, body):
                sent += len(household)
                alerts += 1
                _push(bill["name"], body, badge=alerts)
                db.mark_notified(key)

    # --- Renewals: subscriptions & maintenance from the renewal calendar. Bills and
    #     documents are intentionally excluded here — they have their own toggles above
    #     (bill_reminders) and below (document_expiry_reminders), so counting them again
    #     would double-remind the household. Reminds the whole household. ---
    if prefs.get("renewal_reminders"):
        cal = renewals_svc.build_renewal_calendar(days_ahead=lead)
        for item in cal.get("items", []):
            if item.get("type") in ("bill", "document"):
                continue
            days_until = item.get("days_until")
            if days_until is None or not (0 <= days_until <= lead):
                continue
            checked += 1
            # Stable per renewal per due-cycle: the due month means it fires once now
            # and again next cycle, not every day until then.
            cycle = (item.get("date") or "")[:7] or str(days_until)
            key = f"renewal:{item.get('title')}:{cycle}"
            if db.was_notified(key):
                continue
            when = _fmt_date(date.fromisoformat(item["date"][:10])) if item.get("date") else f"in {days_until}d"
            body = f"🔔 Reminder: {item.get('title')} renews {when}"
            if await _remind_household(household, body):
                sent += len(household)
                alerts += 1
                _push(item.get("title") or "Renewal", body, badge=alerts)
                db.mark_notified(key)

    # --- Document expiries: remind the whole household. ---
    if prefs.get("document_expiry_reminders"):
        for doc in db.documents_expiring_within(lead):
            checked += 1
            key = f"docexp:{doc['id']}"
            if db.was_notified(key):
                continue
            expiry = _parse_dt(doc.get("expiry_date") or doc.get("expiry"))
            when = _fmt_date(expiry.date()) if expiry else "soon"
            body = f"📄 Reminder: {doc.get('name')} expires {when}"
            if await _remind_household(household, body):
                sent += len(household)
                alerts += 1
                _push(doc.get("name") or "Document", body, badge=alerts)
                db.mark_notified(key)

    return {"sent": sent, "checked": checked}
