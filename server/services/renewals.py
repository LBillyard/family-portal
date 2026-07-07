"""Unified renewal calendar — documents, maintenance, subscriptions, bills."""

from __future__ import annotations

from datetime import date, timedelta

from server import database as db


def _days_until(iso: str) -> int | None:
    if not iso or len(iso) < 10:
        return None
    try:
        return (date.fromisoformat(iso[:10]) - date.today()).days
    except ValueError:
        return None


def build_renewal_calendar(days_ahead: int = 90) -> dict:
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    items: list[dict] = []

    for doc in db.list_documents():
        if not doc.get("expiry"):
            continue
        try:
            due = date.fromisoformat(doc["expiry"][:10])
        except ValueError:
            continue
        if due > cutoff:
            continue
        items.append(
            {
                "id": f"doc-{doc['id']}",
                "source_id": doc["id"],
                "type": "document",
                "title": doc["name"],
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": doc.get("category", "other"),
                "status": doc.get("status", "ok"),
                "detail": doc.get("notes", ""),
            }
        )

    for m in db.list_maintenance():
        if not m.get("next_due_date"):
            continue
        try:
            due = date.fromisoformat(m["next_due_date"][:10])
        except ValueError:
            continue
        if due > cutoff:
            continue
        items.append(
            {
                "id": f"maint-{m['id']}",
                "source_id": m["id"],
                "type": "maintenance",
                "title": m["title"],
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": m.get("category", "general"),
                "status": "due" if due <= today else "upcoming",
                "detail": m.get("vendor", ""),
            }
        )

    for sub in db.list_subscriptions(include_ignored=False):
        if sub.get("status") in ("ignored", "lapsed") or not sub.get("next_expected_date"):
            continue
        try:
            due = date.fromisoformat(sub["next_expected_date"][:10])
        except ValueError:
            continue
        if due > cutoff:
            continue
        items.append(
            {
                "id": f"sub-{sub['id']}",
                "source_id": sub["id"],
                "type": "subscription",
                "title": sub["display_name"],
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": "Subscriptions",
                "status": sub.get("status", "detected"),
                "detail": f"{sub['frequency']} · {sub['amount']}",
            }
        )

    for bill in db.list_bills():
        if bill.get("paid"):
            continue
        day = min(bill["due_day"], 28)
        due = today.replace(day=day)
        if due < today:
            if today.month == 12:
                due = date(today.year + 1, 1, min(bill["due_day"], 28))
            else:
                due = date(today.year, today.month + 1, min(bill["due_day"], 28))
        if due > cutoff:
            continue
        items.append(
            {
                "id": f"bill-{bill['id']}",
                "source_id": bill["id"],
                "type": "bill",
                "title": bill["name"],
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": bill.get("category", "Other"),
                "status": "unpaid",
                "detail": f"£{bill['amount']:.2f}",
            }
        )

    for v in db.vehicles_due_within(days_ahead):
        try:
            due = date.fromisoformat(str(v["due_date"])[:10])
        except (ValueError, TypeError):
            continue
        if due > cutoff:
            continue
        items.append(
            {
                "id": f"vehicle-{v['vehicle_id']}-{v['kind']}",
                "source_id": v["vehicle_id"],
                "type": "vehicle",
                "title": f"{v['name']} — {v['kind']}",
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": "Vehicles",
                "status": "due" if due <= today else "upcoming",
                "detail": v.get("reg") or "",
            }
        )

    for c in db.care_due_within(days_ahead):
        try:
            due = date.fromisoformat(str(c["due_date"])[:10])
        except (ValueError, TypeError):
            continue
        if due > cutoff:
            continue
        who = c.get("dependent_name") or ""
        items.append(
            {
                "id": f"care-{c['id']}",
                "source_id": c["id"],
                "type": "care",
                "title": f"{who}: {c['title']}" if who else c["title"],
                "date": due.isoformat(),
                "days_until": (due - today).days,
                "category": c.get("category") or "Care",
                "status": "due" if due <= today else "upcoming",
                "detail": c.get("notes") or "",
            }
        )

    items.sort(key=lambda x: (x["days_until"], x["title"]))
    overdue = [i for i in items if i["days_until"] < 0]
    this_month = [i for i in items if 0 <= i["days_until"] <= 30]
    return {
        "items": items,
        "overdue_count": len(overdue),
        "this_month_count": len(this_month),
        "days_ahead": days_ahead,
    }
