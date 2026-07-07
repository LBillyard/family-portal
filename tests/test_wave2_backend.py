"""Wave-2 backend: unified search, web push routes, and inbox auto-file import.

Search + push route tests use the shared authenticated `client` fixture; the push
tests monkeypatch the push service so nothing is actually sent. The inbox-import
test drives the real db.create_* path (no mocking) and checks the rows appear.
"""

import uuid

from server import database as db
from server.services import push as push_svc
from server.services import search as search_svc


def _tok() -> str:
    return "zwave2" + uuid.uuid4().hex[:8]


# --- (a) Unified search ---------------------------------------------------

def test_search_all_finds_seeded_entities_with_tabs():
    tok = _tok()
    task = db.create_task({"title": f"Task {tok}"})
    doc = db.create_document({"name": f"Doc {tok}", "category": "personal"})
    person = db.create_tradesperson({"name": f"Sparky {tok}", "trade": "Electrician"})
    try:
        results = search_svc.search_all(tok)
        by_type = {r["type"]: r for r in results}

        assert "task" in by_type and by_type["task"]["tab"] == "home"
        assert "document" in by_type and by_type["document"]["tab"] == "documents"
        assert "tradesperson" in by_type and by_type["tradesperson"]["tab"] == "homecare"

        # Uniform result shape.
        for r in results:
            assert set(r) >= {"type", "title", "subtitle", "tab", "id"}
    finally:
        db.delete_task(task["id"])
        db.delete_document(doc["id"])
        db.delete_tradesperson(person["id"])


def test_search_all_empty_query_returns_empty():
    assert search_svc.search_all("") == []
    assert search_svc.search_all("   ") == []


def test_search_route_returns_query_and_results(client):
    tok = _tok()
    person = db.create_tradesperson({"name": f"Plumber {tok}", "trade": "Plumber"})
    try:
        resp = client.get(f"/api/search?q={tok}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["query"] == tok
        hit = next((r for r in body["results"] if r["type"] == "tradesperson"), None)
        assert hit is not None
        assert hit["tab"] == "homecare"
        assert hit["title"] == f"Plumber {tok}"
    finally:
        db.delete_tradesperson(person["id"])

    # Empty query -> empty results.
    empty = client.get("/api/search?q=").json()
    assert empty["results"] == []


# --- (b) Web push routes --------------------------------------------------

def test_push_vapid_key_shape(client, monkeypatch):
    monkeypatch.setattr(push_svc, "is_configured", lambda: True)
    monkeypatch.setattr(push_svc, "get_public_key", lambda: "test-vapid-public-key")
    resp = client.get("/api/push/vapid-key")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"key": "test-vapid-public-key", "enabled": True}


def test_push_subscribe_stores_subscription(client):
    endpoint = f"https://push.example.com/{uuid.uuid4().hex}"
    resp = client.post(
        "/api/push/subscribe",
        json={"endpoint": endpoint, "p256dh": "test-p256dh", "auth": "test-auth"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    stored = {s["endpoint"] for s in db.list_push_subscriptions()}
    assert endpoint in stored

    # Unsubscribe removes it again.
    gone = client.post("/api/push/unsubscribe", json={"endpoint": endpoint})
    assert gone.status_code == 200, gone.text
    assert gone.json() == {"ok": True}
    assert endpoint not in {s["endpoint"] for s in db.list_push_subscriptions()}


def test_push_test_returns_count(client, monkeypatch):
    monkeypatch.setattr(push_svc, "notify", lambda *a, **k: 3)
    resp = client.post("/api/push/test")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sent": 3}


# --- (c) Inbox auto-file import ------------------------------------------

def test_inbox_import_creates_trip_and_appointment(client):
    tok = _tok()
    trip_title = f"Trip {tok}"
    appt_title = f"Dentist {tok}"
    resp = client.post(
        "/api/inbox/import",
        json={
            "items": [
                {
                    "kind": "trip",
                    "title": trip_title,
                    "destination": "Barcelona",
                    "start": "2026-09-01",
                    "end": "2026-09-08",
                },
                {
                    "kind": "appointment",
                    "title": appt_title,
                    "provider": "Smile Clinic",
                    "datetime": "2026-08-15T09:30",
                    "category": "health",
                },
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["created"] == 2
    assert result["by_kind"].get("trip") == 1
    assert result["by_kind"].get("appointment") == 1

    trip = next((t for t in db.list_trips() if t["title"] == trip_title), None)
    assert trip is not None
    assert trip["status"] == "booked"
    assert trip["destination"] == "Barcelona"

    appt = next((a for a in db.list_appointments() if a["title"] == appt_title), None)
    assert appt is not None
    assert appt["provider"] == "Smile Clinic"

    # Cleanup.
    if trip:
        db.delete_trip(trip["id"])
    if appt:
        db.delete_appointment(appt["id"])
