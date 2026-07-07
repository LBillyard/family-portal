"""Wave-6 backend: family occasions (annual recurrence + countdown), home inventory
/ warranty tracker, and the occasion + warranty nudges folded into run_reminders().
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import occasions as occasions_svc
from server.services import reminders as reminders_svc
from server.services import whatsapp


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


def _occasion_dating_in(days: int) -> str:
    """A YYYY-MM-DD (year 2000) whose month/day is `days` from today."""
    target = date.today() + timedelta(days=days)
    return date(2000, target.month, target.day).isoformat()


# --- occasion recurrence math ---------------------------------------------

def test_next_occurrence_and_years():
    nd, years = occasions_svc.next_occurrence("2023-09-18", date(2026, 7, 7))
    assert nd == date(2026, 9, 18)
    assert years == 3                                  # born 2023 → turns 3 in 2026
    # already passed this year → rolls to next year
    nd2, _ = occasions_svc.next_occurrence("1990-01-01", date(2026, 7, 7))
    assert nd2 == date(2027, 1, 1)
    # leap-day clamps in a non-leap year
    nd3, _ = occasions_svc.next_occurrence("2020-02-29", date(2026, 3, 1))
    assert nd3 == date(2027, 2, 28)
    assert occasions_svc.next_occurrence("garbage") is None


def test_occasion_crud_and_upcoming():
    o = db.create_occasion({"title": "Wedding", "kind": "anniversary", "date": "2023-05-26", "person": "Us"})
    assert any(x["id"] == o["id"] for x in db.list_occasions())
    up = occasions_svc.upcoming_occasions()
    row = next((x for x in up if x["id"] == o["id"]), None)
    assert row is not None
    assert "days_until" in row and "next_date" in row and row["kind"] == "anniversary"
    assert db.delete_occasion(o["id"]) is True


def test_occasion_routes(client):
    r = client.post("/api/occasions", json={"title": "Dad bday", "kind": "birthday", "date": "1955-04-02"})
    assert r.status_code == 200, r.text
    oid = r.json()["occasion"]["id"]
    got = client.get("/api/occasions").json()["occasions"]
    assert any(x["id"] == oid and "days_until" in x for x in got)      # enriched w/ countdown
    assert client.post("/api/occasions", json={"title": "x", "date": ""}).status_code == 400
    assert client.patch(f"/api/occasions/{oid}", json={"notes": "socks"}).json()["occasion"]["notes"] == "socks"
    assert client.delete(f"/api/occasions/{oid}").json()["ok"] is True


# --- inventory / warranty --------------------------------------------------

def test_inventory_crud_and_expiring_window():
    it = db.create_inventory_item({"name": "Dishwasher", "category": "appliance", "brand": "Bosch",
                                   "warranty_expiry": "2035-01-01", "price": 500.0})
    assert it["price"] == 500.0
    soon = db.create_inventory_item({"name": "Kettle",
                                     "warranty_expiry": (date.today() + timedelta(days=10)).isoformat()})
    exp = db.inventory_expiring_within(30)
    assert any(x["id"] == soon["id"] for x in exp)          # 10-day kettle included
    assert all(x["id"] != it["id"] for x in exp)            # 2035 dishwasher excluded
    db.delete_inventory_item(it["id"]); db.delete_inventory_item(soon["id"])


def test_inventory_routes(client):
    r = client.post("/api/inventory", json={"name": "TV", "category": "electronics", "price": 1200})
    assert r.status_code == 200, r.text
    iid = r.json()["item"]["id"]
    assert any(x["id"] == iid for x in client.get("/api/inventory").json()["items"])
    assert client.post("/api/inventory", json={"name": "  "}).status_code == 400
    assert client.patch(f"/api/inventory/{iid}", json={"serial": "SN123"}).json()["item"]["serial"] == "SN123"
    assert client.delete(f"/api/inventory/{iid}").json()["ok"] is True


# --- reminders integration -------------------------------------------------

def test_occasion_headsup_fires_once(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900111"})
    db.update_notification_prefs({
        "master_enabled": True, "appointment_reminders": False, "bill_reminders": False,
        "renewal_reminders": False, "document_expiry_reminders": False, "large_transaction_alerts": False,
    })
    marker = f"Party {uuid.uuid4().hex[:5]}"
    o = db.create_occasion({"title": marker, "kind": "birthday", "date": _occasion_dating_in(3)})

    asyncio.run(reminders_svc.run_reminders())
    assert any(marker in b for _to, b in calls), calls          # within-7-day heads-up fired
    calls.clear()
    asyncio.run(reminders_svc.run_reminders())
    assert not any(marker in b for _to, b in calls)             # deduped

    db.update_user("luke", {"phone": ""}); db.delete_occasion(o["id"])


def test_warranty_reminder_gated_by_expiry_pref(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900222"})
    marker = f"Widget {uuid.uuid4().hex[:5]}"
    it = db.create_inventory_item({"name": marker,
                                   "warranty_expiry": (date.today() + timedelta(days=1)).isoformat()})

    # Gate OFF → no warranty nudge.
    db.update_notification_prefs({
        "master_enabled": True, "appointment_reminders": False, "bill_reminders": False,
        "renewal_reminders": False, "document_expiry_reminders": False, "large_transaction_alerts": False,
    })
    asyncio.run(reminders_svc.run_reminders())
    assert not any(marker in b for _to, b in calls)

    # Gate ON → warranty nudge fires.
    db.update_notification_prefs({"document_expiry_reminders": True})
    asyncio.run(reminders_svc.run_reminders())
    assert any(marker in b and "Warranty" in b for _to, b in calls), calls

    db.update_user("luke", {"phone": ""}); db.delete_inventory_item(it["id"])
