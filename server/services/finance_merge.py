"""Merge manual bills with detected bank subscriptions."""

from __future__ import annotations

import re

from server import database as db


def _norm(s: str) -> str:
    s = s.upper()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_score(bill_name: str, sub_name: str) -> float:
    a, b = _norm(bill_name), _norm(sub_name)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    aw, bw = set(a.split()), set(b.split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / max(len(aw), len(bw))


def build_merged_recurring() -> dict:
    bills = db.list_bills()
    subs = [s for s in db.list_subscriptions(include_ignored=False) if s.get("status") != "ignored"]
    used_sub_ids: set[str] = set()
    merged: list[dict] = []
    duplicate_savings = 0.0

    for bill in bills:
        best = None
        best_score = 0.55
        for sub in subs:
            if sub["id"] in used_sub_ids:
                continue
            if bill.get("subscription_id") == sub["id"]:
                best, best_score = sub, 1.0
                break
            score = _match_score(bill["name"], sub["display_name"])
            if score > best_score:
                best, best_score = sub, score
        entry = {
            "id": bill["id"],
            "name": bill["name"],
            "amount": bill["amount"],
            "source": "bill",
            "bill_id": bill["id"],
            "subscription_id": None,
            "due_day": bill["due_day"],
            "category": bill["category"],
            "paid": bill["paid"],
            "frequency": bill.get("recurrence", "monthly"),
            "matched": False,
        }
        if best:
            entry["matched"] = True
            entry["subscription_id"] = best["id"]
            entry["bank_amount"] = best["amount"]
            entry["occurrence_count"] = best.get("occurrence_count", 0)
            entry["last_charge_date"] = best.get("last_charge_date")
            if abs(bill["amount"] - best["amount"]) > 0.01:
                entry["amount_note"] = f"Bill £{bill['amount']:.2f} vs bank £{best['amount']:.2f}"
            duplicate_savings += min(bill["amount"], best["amount"])
            used_sub_ids.add(best["id"])
            if not bill.get("subscription_id"):
                db.link_bill_subscription(bill["id"], best["id"])
        merged.append(entry)

    for sub in subs:
        if sub["id"] in used_sub_ids:
            continue
        merged.append(
            {
                "id": sub["id"],
                "name": sub["display_name"],
                "amount": sub["amount"],
                "source": "subscription",
                "bill_id": None,
                "subscription_id": sub["id"],
                "due_day": None,
                "category": sub.get("category", "Subscriptions"),
                "paid": False,
                "frequency": sub.get("frequency", "monthly"),
                "matched": False,
                "occurrence_count": sub.get("occurrence_count", 0),
                "last_charge_date": sub.get("last_charge_date"),
                "status": sub.get("status"),
            }
        )

    merged.sort(key=lambda x: -x["amount"])
    monthly = sum(
        x["amount"] for x in merged
        if x.get("frequency", "monthly") == "monthly" and not x.get("paid")
    )
    return {
        "items": merged,
        "summary": {
            "total_items": len(merged),
            "matched_pairs": sum(1 for x in merged if x.get("matched")),
            "bank_only": sum(1 for x in merged if x["source"] == "subscription"),
            "bill_only": sum(1 for x in merged if x["source"] == "bill" and not x.get("matched")),
            "estimated_monthly": round(monthly, 2),
        },
    }
