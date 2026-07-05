"""Detect recurring subscription payments from bank transactions."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from server import database as db

MIN_OCCURRENCES = 2
AMOUNT_VARIANCE = 0.2


def normalize_merchant(description: str) -> str:
    s = description.upper().strip()
    s = re.sub(r"\d{4,}", " ", s)
    s = re.sub(r"[#*]\w+", " ", s)
    for prefix in (
        "DD ",
        "SO ",
        "FPI ",
        "BANK ",
        "CARD PAYMENT TO ",
        "DIRECT DEBIT ",
        "CONTINUOUS AUTHORITY ",
    ):
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
    s = re.sub(r"[^\w\s&]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80] or description[:40].upper()


def _frequency_from_gap(avg_gap: float) -> str | None:
    if 25 <= avg_gap <= 38:
        return "monthly"
    if 6 <= avg_gap <= 10:
        return "weekly"
    if 350 <= avg_gap <= 380:
        return "yearly"
    if 85 <= avg_gap <= 100:
        return "quarterly"
    return None


def detect_subscriptions(transactions: list[dict] | None = None) -> list[dict]:
    txns = transactions if transactions is not None else db.list_transactions_for_analysis()
    expenses = [t for t in txns if float(t["amount"]) < 0]
    groups: dict[str, list[dict]] = defaultdict(list)

    for t in expenses:
        key = normalize_merchant(t["description"])
        if len(key) < 3:
            continue
        groups[key].append(t)

    results: list[dict] = []
    for key, group in groups.items():
        if len(group) < MIN_OCCURRENCES:
            continue

        amounts = [abs(float(t["amount"])) for t in group]
        med = median(amounts)
        if med < 0.5:
            continue
        if max(amounts) - min(amounts) > max(med * AMOUNT_VARIANCE, 0.5):
            continue

        try:
            dates = sorted(date.fromisoformat(t["date"][:10]) for t in group)
        except ValueError:
            continue
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        if not gaps:
            continue

        avg_gap = sum(gaps) / len(gaps)
        frequency = _frequency_from_gap(avg_gap)
        if not frequency:
            continue

        last_date = dates[-1]
        next_date = last_date + timedelta(days=int(round(avg_gap)))
        display = max(group, key=lambda t: t["date"])["description"].strip()

        results.append(
            {
                "merchant_key": key,
                "display_name": display,
                "amount": round(med, 2),
                "frequency": frequency,
                "occurrence_count": len(group),
                "last_charge_date": last_date.isoformat(),
                "next_expected_date": next_date.isoformat(),
                "account": group[-1].get("account") or group[-1].get("account_id", ""),
                "category": group[-1].get("category", "Subscriptions"),
            }
        )

    return sorted(results, key=lambda x: (-x["amount"], x["display_name"]))


def monthly_equivalent(amount: float, frequency: str) -> float:
    if frequency == "weekly":
        return round(amount * 52 / 12, 2)
    if frequency == "yearly":
        return round(amount / 12, 2)
    if frequency == "quarterly":
        return round(amount / 3, 2)
    return round(amount, 2)


def build_summary(subscriptions: list[dict]) -> dict:
    active = [s for s in subscriptions if s.get("status") != "ignored"]
    monthly = sum(monthly_equivalent(s["amount"], s["frequency"]) for s in active)
    return {
        "active_count": len(active),
        "monthly_total": round(monthly, 2),
        "yearly_estimate": round(monthly * 12, 2),
    }


def refresh_subscriptions() -> dict:
    detected = detect_subscriptions()
    items = db.sync_subscriptions(detected)
    visible = [s for s in items if s["status"] != "ignored"]
    return {"subscriptions": visible, "summary": build_summary(items), "ignored_count": len(items) - len(visible)}
