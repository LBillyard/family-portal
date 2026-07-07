"""Weekly finance recap — a WhatsApp-friendly Sunday summary of the household's money.

Composed entirely from real ledger data:
  • this week's spend vs last week's (with direction),
  • the top spend category this week,
  • unpaid bills falling due in the next 7 days,
  • the current net-worth snapshot.

The (separately-owned) Sunday job imports `build_weekly_summary()`. This module is
defensive by design: every section is wrapped so a missing/erroring slice degrades
to a blank line rather than taking down the whole recap. It never raises.

"This week" always means the calendar week (Mon..Sun) *containing today* — the job
runs on a Sunday, so that's the week ending today, regardless of where the newest
transaction happens to fall.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from server import database as db
from server.services import networth

logger = logging.getLogger(__name__)


def _gbp(x: float) -> str:
    """Format a number as GBP with thousands separators and 2dp, e.g. £1,234.56."""
    try:
        return f"£{float(x):,.2f}"
    except (TypeError, ValueError):
        return "£0.00"


def _week_bounds(today: date) -> tuple[date, date, date, date]:
    """(this_mon, this_sun, prev_mon, prev_sun) for the ISO week containing `today`."""
    this_mon = today - timedelta(days=today.weekday())  # Monday of this week
    this_sun = this_mon + timedelta(days=6)
    prev_mon = this_mon - timedelta(days=7)
    prev_sun = this_mon - timedelta(days=1)
    return this_mon, this_sun, prev_mon, prev_sun


def _spend_in_range(txns: list[dict], start: date, end: date) -> float:
    """Total spend (abs of negative amounts) with a date in [start, end] inclusive."""
    s, e = start.isoformat(), end.isoformat()
    total = 0.0
    for t in txns:
        amount = t.get("amount")
        if amount is None or amount >= 0:  # skip income / zero
            continue
        d = (t.get("date") or "")[:10]
        if s <= d <= e:
            total += abs(float(amount))
    return total


def _top_category(txns: list[dict], start: date, end: date) -> tuple[str, float] | None:
    """(category, amount) with the highest spend in [start, end], or None if no spend."""
    s, e = start.isoformat(), end.isoformat()
    totals: dict[str, float] = {}
    for t in txns:
        amount = t.get("amount")
        if amount is None or amount >= 0:
            continue
        d = (t.get("date") or "")[:10]
        if s <= d <= e:
            cat = t.get("category") or "Uncategorised"
            totals[cat] = totals.get(cat, 0.0) + abs(float(amount))
    if not totals:
        return None
    name = max(totals, key=totals.get)
    return name, totals[name]


def _next_due_date(due_day: int, today: date) -> date:
    """Next calendar date a monthly bill with this due-day falls on: this month if the
    day hasn't passed yet, otherwise next month. Day is clamped to the month length."""
    if due_day >= today.day:
        year, month = today.year, today.month
    elif today.month == 12:
        year, month = today.year + 1, 1
    else:
        year, month = today.year, today.month + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(due_day, 1), last))


def _spend_section(txns: list[dict], today: date) -> str:
    this_mon, this_sun, prev_mon, prev_sun = _week_bounds(today)
    this_week = _spend_in_range(txns, this_mon, this_sun)
    last_week = _spend_in_range(txns, prev_mon, prev_sun)
    if this_week <= 0:
        return "💸 No spending recorded this week."
    if this_week > last_week:
        direction = f"▲ more vs {_gbp(last_week)} last week"
    elif this_week < last_week:
        direction = f"▼ less vs {_gbp(last_week)} last week"
    else:
        direction = f"same as {_gbp(last_week)} last week"
    return f"💸 Spent this week: {_gbp(this_week)} ({direction})"


def _top_section(txns: list[dict], today: date) -> str | None:
    this_mon, this_sun, _, _ = _week_bounds(today)
    top = _top_category(txns, this_mon, this_sun)
    if not top:
        return None
    name, amount = top
    return f"🏷️ Top: {name} {_gbp(amount)}"


def _bills_section(today: date) -> str:
    horizon = today + timedelta(days=7)
    due: list[tuple[str, float]] = []
    total = 0.0
    for bill in db.list_bills():
        if bill.get("paid"):
            continue
        try:
            dd = int(bill.get("due_day"))
        except (TypeError, ValueError):
            continue
        when = _next_due_date(dd, today)
        if today <= when <= horizon:
            amt = float(bill.get("amount") or 0)
            due.append((bill.get("name") or "Bill", amt))
            total += amt
    if not due:
        return "📅 No bills due in the next 7 days."
    parts = ", ".join(f"{name} {_gbp(amt)}" for name, amt in due)
    return f"📅 Bills next 7 days: {parts} ({_gbp(total)})"


def _networth_section() -> str:
    nw = networth.build_networth().get("net_worth", 0.0)
    return f"💰 Net worth: {_gbp(nw)}"


def build_weekly_summary() -> str:
    """Return the finished multi-line recap string. Never raises."""
    today = date.today()
    lines = ["📊 Your week in money", ""]

    try:
        txns = db.list_transactions_for_analysis(limit=1000)
    except Exception:
        logger.exception("weekly_finance: could not load transactions")
        txns = []

    try:
        lines.append(_spend_section(txns, today))
    except Exception:
        logger.exception("weekly_finance: spend section failed")

    try:
        top = _top_section(txns, today)
        if top:
            lines.append(top)
    except Exception:
        logger.exception("weekly_finance: top-category section failed")

    try:
        lines.append(_bills_section(today))
    except Exception:
        logger.exception("weekly_finance: bills section failed")

    try:
        lines.append(_networth_section())
    except Exception:
        logger.exception("weekly_finance: net-worth section failed")

    lines.append("")
    lines.append("Have a great week! — The Hub")
    return "\n".join(lines)
