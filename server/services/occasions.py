"""Annual occasions — birthdays, anniversaries and other yearly dates.

An occasion stores its ORIGINAL full date (e.g. a birth or wedding date) and
recurs every year on that month/day. This module computes the next upcoming
occurrence and the countdown to it, so callers (the /occasions API and the
reminders job) can surface a "coming up" view without storing per-year rows.
"""

from __future__ import annotations

from datetime import date

from server import database as db


def _occurrence_in_year(year: int, month: int, day: int) -> date:
    """The occasion's date in `year`, with Feb-29 gracefully clamped to Feb-28
    in non-leap years so a leap-day occasion still resolves every year."""
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        raise


def next_occurrence(date_str: str, today: date | None = None) -> tuple[date, int] | None:
    """Return (occurrence_date, years) for the next upcoming anniversary of
    `date_str` ('YYYY-MM-DD'), or None if it can't be parsed.

    `years` is how many years old the occasion turns on that upcoming date, i.e.
    occurrence_date.year - original_year (a 2023 birth → turning 3 in 2026).
    This year's occurrence is used unless it has already passed, in which case
    next year's is returned.
    """
    if today is None:
        today = date.today()
    try:
        original = date.fromisoformat(str(date_str)[:10])
    except (ValueError, TypeError):
        return None
    occ = _occurrence_in_year(today.year, original.month, original.day)
    if occ < today:
        occ = _occurrence_in_year(today.year + 1, original.month, original.day)
    return occ, occ.year - original.year


def upcoming_occasions(within_days: int | None = None, today: date | None = None) -> list[dict]:
    """Every occasion enriched with its next occurrence and countdown, sorted
    soonest-first. When `within_days` is given, only occasions falling due in
    that many days (inclusive) are kept."""
    if today is None:
        today = date.today()
    out: list[dict] = []
    for occ in db.list_occasions():
        nxt = next_occurrence(occ.get("date"), today)
        if nxt is None:
            continue
        occ_date, years = nxt
        out.append({
            "id": occ["id"],
            "title": occ["title"],
            "kind": occ.get("kind"),
            "person": occ.get("person"),
            "notes": occ.get("notes"),
            "date": occ.get("date"),
            "next_date": occ_date.isoformat(),
            "days_until": (occ_date - today).days,
            "years": years,
        })
    out.sort(key=lambda x: x["days_until"])
    if within_days is not None:
        out = [x for x in out if x["days_until"] <= within_days]
    return out
