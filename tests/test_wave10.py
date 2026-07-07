"""Wave-10 backend: household vehicles (MOT/tax/insurance/service tracker).

Covers the db CRUD helpers + the vehicles_due_within() window, the
GET/POST/PATCH/DELETE /api/vehicles routes and the optional DVLA reg-lookup
(dormant with no key — the not-configured branch is exercised directly, and the
configured branch is driven with the DVLA call stubbed so the real API is never
hit), plus the vehicle-renewal nudge folded into run_reminders().

Rows live on a shared box, so every test cleans up the vehicles it creates and
restores any user phone it set.
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import reminders as reminders_svc
from server.services import vehicles as vehicles_svc
from server.services import whatsapp


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    """Capture whatsapp.send_text calls instead of hitting the network."""
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


# --- db CRUD ---------------------------------------------------------------

def test_vehicle_db_crud():
    v = db.create_vehicle({"name": "DB Van", "reg": "VAN1", "make": "Ford", "notes": "runabout"})
    try:
        assert v["id"] and v["name"] == "DB Van" and v["reg"] == "VAN1"
        got = db.get_vehicle(v["id"])
        assert got and got["name"] == "DB Van" and got["make"] == "Ford"

        # partial update touches only the given fields
        upd = db.update_vehicle(v["id"], {"model": "Transit", "insurance_due": "2027-06-01"})
        assert upd["model"] == "Transit" and upd["insurance_due"] == "2027-06-01"
        assert upd["reg"] == "VAN1"                      # untouched field preserved

        # a nullable field can be cleared to NULL via presence
        upd2 = db.update_vehicle(v["id"], {"reg": None})
        assert upd2["reg"] is None

        # updating a missing vehicle → None
        assert db.update_vehicle("does-not-exist", {"name": "x"}) is None

        assert db.delete_vehicle(v["id"]) is True
        assert db.get_vehicle(v["id"]) is None
        assert db.delete_vehicle(v["id"]) is False       # already gone
    finally:
        db.delete_vehicle(v["id"])


# --- vehicles_due_within() window ------------------------------------------

def test_vehicles_due_within_window():
    soon = db.create_vehicle({"name": "Soon", "reg": "SO12 ON",
                              "mot_due": (date.today() + timedelta(days=10)).isoformat()})
    multi = db.create_vehicle({"name": "Multi",
                               "mot_due": (date.today() + timedelta(days=3)).isoformat(),
                               "tax_due": (date.today() + timedelta(days=4)).isoformat()})
    far = db.create_vehicle({"name": "Far",
                             "mot_due": (date.today() + timedelta(days=400)).isoformat()})
    none_v = db.create_vehicle({"name": "NoDates"})
    try:
        within30 = db.vehicles_due_within(30)
        pairs = {(e["vehicle_id"], e["kind"]) for e in within30}

        # the 10-day MOT is included, with the expected entry shape
        assert (soon["id"], "MOT") in pairs
        entry = next(e for e in within30 if e["vehicle_id"] == soon["id"])
        assert entry["kind"] == "MOT" and entry["name"] == "Soon"
        assert entry["reg"] == "SO12 ON" and entry["due_date"]

        # a vehicle with two due fields yields one entry per field
        assert (multi["id"], "MOT") in pairs
        assert (multi["id"], "Tax") in pairs

        # the far-future and the date-less vehicles are excluded
        assert all(e["vehicle_id"] != far["id"] for e in within30)
        assert all(e["vehicle_id"] != none_v["id"] for e in within30)

        # a narrower window drops the 10-day MOT but keeps the 3/4-day ones
        within5 = db.vehicles_due_within(5)
        assert all(e["vehicle_id"] != soon["id"] for e in within5)
        assert (multi["id"], "MOT") in {(e["vehicle_id"], e["kind"]) for e in within5}
    finally:
        for vv in (soon, multi, far, none_v):
            db.delete_vehicle(vv["id"])


# --- routes: CRUD ----------------------------------------------------------

def test_vehicle_crud_routes(client):
    r = client.post("/api/vehicles", json={
        "name": "Family Car", "reg": "AB12 CDE", "make": "Toyota",
        "mot_due": "2027-01-15", "notes": "the blue one",
    })
    assert r.status_code == 200, r.text
    v = r.json()["vehicle"]
    vid = v["id"]
    try:
        assert v["name"] == "Family Car" and v["make"] == "Toyota"
        assert v["mot_due"] == "2027-01-15" and v["notes"] == "the blue one"

        # blank name is rejected
        assert client.post("/api/vehicles", json={"name": "   "}).status_code == 400

        # GET lists the new vehicle
        listed = client.get("/api/vehicles").json()["vehicles"]
        assert any(x["id"] == vid for x in listed)

        # PATCH updates the given fields only
        p = client.patch(f"/api/vehicles/{vid}", json={"model": "Corolla", "tax_due": "2027-03-01"})
        assert p.status_code == 200, p.text
        pv = p.json()["vehicle"]
        assert pv["model"] == "Corolla" and pv["tax_due"] == "2027-03-01"
        assert pv["name"] == "Family Car"                # untouched

        # PATCH can clear a nullable date to null
        p2 = client.patch(f"/api/vehicles/{vid}", json={"mot_due": None})
        assert p2.json()["vehicle"]["mot_due"] is None

        # PATCH / DELETE of a missing id → 404
        assert client.patch("/api/vehicles/nope", json={"name": "x"}).status_code == 404

        d = client.delete(f"/api/vehicles/{vid}")
        assert d.status_code == 200 and d.json()["ok"] is True
        assert client.delete(f"/api/vehicles/{vid}").status_code == 404   # already gone
        assert db.get_vehicle(vid) is None
    finally:
        db.delete_vehicle(vid)


# --- routes: DVLA reg lookup -----------------------------------------------

def test_vehicle_lookup_not_configured(client, monkeypatch):
    # No key → the feature is dormant; it must NOT reach the real DVLA API.
    monkeypatch.delenv("DVLA_API_KEY", raising=False)
    assert vehicles_svc.is_lookup_configured() is False

    r = client.post("/api/vehicles/lookup", json={"reg": "AB12CDE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert "DVLA_API_KEY" in body["message"]


def test_vehicle_lookup_configured_stubbed(client, monkeypatch):
    # Drive the configured branch with the DVLA call stubbed — no network.
    monkeypatch.setattr(vehicles_svc, "is_lookup_configured", lambda: True)

    async def fake_lookup(reg):
        return {"make": "Tesla", "mot_due": "2027-09-01", "tax_due": "2027-08-01", "year": 2020}

    monkeypatch.setattr(vehicles_svc, "lookup_reg", fake_lookup)
    r = client.post("/api/vehicles/lookup", json={"reg": "TES LA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["make"] == "Tesla" and body["mot_due"] == "2027-09-01" and body["year"] == 2020

    # an unknown plate (ValueError) surfaces as a 404
    async def fake_notfound(reg):
        raise ValueError("Vehicle not found")

    monkeypatch.setattr(vehicles_svc, "lookup_reg", fake_notfound)
    assert client.post("/api/vehicles/lookup", json={"reg": "ZZ99ZZZ"}).status_code == 404


# --- reminders integration -------------------------------------------------

def test_vehicle_renewal_reminder_fires_once_then_dedupes(monkeypatch):
    calls = _record_sends(monkeypatch)

    # Only Luke is in the household (one recipient → exactly one message).
    db.update_user("luke", {"phone": "+447700900333"})
    db.update_user("partner", {"phone": ""})

    # Master on, renewals on (vehicles gate under this), every other category off.
    db.update_notification_prefs({
        "master_enabled": True,
        "reminder_lead_days": 5,
        "appointment_reminders": False,
        "bill_reminders": False,
        "renewal_reminders": True,
        "document_expiry_reminders": False,
        "large_transaction_alerts": False,
        "budget_alerts": False,
    })

    marker = f"Batmobile {uuid.uuid4().hex[:5]}"
    due = (date.today() + timedelta(days=2)).isoformat()
    v = db.create_vehicle({"name": marker, "reg": "BAT 123", "mot_due": due})
    try:
        asyncio.run(reminders_svc.run_reminders())
        mot_msgs = [b for _to, b in calls if marker in b and "MOT" in b]
        assert len(mot_msgs) == 1, calls                 # fired ONCE for this vehicle+MOT
        assert mot_msgs[0].startswith("🚗")
        assert "BAT 123" in mot_msgs[0]

        # a second run is de-duplicated — no repeat nudge
        calls.clear()
        asyncio.run(reminders_svc.run_reminders())
        assert not any(marker in b for _to, b in calls), calls
    finally:
        db.update_user("luke", {"phone": ""})
        db.update_user("partner", {"phone": ""})
        db.delete_vehicle(v["id"])


def test_vehicle_renewal_reminder_gated_by_renewal_pref(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900444"})
    db.update_user("partner", {"phone": ""})

    marker = f"Speeder {uuid.uuid4().hex[:5]}"
    due = (date.today() + timedelta(days=1)).isoformat()
    v = db.create_vehicle({"name": marker, "mot_due": due})
    try:
        # renewal gate OFF → no vehicle nudge even though it's due.
        db.update_notification_prefs({
            "master_enabled": True,
            "reminder_lead_days": 5,
            "appointment_reminders": False,
            "bill_reminders": False,
            "renewal_reminders": False,
            "document_expiry_reminders": False,
            "large_transaction_alerts": False,
            "budget_alerts": False,
        })
        asyncio.run(reminders_svc.run_reminders())
        assert not any(marker in b for _to, b in calls), calls

        # renewal gate ON → the vehicle nudge fires.
        db.update_notification_prefs({"renewal_reminders": True})
        asyncio.run(reminders_svc.run_reminders())
        assert any(marker in b and "MOT" in b for _to, b in calls), calls
    finally:
        db.update_user("luke", {"phone": ""})
        db.update_user("partner", {"phone": ""})
        db.delete_vehicle(v["id"])
