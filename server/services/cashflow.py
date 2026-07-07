"""Cashflow forecast — "how much money is left this month".

Projects the household's month-end cash position honestly:
  projected = current spendable cash + expected income still to come
              − projected further spending

Spending/income rates are a trailing 30-day average (stable, and not thrown off
by a spiky start to the month), and TRANSFERS / SAVINGS / CRYPTO shuffles are
excluded (they're internal money movements, not real spending or income — this
matches the Insights "spending by category" and finance_summary logic). Bills
still unpaid this month are surfaced for context but NOT double-subtracted, since
the trailing spend average already reflects the household's recurring outgoings.

Everything is defensive: bad/missing data is skipped and build_forecast() never
raises.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from server import database as db

# Locale-independent month names (strftime('%B') depends on the active locale).
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_TRAILING_DAYS = 30


def _excluded() -> tuple[set, set]:
    """(spend_exclude, income_exclude) category sets — mirrors finance_summary."""
    try:
        from server.services import categorize as cz
        non_spend = set(cz.NON_SPEND_CATEGORIES)
    except Exception:
        non_spend = {"Income", "Transfers", "Savings", "Crypto"}
    return non_spend, (non_spend - {"Income"})


def build_forecast() -> dict:
    today = date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_left = days_in_month - today.day

    # Current spendable cash = balances of NON-credit accounts (credit = debt).
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

    spend_exclude, income_exclude = _excluded()
    try:
        txns = db.list_transactions_for_analysis(limit=2000)
    except Exception:
        txns = []

    month_key = f"{year:04d}-{month:02d}"
    trailing_cutoff = (today - timedelta(days=_TRAILING_DAYS)).isoformat()

    spent_so_far = 0.0          # real spend THIS month (for display)
    trailing_spend = 0.0        # real spend over the last 30 days
    trailing_income = 0.0       # real income over the last 30 days
    for t in txns:
        try:
            amt = t.get("amount") or 0
            if not amt:
                continue
            d = (t.get("date") or "")[:10]
            cat = t.get("category") or ""
            if amt < 0 and cat not in spend_exclude:
                if d[:7] == month_key:
                    spent_so_far += -amt
                if d >= trailing_cutoff:
                    trailing_spend += -amt
            elif amt > 0 and cat not in income_exclude:
                if d >= trailing_cutoff:
                    trailing_income += amt
        except (TypeError, ValueError):
            continue

    daily_spend = trailing_spend / _TRAILING_DAYS if _TRAILING_DAYS else 0.0
    daily_income = trailing_income / _TRAILING_DAYS if _TRAILING_DAYS else 0.0
    projected_further_spend = round(daily_spend * days_left, 2)
    expected_income_remaining = round(daily_income * days_left, 2)

    # Unpaid bills with a due-day in this month — shown for context only.
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

    projected_end = round(current_cash + expected_income_remaining - projected_further_spend, 2)

    return {
        "as_of": today.isoformat(),
        "days_left": days_left,
        "current_cash": round(current_cash, 2),
        "spent_so_far": round(spent_so_far, 2),
        "avg_daily_spend": round(daily_spend, 2),
        "projected_further_spend": projected_further_spend,
        "expected_income_remaining": expected_income_remaining,
        "bills_due_remaining": round(bills_due_remaining, 2),
        "projected_month_end_cash": projected_end,
        "month_label": f"{_MONTH_NAMES[month - 1]} {year}",
    }
