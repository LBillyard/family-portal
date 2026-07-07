"""Spending insights derived from transaction history.

Everything here is computed in Python from the raw ledger so the frontend gets a
ready-to-render snapshot: this month vs last month, the biggest single expense,
top spend categories, and the household subscription load. The "current" month is
taken from the most recent transaction present in the data (NOT today's clock) —
bank feeds and CSV imports often lag, so anchoring to the data keeps the headline
figures meaningful even when the calendar has ticked over.
"""

from __future__ import annotations

from server import database as db

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _txn_date(t: dict) -> str:
    """ISO date string for a transaction, tolerating either output key."""
    return t.get("txn_date") or t.get("date") or ""


def _txn_month(t: dict) -> str:
    return _txn_date(t)[:7]


def _txn_desc(t: dict) -> str:
    return t.get("merchant_display") or t.get("display_name") or t.get("description") or "Transaction"


def _label(month_key: str) -> str:
    """'2026-07' -> 'Jul 2026'. Locale-independent (no strftime)."""
    try:
        year, mon = month_key.split("-")
        return f"{_MONTHS[int(mon)]} {year}"
    except (ValueError, IndexError):
        return month_key


def _prev_month_key(month_key: str) -> str:
    """Calendar month before the given 'YYYY-MM'."""
    year, mon = int(month_key[:4]), int(month_key[5:7])
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"


def _empty_month(label: str = "") -> dict:
    return {"label": label, "spend": 0.0, "income": 0.0}


def _subscription_summary() -> dict:
    """Count and monthly/annual spend for active subscriptions (ignored excluded)."""
    subs = [s for s in db.list_subscriptions(include_ignored=False) if (s.get("status") or "") != "ignored"]
    monthly = 0.0
    for s in subs:
        amount = abs(float(s.get("amount") or 0))
        freq = (s.get("frequency") or "monthly").lower()
        if freq in ("yearly", "annual", "annually", "year"):
            monthly += amount / 12
        elif freq in ("weekly", "week"):
            monthly += amount * 52 / 12
        elif freq in ("quarterly", "quarter"):
            monthly += amount / 3
        else:  # monthly / unknown → treat as monthly
            monthly += amount
    monthly = round(monthly, 2)
    return {"count": len(subs), "monthly_total": monthly, "annualised": round(monthly * 12, 2)}


def _month_totals(txns: list[dict], key: str) -> dict:
    spend = 0.0
    income = 0.0
    for t in txns:
        if _txn_month(t) != key:
            continue
        amount = t.get("amount") or 0
        if amount < 0:
            spend += abs(amount)
        elif amount > 0:
            income += amount
    return {"label": _label(key), "spend": round(spend, 2), "income": round(income, 2)}


def build_insights() -> dict:
    txns = db.list_transactions_for_analysis(limit=1000)
    if not txns:
        return {
            "this_month": _empty_month(),
            "last_month": _empty_month(),
            "spend_delta_pct": None,
            "top_categories": [],
            "subscriptions": {"count": 0, "monthly_total": 0.0, "annualised": 0.0},
            "biggest_expense": None,
            "has_data": False,
        }

    # Anchor "this month" to the latest month present in the data, not the clock.
    months = sorted({m for m in (_txn_month(t) for t in txns) if m})
    this_key = months[-1] if months else ""
    last_key = _prev_month_key(this_key) if this_key else ""

    this_month = _month_totals(txns, this_key)
    last_month = _month_totals(txns, last_key)

    spend_delta_pct = None
    if last_month["spend"]:
        spend_delta_pct = round(
            (this_month["spend"] - last_month["spend"]) / last_month["spend"] * 100, 2
        )

    # This month's spend by category + the single biggest expense.
    cat_totals: dict[str, float] = {}
    biggest = None
    biggest_amt = -1.0
    for t in txns:
        if _txn_month(t) != this_key:
            continue
        amount = t.get("amount") or 0
        if amount >= 0:
            continue
        spend = abs(amount)
        category = t.get("category") or "Uncategorised"
        cat_totals[category] = cat_totals.get(category, 0.0) + spend
        if spend > biggest_amt:
            biggest_amt = spend
            biggest = {
                "description": _txn_desc(t),
                "amount": round(spend, 2),
                "date": _txn_date(t),
            }

    top_categories = [
        {"category": c, "amount": round(v, 2)}
        for c, v in sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    return {
        "this_month": this_month,
        "last_month": last_month,
        "spend_delta_pct": spend_delta_pct,
        "top_categories": top_categories,
        "subscriptions": _subscription_summary(),
        "biggest_expense": biggest,
        "has_data": True,
    }
