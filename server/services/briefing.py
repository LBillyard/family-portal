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

    next_trip = next((t for t in trips if t.get("days_until") is not None), None)
    if not next_trip:
        next_trip = next((t for t in trips if t.get("start")), None)

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


def whatsapp_digest_line(user: dict | None = None) -> str:
    """One-line, newline-free digest for a WhatsApp template variable ({{1}}).

    Meta rejects template parameters containing newlines/tabs, so this uses
    ' · ' between sections and ', ' between items. Kept under ~1000 chars."""
    b = build_briefing(user)
    today = date.fromisoformat(b["date"])
    date_str = f"{today.strftime('%a')} {today.day} {today.strftime('%b')}"

    parts: list[str] = []
    evs = b["today_events"]
    if evs:
        items = ", ".join(f"{_hhmm(e['start'])}{e['title']}" for e in evs[:5])
        parts.append(f"📅 {len(evs)} event(s): {items}")
    appts = b["today_appointments"]
    if appts:
        items = ", ".join(f"{_hhmm(a['datetime'])}{a['title']}" for a in appts[:4])
        parts.append(f"🩺 {items}")
    tasks = b["due_tasks"]
    if tasks:
        parts.append("✅ due: " + ", ".join(t["title"] for t in tasks[:4]))
    rn = b["urgent_renewals"]
    if rn:
        parts.append("🔔 " + ", ".join(f"{r['name']} ({r['days_until']}d)" for r in rn[:3]))
    trip = b["next_trip"]
    if trip and trip.get("days_until") is not None:
        parts.append(f"✈️ {trip['title']} in {trip['days_until']}d")

    if parts:
        body = f"{date_str} — " + " · ".join(parts) + ". Reply to add or change anything."
    else:
        body = f"{date_str}: a clear day, nothing scheduled. Reply to add anything."
    return re.sub(r"\s+", " ", body).strip()[:1000]
