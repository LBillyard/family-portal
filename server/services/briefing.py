"""Morning briefing — daily household summary."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from server import database as db
from server.services import renewals as renewals_svc


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def _trip_ended(trip: dict) -> bool:
    """A trip is over when its end (or start, if end is unset) is in the past."""
    ref = trip.get("end") or trip.get("start")
    if not ref:
        return False
    try:
        return date.fromisoformat(str(ref)[:10]) < date.today()
    except (ValueError, TypeError):
        return False


def build_briefing(user: dict | None = None) -> dict:
    today = date.today()
    now = datetime.now()
    events = db.list_events()
    tasks = [t for t in db.list_tasks() if not t.get("done")]
    appointments = db.list_appointments()
    trips = db.list_trips()
    activities = db.list_activity(limit=8)

    today_events = []
    for e in events:
        dt = _parse_dt(e["start"])
        if dt and dt.date() == today:
            today_events.append(e)

    today_appts = []
    for a in appointments:
        dt = _parse_dt(a["datetime"])
        if dt and dt.date() == today and a["status"] == "upcoming":
            today_appts.append(a)

    due_tasks = [t for t in tasks if t.get("due") and t["due"][:10] <= (today + timedelta(days=3)).isoformat()][:5]
    renewals = renewals_svc.build_renewal_calendar(days_ahead=14)
    urgent_renewals = [r for r in renewals["items"] if r["days_until"] <= 7][:4]

    active_trips = [t for t in trips if not _trip_ended(t)]
    next_trip = next((t for t in active_trips if t.get("days_until") is not None), None)
    if not next_trip:
        next_trip = next((t for t in active_trips if t.get("start")), None)

    greeting_hour = now.hour
    if greeting_hour < 12:
        greeting = "Good morning"
    elif greeting_hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    name = user["name"] if user else "there"
    lines = [f"{greeting}, {name}."]
    if today_events:
        lines.append(f"You have {len(today_events)} event(s) today.")
    if today_appts:
        lines.append(f"{len(today_appts)} appointment(s) scheduled.")
    if due_tasks:
        lines.append(f"{len(due_tasks)} task(s) due soon.")
    if urgent_renewals:
        lines.append(f"{len(urgent_renewals)} renewal(s) in the next week.")
    if next_trip and next_trip.get("days_until") is not None:
        lines.append(f"{next_trip['title']} in {next_trip['days_until']} days.")

    return {
        "greeting": greeting,
        "user_name": name,
        "date": today.isoformat(),
        "summary_text": " ".join(lines),
        "today_events": today_events,
        "today_appointments": today_appts,
        "due_tasks": due_tasks,
        "urgent_renewals": urgent_renewals,
        "next_trip": next_trip,
        "open_tasks_count": len(tasks),
        "recent_activity": activities,
        "finance": db.finance_summary(),
    }


def _hhmm(s: str) -> str:
    dt = _parse_dt(s)
    if dt and "T" in (s or ""):
        return dt.strftime("%H:%M") + " "
    return ""


def _ordinal(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _next_due(day: int, today: date) -> date:
    """Next occurrence of a monthly due-day (clamped to 28 for short months)."""
    day = min(max(int(day), 1), 28)
    if day >= today.day:
        return today.replace(day=day)
    month = today.month % 12 + 1
    year = today.year + (1 if today.month == 12 else 0)
    return date(year, month, day)


def whatsapp_digest_line(user: dict | None = None, weather: str | None = None) -> str:
    """One-line, newline-free digest for a WhatsApp template variable ({{1}}).

    Meta rejects template parameters containing newlines/tabs, so this uses
    ' · ' between sections and ', ' between items. Kept under ~1000 chars.

    `weather` (if provided) is appended as a leading section — pass the result of
    server.services.weather.today_line(), fetched by the async caller."""
    b = build_briefing(user)
    today = date.fromisoformat(b["date"])
    date_str = f"{today.strftime('%A')} {today.day} {today.strftime('%b')}"

    # Diary = today's events + appointments, ordered by time.
    diary = [(_hhmm(e["start"]), e["title"]) for e in b["today_events"]]
    diary += [(_hhmm(a["datetime"]), a["title"]) for a in b["today_appointments"]]
    diary.sort(key=lambda x: x[0] or "zz")
    # Drop duplicates — the same meeting often syncs from more than one calendar.
    seen: set = set()
    deduped = []
    for tm, ti in diary:
        key = (tm.strip(), (ti or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((tm, ti))
    diary = deduped

    # Outstanding tasks: open tasks, prioritising anything due today or overdue.
    open_tasks = [t for t in db.list_tasks() if not t.get("done")]
    due_now = [t for t in open_tasks if t.get("due") and t["due"][:10] <= today.isoformat()]
    task_list = due_now or open_tasks

    if diary:
        diary_part = "📅 " + ", ".join(f"{tm}{ti}".strip() for tm, ti in diary[:6])
    else:
        diary_part = "📅 Nothing in the diary"
    if task_list:
        task_part = "✅ " + ", ".join(t["title"] for t in task_list[:6])
    else:
        task_part = "✅ No outstanding tasks"

    sections = [weather] if weather else []
    sections += [diary_part, task_part]

    # Bills due within the next week (unpaid).
    bills_due = []
    for bill in db.list_bills():
        if bill.get("paid") or not bill.get("due_day"):
            continue
        nd = _next_due(bill["due_day"], today)
        if 0 <= (nd - today).days <= 7:
            bills_due.append((nd, bill["name"]))
    bills_due.sort(key=lambda x: x[0])
    if bills_due:
        sections.append("💷 Due: " + ", ".join(f"{n} ({d.day}{_ordinal(d.day)})" for d, n in bills_due[:4]))

    # Subscriptions/renewals coming up in the next week.
    if b["urgent_renewals"]:
        sections.append("🔔 Renewing: " + ", ".join(
            f"{r['title']} ({r['days_until']}d)" for r in b["urgent_renewals"][:3]))

    body = f"{date_str} — " + " · ".join(sections)
    return re.sub(r"\s+", " ", body).strip()[:1000]
