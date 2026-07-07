"""Cashflow forecast — a conservative "money left this month" estimate.

Raw multi-account bank feeds are noisy for this: money moved between your own
accounts often isn't labelled "Transfers", and salary/mortgage-sized items are
lumpy — so a naive spend/income rate is wildly skewed. To stay honest and stable
we:
  * exclude Transfers / Savings / Crypto categories (internal shuffles), and
  * exclude any single transaction >= £1,000 from the *spending rate* (those are
    transfers or big one-offs, not the everyday drip of living costs), and
  * base the rate on a trailing 30-day window (not a spiky start-of-month), and
  * do NOT try to project lumpy income — the figure is framed as the balance
    "before any income lands", i.e. a conservative floor.

projected = current spendable cash − (everyday daily spend × days left).
Unpaid bills this month are surfaced for context but not double-subtracted (the
everyday spend rate already includes recurring bills). build_forecast() never
raises.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from server import database as db

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_TRAILING_DAYS = 30
_BIG_TXN = 1000.0  # single items >= this are transfers/one-offs, not everyday spend


def _spend_exclude() -> set:
    try:
        from server.services import categorize as cz
        return set(cz.NON_SPEND_CATEGORIES)
    except Exception:
        return {"Income", "Transfers", "Savings", "Crypto"}


def build_forecast() -> dict:
    today = date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    days_left = days_in_month - today.day

    # Current spendable cash = balances of 'current' accounts only, matching the
    # summary card's "Current accounts" stat (savings/credit are excluded here).
    try:
        accounts = db.list_accounts()
    except Exception:
        accounts = []
    current_cash = 0.0
    for a in accounts:
        try:
            if (a.get("type") or "") == "current":
                current_cash += float(a.get("balance") or 0)
        except (TypeError, ValueError):
            continue

    exclude = _spend_exclude()
    try:
        txns = db.list_transactions_for_analysis(limit=2000)
    except Exception:
        txns = []

    month_key = f"{year:04d}-{month:02d}"
    trailing_cutoff = (today - timedelta(days=_TRAILING_DAYS)).isoformat()

    spent_so_far = 0.0     # everyday spend THIS month (for display)
    trailing_spend = 0.0   # everyday spend over the last 30 days (drives the rate)
    for t in txns:
        try:
            amt = t.get("amount") or 0
            if amt >= 0:
                continue
            cat = t.get("category") or ""
            if cat in exclude:
                continue
            spend = -amt
            if spend >= _BIG_TXN:  # transfer / big one-off — not the everyday rate
                continue
            d = (t.get("date") or "")[:10]
            if d[:7] == month_key:
                spent_so_far += spend
            if d >= trailing_cutoff:
                trailing_spend += spend
        except (TypeError, ValueError):
            continue

    daily_spend = trailing_spend / _TRAILING_DAYS if _TRAILING_DAYS else 0.0
    projected_further_spend = round(daily_spend * days_left, 2)

    # Unpaid bills with a due-day this month — context only (not double-subtracted).
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

    projected_end = round(current_cash - projected_further_spend, 2)

    # has_data drives the frontend empty state: True once the household has any
    # account or any transaction to reason about.
    has_data = bool(accounts) or bool(txns)

    return {
        "as_of": today.isoformat(),
        "days_left": days_left,
        "current_cash": round(current_cash, 2),
        "spent_so_far": round(spent_so_far, 2),
        "avg_daily_spend": round(daily_spend, 2),
        "projected_further_spend": projected_further_spend,
        "bills_due_remaining": round(bills_due_remaining, 2),
        "projected_month_end_cash": projected_end,
        "month_label": f"{_MONTH_NAMES[month - 1]} {year}",
        "has_data": has_data,
    }
