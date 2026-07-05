"""Natural-language household search across entities."""

from __future__ import annotations

import re

from server import database as db


def _tokens(q: str) -> list[str]:
    return [t for t in re.split(r"\W+", q.lower()) if len(t) >= 2]


def _score(text: str, tokens: list[str]) -> int:
    low = text.lower()
    return sum(1 for t in tokens if t in low)


def search(query: str, limit: int = 25) -> dict:
    q = (query or "").strip()
    tokens = _tokens(q)
    if not tokens:
        return {"query": q, "results": []}

    results: list[dict] = []

    for e in db.list_events():
        text = f"{e['title']} {e.get('location', '')}"
        s = _score(text, tokens)
        if s:
            results.append({"type": "event", "label": e["title"], "meta": e["start"], "tab": "calendar", "score": s, "id": e["id"]})

    for t in db.list_tasks():
        text = t["title"]
        s = _score(text, tokens)
        if s:
            results.append({"type": "task", "label": t["title"], "meta": t.get("due") or "No due date", "tab": "home", "score": s, "id": t["id"]})

    for b in db.list_bills():
        text = f"{b['name']} {b['category']}"
        s = _score(text, tokens)
        if s:
            results.append({"type": "bill", "label": b["name"], "meta": f"£{b['amount']:.2f} · day {b['due_day']}", "tab": "finances", "score": s, "id": b["id"]})

    for txn in db.list_transactions(limit=200):
        text = f"{txn['description']} {txn['category']}"
        s = _score(text, tokens)
        if s:
            results.append(
                {
                    "type": "transaction",
                    "label": txn["description"],
                    "meta": f"{txn['date']} · £{txn['amount']:.2f}",
                    "tab": "finances",
                    "score": s,
                    "id": txn["id"],
                }
            )

    for a in db.list_appointments():
        text = f"{a['title']} {a['provider']} {a.get('location', '')}"
        s = _score(text, tokens)
        if s:
            results.append({"type": "appointment", "label": a["title"], "meta": a["datetime"], "tab": "appointments", "score": s, "id": a["id"]})

    for trip in db.list_trips():
        text = trip["title"]
        s = _score(text, tokens)
        if s:
            results.append({"type": "trip", "label": trip["title"], "meta": trip.get("start") or trip["status"], "tab": "holidays", "score": s, "id": trip["id"]})

    for d in db.list_documents():
        text = f"{d['name']} {d.get('notes', '')} {d.get('category', '')}"
        s = _score(text, tokens)
        if s:
            results.append({"type": "document", "label": d["name"], "meta": d.get("expiry") or d.get("category", ""), "tab": "documents", "score": s, "id": d["id"]})

    for m in db.list_maintenance():
        text = f"{m['title']} {m.get('vendor', '')} {m.get('notes', '')}"
        s = _score(text, tokens)
        if s:
            results.append({"type": "maintenance", "label": m["title"], "meta": m.get("next_due_date") or "", "tab": "homecare", "score": s, "id": m["id"]})

    for sub in db.list_subscriptions(include_ignored=True):
        text = sub["display_name"]
        s = _score(text, tokens)
        if s:
            results.append(
                {
                    "type": "subscription",
                    "label": sub["display_name"],
                    "meta": f"£{sub['amount']:.2f} · {sub['frequency']}",
                    "tab": "subscriptions",
                    "score": s,
                    "id": sub["id"],
                }
            )

    results.sort(key=lambda x: (-x["score"], x["label"]))
    return {"query": q, "results": results[:limit]}
