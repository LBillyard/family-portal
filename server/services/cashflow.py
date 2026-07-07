"""Cashflow forecast — "how much money is left this month".

Projects the household's month-end cash position from current spendable cash,
spending so far (extrapolated over the remaining days), and unpaid bills still
due before the month is out. Everything is defensive: bad/missing data is
skipped, and build_forecast() must never raise.
"""

from __future__ import annotations

import calendar
from datetime import date

from server import database as db

# Locale-independent month names (strftime('%B') depends on the active locale).
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def build_forecast() -> dict:
    today = date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_left = days_in_month - today.day

    # Current spendable cash = sum of balances of NON-credit accounts.
    # Credit accounts are debt, so they're ignored here.
    try:
        accounts = db.list_accounts()
    except Exception:
        accounts = []
    current_cash = 0.0
    for a in accounts:
        try:
            if (a.get("type") or "") != "credit":
                current_cash += float(a.get("balance") or 0)
        except (TypeError, ValueError):
            continue

    # Spend so far this month + average daily spend (this month to date).
    try:
        txns = db.list_transactions_for_analysis(limit=1000)
    except Exception:
        txns = []
    mk = f"{year:04d}-{month:02d}"
    spent_so_far = 0.0
    for t in txns:
        try:
            amt = t.get("amount") or 0
            if (t.get("date") or "")[:7] == mk and amt < 0:
                spent_so_far += abs(amt)
        except (TypeError, ValueError):
            continue

    avg_daily = round(spent_so_far / today.day, 2) if today.day else 0.0
    projected_further_spend = round(avg_daily * days_left, 2)

    # Money still going out this month = every UNPAID bill with a due-day in this
    # month, whether it's already overdue (due-day before today, still unpaid) or
    # yet to come. Excluding overdue-unpaid bills would make the forecast too rosy.
    bills_due_remaining = 0.0
    try:
        bills = db.list_bills()
    except Exception:
        bills = []
    for b in bills:
        try:
            if b.get("paid"):
                continue
            dd = b.get("due_day")
            if isinstance(dd, (int, float)) and 1 <= int(dd) <= days_in_month:
                amt = b.get("amount")
                if isinstance(amt, (int, float)):
                    bills_due_remaining += amt
        except (TypeError, ValueError):
            continue

    projected_end = round(current_cash - bills_due_remaining - projected_further_spend, 2)

    month_label = f"{_MONTH_NAMES[month - 1]} {year}"

    return {
        "as_of": today.isoformat(),
        "days_left": days_left,
        "current_cash": round(current_cash, 2),
        "spent_so_far": round(spent_so_far, 2),
        "avg_daily_spend": avg_daily,
        "projected_further_spend": projected_further_spend,
        "bills_due_remaining": round(bills_due_remaining, 2),
        "projected_month_end_cash": projected_end,
        "month_label": month_label,
    }
