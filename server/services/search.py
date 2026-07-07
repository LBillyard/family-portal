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


# --- Wave-2 unified search (title/subtitle/tab shape) ---
#
# `search_all` is a flat, case-insensitive substring search returning a uniform
# result shape the frontend can render and route on:
#   {"type", "title", "subtitle", "tab", "id"}
# It ranks exact matches above startswith above plain "contains".

_EXACT, _PREFIX, _CONTAINS = 3, 2, 1


def _match_rank(text: str | None, q: str) -> int:
    """0 no match; 3 exact; 2 startswith; 1 contains (all case-insensitive)."""
    if not text:
        return 0
    low = text.lower()
    if low == q:
        return _EXACT
    if low.startswith(q):
        return _PREFIX
    if q in low:
        return _CONTAINS
    return 0


def _money(value) -> str:
    try:
        return f"£{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def search_all(query: str, limit: int = 30) -> list[dict]:
    """Case-insensitive substring search across every household entity.

    Returns a ranked, capped list of {type, title, subtitle, tab, id} dicts;
    `tab` is the app tab to open for the result. Empty query -> empty list.
    """
    q = (query or "").strip().lower()
    if not q:
        return []

    scored: list[tuple[int, dict]] = []

    def consider(fields: list, result: dict) -> None:
        rank = max((_match_rank(f, q) for f in fields), default=0)
        if rank:
            scored.append((rank, result))

    # Calendar events — search title + location.
    for e in db.list_events():
        consider(
            [e.get("title"), e.get("location")],
            {"type": "event", "title": e["title"], "subtitle": e.get("start") or e.get("location") or "",
             "tab": "calendar", "id": e.get("id")},
        )

    # Transactions — search description.
    for t in db.list_transactions(limit=500):
        consider(
            [t.get("description")],
            {"type": "transaction", "title": t["description"],
             "subtitle": f"{t.get('date', '')} · {_money(t.get('amount'))}".strip(" ·"),
             "tab": "finances", "id": t.get("id")},
        )

    # Documents — search name + notes.
    for d in db.list_documents():
        consider(
            [d.get("name"), d.get("notes")],
            {"type": "document", "title": d["name"],
             "subtitle": d.get("expiry_date") or d.get("expiry") or d.get("category") or "",
             "tab": "documents", "id": d.get("id")},
        )

    # Memory facts — search the fact text.
    for m in db.list_memory_facts(include_embedding=False):
        consider(
            [m.get("text")],
            {"type": "memory", "title": m["text"], "subtitle": m.get("category") or "",
             "tab": "memory", "id": m.get("id")},
        )

    # Tasks — search title.
    for t in db.list_tasks():
        consider(
            [t.get("title")],
            {"type": "task", "title": t["title"], "subtitle": t.get("due") or "No due date",
             "tab": "home", "id": t.get("id")},
        )

    # Appointments — search title + provider.
    for a in db.list_appointments():
        consider(
            [a.get("title"), a.get("provider")],
            {"type": "appointment", "title": a["title"], "subtitle": a.get("provider") or a.get("datetime") or "",
             "tab": "appointments", "id": a.get("id")},
        )

    # Tradespeople — search name + trade + notes (they live on the homecare tab).
    for p in db.list_tradespeople():
        consider(
            [p.get("name"), p.get("trade"), p.get("notes")],
            {"type": "tradesperson", "title": p["name"], "subtitle": p.get("trade") or "",
             "tab": "homecare", "id": p.get("id")},
        )

    # Subscriptions — search display name.
    for s in db.list_subscriptions(include_ignored=True):
        consider(
            [s.get("display_name")],
            {"type": "subscription", "title": s["display_name"],
             "subtitle": f"{_money(s.get('amount'))} · {s.get('frequency', '')}".strip(" ·"),
             "tab": "subscriptions", "id": s.get("id")},
        )

    # Bills — search name.
    for b in db.list_bills():
        consider(
            [b.get("name")],
            {"type": "bill", "title": b["name"],
             "subtitle": f"{_money(b.get('amount'))} · day {b.get('due_day')}".strip(" ·"),
             "tab": "finances", "id": b.get("id")},
        )

    scored.sort(key=lambda sr: (-sr[0], (sr[1].get("title") or "").lower()))
    return [result for _rank, result in scored[:limit]]
