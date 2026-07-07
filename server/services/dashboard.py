"""Aggregate dashboard and reminder data."""

from datetime import date, datetime, timedelta

from server import database as db


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s.replace("Z", "+00:00").split("+")[0])
    except ValueError:
        return None


def _suggestions_count() -> int:
    """Pending email-suggestion count — best-effort so a DB hiccup can never 500
    the whole Home dashboard (mirrors the try-guard the briefing uses)."""
    try:
        return db.count_pending_suggestions()
    except Exception:
        return 0


def _trip_ended(trip: dict) -> bool:
    """A trip is over when its end (or start, if end is unset) is in the past."""
    ref = trip.get("end") or trip.get("start")
    if not ref:
        return False
    try:
        return date.fromisoformat(str(ref)[:10]) < date.today()
    except (ValueError, TypeError):
        return False


def build_dashboard() -> dict:
    users = [db.user_public(u) for u in db.list_users()]
    events = db.list_events()
    bills = db.list_bills()
    appointments = db.list_appointments()
    tasks = db.list_tasks()
    documents = db.list_documents()
    trips = db.list_trips()

    now = datetime.now()
    week_end = now + timedelta(days=7)

    upcoming_events = []
    for e in events:
        dt = _parse_dt(e["start"])
        if dt and dt >= now - timedelta(days=1) and dt <= week_end:
            upcoming_events.append(e)
    upcoming_events = upcoming_events[:6]

    upcoming_bills = [b for b in bills if not b["paid"]][:4]
    upcoming_appointments = [
        a for a in appointments
        if a["status"] == "upcoming" and (_parse_dt(a["datetime"]) or now) >= now - timedelta(days=1)
    ][:4]

    active_trips = [t for t in trips if not _trip_ended(t)]
    next_holiday = next((t for t in active_trips if t["status"] == "booked" and t.get("days_until") is not None), None)
    if not next_holiday and active_trips:
        next_holiday = active_trips[0]

    reminders = _build_reminders(appointments, bills, documents)
    doc_alerts = [d for d in documents if d.get("status") == "renew_soon"]

    return {
        "users": users,
        "upcoming_events": upcoming_events,
        "upcoming_bills": upcoming_bills,
        "upcoming_appointments": upcoming_appointments,
        "next_holiday": next_holiday,
        "tasks": tasks,
        "reminders": reminders,
        "documents": doc_alerts[:3],
        "notifications_unread": len([r for r in reminders]),
        "suggestions_count": _suggestions_count(),
        "finance_summary": db.finance_summary(),
        "sync": {"google_last": db.get_setting("google_last_sync", "never"), "status": "ok"},
    }


def _build_reminders(appointments, bills, documents) -> list[dict]:
    reminders = []
    today = date.today()

    for a in appointments:
        if a["status"] != "upcoming":
            continue
        dt = _parse_dt(a["datetime"])
        if dt and dt.date() == today + timedelta(days=1):
            reminders.append({"id": a["id"], "text": f"{a['title']} tomorrow", "type": "appointment", "when": "Tomorrow"})

    for b in bills:
        if b["paid"]:
            continue
        # Next real occurrence: this month if the day hasn't passed, else next month
        # (day clamped to 28 for short months — mirrors renewals).
        day = min(b["due_day"], 28)
        due = today.replace(day=day)
        if due < today:
            if today.month == 12:
                due = date(today.year + 1, 1, day)
            else:
                due = date(today.year, today.month + 1, day)
        if (due - today).days <= 14:
            reminders.append({"id": b["id"], "text": f"{b['name']} due soon", "type": "bill", "when": f"{due.day} {due.strftime('%b')}"})

    for d in documents:
        if d.get("status") == "renew_soon":
            reminders.append({"id": d["id"], "text": f"{d['name']} — renew soon", "type": "document", "when": d["expiry"][:7]})

    return reminders[:5]
