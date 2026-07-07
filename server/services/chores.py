"""Rotating household chores — whose turn it is, and when it's next due.

A chore has a cadence (weekly/fortnightly/monthly), an optional assignee, and a
`rotate` flag. Completing a chore stamps it done today, schedules the next due date
from the completion date, and — when rotating — hands it to the OTHER household
member so the two people alternate. `due_chores()` is what the reminders job polls to
nudge whoever's turn it is once a chore falls due.

All state lives in the database; these are pure helpers over db.* (verified by the
data agent). Month arithmetic clamps the day to ≤28 so a monthly chore never lands on
a non-existent date (e.g. the 31st in February).
"""

from __future__ import annotations

from datetime import date, timedelta

from server import database as db


def _other_member(user_id: str | None) -> str | None:
    """The OTHER household member's id, for handing a rotating chore over.

    If `user_id` is None or not a known member, returns the first member (so an
    unassigned chore still lands on someone). With a single-member household, returns
    that one member.
    """
    members = db.list_users()
    ids = [m["id"] for m in members]
    if not ids:
        return None
    if user_id not in ids:
        return ids[0]
    others = [mid for mid in ids if mid != user_id]
    return others[0] if others else user_id


def _advance_due(cadence: str, from_day: date) -> date:
    """Next due date for a cadence, measured from `from_day`.

    weekly=+7d, fortnightly=+14d, monthly=+1 calendar month (day clamped to ≤28 so it
    always exists). Unknown cadences default to weekly.
    """
    c = (cadence or "").lower()
    if c == "fortnightly":
        return from_day + timedelta(days=14)
    if c == "monthly":
        month = from_day.month % 12 + 1
        year = from_day.year + (1 if from_day.month == 12 else 0)
        day = min(from_day.day, 28)
        return date(year, month, day)
    # weekly / unknown
    return from_day + timedelta(days=7)


def complete_chore(chore_id: str) -> dict | None:
    """Mark a chore done today, reschedule it, and rotate it to the other member.

    Returns the updated chore, or None if the chore doesn't exist.
    """
    chore = db.get_chore(chore_id)
    if chore is None:
        return None

    today = date.today()
    last_done = today.isoformat()
    next_due = _advance_due(chore.get("cadence"), today).isoformat()
    if chore.get("rotate"):
        new_assignee = _other_member(chore.get("assignee_id"))
    else:
        new_assignee = chore.get("assignee_id")

    return db.update_chore(
        chore_id,
        {
            "last_done": last_done,
            "next_due": next_due,
            "assignee_id": new_assignee,
        },
    )


def due_chores(today: date | None = None) -> list[dict]:
    """Chores that are due or overdue: next_due is set and <= today."""
    if today is None:
        today = date.today()
    today_iso = today.isoformat()
    out: list[dict] = []
    for ch in db.list_chores():
        next_due = ch.get("next_due")
        if next_due and next_due <= today_iso:
            out.append(ch)
    return out
