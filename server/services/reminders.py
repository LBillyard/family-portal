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
            # Each appointment carries its own reminder_days (UI: "Reminder Nd before",
            # schema default 2); honour it instead of the global lead.
            _rd = a.get("reminder_days")
            appt_lead = max(0, int(_rd)) if _rd is not None else lead  # 0 = remind on the day only
            if not (0 <= days_until <= appt_lead):  # today..appt_lead days ahead only
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

    # --- Renewals: subscriptions & maintenance from the renewal calendar. Bills,
    #     documents, vehicles and care are intentionally excluded here — each has its
    #     own reminder block (bills above, documents below, vehicles + care in their
    #     own blocks further down), so counting them here would double-remind the
    #     household. Reminds the whole household. ---
    if prefs.get("renewal_reminders"):
        cal = renewals_svc.build_renewal_calendar(days_ahead=lead)
        for item in cal.get("items", []):
            if item.get("type") in ("bill", "document", "vehicle", "care"):
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

    # --- Large transactions: alert the whole household to any recent spend over the threshold. ---
    if prefs.get("large_transaction_alerts"):
        threshold = int(prefs.get("large_transaction_threshold") or 200)
        for t in db.list_transactions(limit=100):
            amt = t.get("amount") or 0
            if amt >= 0 or abs(amt) < threshold:
                continue
            txn_dt = _parse_dt(t.get("txn_date") or t.get("date"))
            if not txn_dt or (today - txn_dt.date()).days > 3:   # only very recent, avoid alerting historical imports
                continue
            checked += 1
            key = f"largetxn:{t['id']}"
            if db.was_notified(key):
                continue
            desc = t.get("merchant_display") or t.get("display_name") or t.get("description") or "Transaction"
            acct = t.get("account_name") or t.get("account")
            at = f" — {acct}" if acct else ""
            body = f"💳 Large transaction: £{abs(amt):.2f} at {desc}{at}"
            if await _remind_household(household, body):
                sent += len(household)
                alerts += 1
                _push("Large transaction", body, badge=alerts)
                db.mark_notified(key)

    # --- Chores: nudge the person whose turn it is when a chore falls due. ---
    from server.services import chores as chores_svc
    for ch in chores_svc.due_chores(today):
        checked += 1
        key = f"chore:{ch['id']}:{ch.get('next_due')}"
        if db.was_notified(key):
            continue
        title = ch.get("title") or "Chore"
        body = f"🧹 Your turn: {title} (due {ch.get('next_due')})"
        assignee = db.get_user(ch.get("assignee_id")) if ch.get("assignee_id") else None
        phone = (assignee or {}).get("phone")
        ok = False
        if phone:
            ok = await _send_one(phone, body)
        else:
            ok = bool(await _remind_household(_household(), body))
        if ok:
            sent += 1
            alerts += 1
            _push("Chore due", body, badge=alerts)
            db.mark_notified(key)

    # --- Occasions: a 7-day heads-up so there's time to buy a gift/card. Gated only
    #     by the master switch (checked at the top), not a per-category pref. ---
    from server.services import occasions as occasions_svc
    for occ in occasions_svc.upcoming_occasions(within_days=7, today=today):
        checked += 1
        nd = occ.get("next_date")
        key = f"occasion:{occ['id']}:{(nd or '')[:4]}"   # once per year
        if db.was_notified(key):
            continue
        du = occ.get("days_until")
        when = "today! 🎉" if du == 0 else f"in {du} day{'s' if du != 1 else ''}"
        extra = f" (turns {occ['years']})" if occ.get("kind") == "birthday" and occ.get("years") else ""
        body = f"🎂 {occ['title']}{extra} {when}"
        if await _remind_household(_household(), body):
            sent += len(_household())
            alerts += 1
            _push("Upcoming occasion", body, badge=alerts)
            db.mark_notified(key)

    # --- Warranty expiries: gate under the household's expiry-radar toggle. ---
    if prefs.get("document_expiry_reminders"):
        for it in db.inventory_expiring_within(lead):
            checked += 1
            key = f"warranty:{it['id']}:{it.get('warranty_expiry')}"
            if db.was_notified(key):
                continue
            we = it.get("warranty_expiry")
            try:
                when = _fmt_date(date.fromisoformat(str(we)[:10]))
            except (TypeError, ValueError):
                when = "soon"
            body = f"📦 Warranty ending: {it['name']} on {when}"
            if await _remind_household(_household(), body):
                sent += len(_household())
                alerts += 1
                _push("Warranty ending", body, badge=alerts)
                db.mark_notified(key)

    # --- Care due (children & pets): vaccinations, check-ups, grooming, etc. Neutral
    #     wording covers both. Gated by the master switch only (checked at the top). ---
    for ci in db.care_due_within(lead):
        checked += 1
        key = f"care:{ci['id']}:{ci.get('due_date')}"
        if db.was_notified(key):
            continue
        try:
            when = _fmt_date(date.fromisoformat(str(ci.get('due_date'))[:10]))
        except (TypeError, ValueError):
            when = "soon"
        who = ci.get('dependent_name') or ''
        lead_txt = f"{who}: " if who else ""
        body = f"🐾 Care due — {lead_txt}{ci['title']} ({when})"
        if await _remind_household(_household(), body):
            sent += len(_household())
            alerts += 1
            _push("Care due", body, badge=alerts)
            db.mark_notified(key)

    # --- Budget alerts: warn the household once when a category hits 80% of its
    #     monthly limit and again when it goes over 100%. The month is baked into
    #     the de-dupe key so each level fires once per category per month and resets
    #     next month. Gated by the household's budget-alerts toggle. ---
    if prefs.get("budget_alerts"):
        month = today.strftime("%Y-%m")
        for b in db.list_budgets():
            limit = b.get("limit") or 0
            spent = b.get("spent") or 0
            if limit <= 0:
                continue
            pct = spent / limit
            level = "over" if pct >= 1.0 else ("warn" if pct >= 0.8 else None)
            if level is None:
                continue
            checked += 1
            key = f"budget:{b['category']}:{month}:{level}"  # 'warn' once + 'over' once, per month
            if db.was_notified(key):
                continue
            cat = b.get("category")
            if level == "over":
                body = f"💸 Over budget: {cat} — £{spent:.0f} of £{limit:.0f} this month"
            else:
                body = f"⚠️ Budget alert: {cat} at {round(pct*100)}% (£{spent:.0f} of £{limit:.0f})"
            if await _remind_household(_household(), body):
                sent += len(_household())
                alerts += 1
                _push("Budget alert", body, badge=alerts)
                db.mark_notified(key)

    # --- Vehicle renewals: MOT / tax / insurance / service falling due. These are
    #     renewals, so gate them under the same renewal_reminders toggle. One entry
    #     per due field per vehicle; the due date is in the key so it fires once per
    #     cycle and re-fires next cycle. Reminds the whole household. ---
    if prefs.get("renewal_reminders"):
        for v in db.vehicles_due_within(lead):
            checked += 1
            key = f"vehicle:{v['vehicle_id']}:{v['kind']}:{v.get('due_date')}"
            if db.was_notified(key):
                continue
            try:
                when = _fmt_date(date.fromisoformat(str(v.get('due_date'))[:10]))
            except (TypeError, ValueError):
                when = "soon"
            reg = f" ({v['reg']})" if v.get('reg') else ""
            body = f"🚗 {v['name']}{reg} — {v['kind']} due {when}"
            if await _remind_household(_household(), body):
                sent += len(_household())
                alerts += 1
                _push("Vehicle renewal", body, badge=alerts)
                db.mark_notified(key)

    return {"sent": sent, "checked": checked}
