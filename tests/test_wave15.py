"""Wave-15 backend: trip intelligence (build a trip's itinerary from travel
emails, detect trips hiding in the inbox) + the two assistant tools that expose
it.

Everything external is mocked: there is NO connected Google account (we
monkeypatch trip_intel.db.list_google_accounts -> []) so no real Gmail call is
made, and with no emails the OpenRouter extraction short-circuits to [] before
any HTTP request. So these tests never touch the network.

Covered:
- POST /api/trips/{id}/itinerary/import creates itinerary_items (visible via
  GET /api/itinerary?trip_id=), skips blank-title items, and 404s an unknown trip.
- POST /api/trips/{id}/scan-email 404s an unknown trip (before any Gmail work).
- trip_intel.scan_for_trip / detect_trips return empty gracefully (never raise)
  when the user has no connected Google account.
- assistant registers find_trips_in_email + build_trip_itinerary_from_email, and
  execute_tool('build_trip_itinerary_from_email', ...) is graceful when the trip
  can't be resolved.

Rows live on a shared box, so every test creates its own trip and deletes it in a
finally (delete_trip cascades the itinerary rows away).
"""

import asyncio
import uuid

from server import database as db
from server.services import assistant, trip_intel


def _make_trip() -> str:
    """A fresh holiday trip; returns its id. Caller must db.delete_trip() it."""
    trip = db.create_trip({"title": f"Wave15 Trip {uuid.uuid4().hex[:6]}", "status": "booked"})
    return trip["id"]


# --- route: POST /api/trips/{id}/itinerary/import ---------------------------

def test_itinerary_import_creates_items(client):
    tid = _make_trip()
    try:
        r = client.post(f"/api/trips/{tid}/itinerary/import", json={"items": [
            {"title": "Flight LGW->FAO", "kind": "flight",
             "day_date": "2027-06-01", "start_time": "07:30",
             "location": "LGW", "notes": "BA2734"},
            {"title": "Check in: Hotel Sol", "kind": "hotel",
             "day_date": "2027-06-01", "start_time": "15:00"},
        ]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["added"] == 2
        assert len(body["items"]) == 2

        # The imported items are now listed under the trip via /api/itinerary.
        listed = client.get(f"/api/itinerary?trip_id={tid}").json()["items"]
        titles = [i["title"] for i in listed]
        assert "Flight LGW->FAO" in titles and "Check in: Hotel Sol" in titles

        flight = next(i for i in listed if i["title"] == "Flight LGW->FAO")
        assert flight["kind"] == "flight"
        assert flight["day_date"] == "2027-06-01" and flight["start_time"] == "07:30"
        assert flight["location"] == "LGW" and flight["notes"] == "BA2734"
    finally:
        db.delete_trip(tid)


def test_itinerary_import_skips_blank_title(client):
    tid = _make_trip()
    try:
        r = client.post(f"/api/trips/{tid}/itinerary/import", json={"items": [
            {"title": "   ", "kind": "activity"},          # blank -> skipped
            {"title": "Museum visit", "kind": "activity"},  # kept
        ]})
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1

        listed = client.get(f"/api/itinerary?trip_id={tid}").json()["items"]
        assert [i["title"] for i in listed] == ["Museum visit"]
    finally:
        db.delete_trip(tid)


def test_itinerary_import_unknown_trip_404(client):
    r = client.post(
        f"/api/trips/no-such-trip-{uuid.uuid4().hex}/itinerary/import",
        json={"items": [{"title": "Ghost"}]},
    )
    assert r.status_code == 404, r.text


# --- route: POST /api/trips/{id}/scan-email ---------------------------------

def test_scan_email_unknown_trip_404(client):
    # Unknown trip -> 404 before any Gmail work is attempted.
    r = client.post(f"/api/trips/no-such-trip-{uuid.uuid4().hex}/scan-email")
    assert r.status_code == 404, r.text


# --- trip_intel: graceful with no connected Google account ------------------

def test_scan_for_trip_no_google_account(monkeypatch):
    # No connected account -> no Gmail, no emails, no AI call; empty + never raises.
    monkeypatch.setattr(trip_intel.db, "list_google_accounts", lambda *a, **k: [])
    res = asyncio.run(trip_intel.scan_for_trip("luke", {"title": "X"}))
    assert res["candidates"] == []
    assert res["scanned"] == 0
    assert res["needs_reconnect"] == []


def test_detect_trips_no_google_account(monkeypatch):
    monkeypatch.setattr(trip_intel.db, "list_google_accounts", lambda *a, **k: [])
    res = asyncio.run(trip_intel.detect_trips("luke"))
    assert res["proposals"] == []
    assert res["scanned"] == 0
    assert res["needs_reconnect"] == []


# --- assistant tools --------------------------------------------------------

def test_trip_tools_registered():
    names = {t["function"]["name"] for t in assistant.TOOLS}
    assert "find_trips_in_email" in names
    assert "build_trip_itinerary_from_email" in names


def test_build_trip_itinerary_from_email_unresolved_is_graceful(monkeypatch):
    # Gmail mocked empty; an unmatched trip_name -> ok False, no raise, no writes.
    monkeypatch.setattr(trip_intel.db, "list_google_accounts", lambda *a, **k: [])
    user = db.get_user_by_email("lbillyard@gmail.com")
    assert user, "seeded user should exist"
    res = asyncio.run(assistant.execute_tool(
        "build_trip_itinerary_from_email",
        {"trip_name": f"nonexistent-{uuid.uuid4().hex}"},
        user,
    ))
    assert res["ok"] is False
    assert "error" in res


def test_find_trips_in_email_no_account_is_graceful(monkeypatch):
    # With no connected account the tool still succeeds, just with no proposals.
    monkeypatch.setattr(trip_intel.db, "list_google_accounts", lambda *a, **k: [])
    user = db.get_user_by_email("lbillyard@gmail.com")
    res = asyncio.run(assistant.execute_tool("find_trips_in_email", {}, user))
    assert res["ok"] is True
    assert res["proposals"] == []
    assert res["scanned"] == 0
