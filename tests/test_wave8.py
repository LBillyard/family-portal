"""Wave-8 backend: household wishlist (gift ideas per person) with a purchased
toggle, a budget-alerts notification preference, and budget-overspend alerts
folded into run_reminders().

Service/db tests drive the code directly; route tests use the shared authenticated
`client` fixture from conftest; the reminders test monkeypatches whatsapp.send_text
to record (phone, body) instead of sending. Rows live in a shared DB, so every
test tags its data with a unique marker and cleans up after itself.
"""

import asyncio
import uuid
from datetime import date

from server import database as db
from server.services import reminders as reminders_svc
from server.services import whatsapp


# --- helpers ---------------------------------------------------------------

def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


def _ensure_account(name: str, acc_type: str, balance: float) -> str:
    """Create an account directly (no public create_account helper) and return its id."""
    aid = f"acc-{uuid.uuid4().hex[:8]}"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, name, acc_type, balance, "Test Bank"),
        )
    return aid


# --- Wishlist: db CRUD + purchased toggle + person filter ------------------

def test_wishlist_db_crud_and_person_filter():
    who = f"Kid {uuid.uuid4().hex[:5]}"
    other = f"Gran {uuid.uuid4().hex[:5]}"

    a = db.create_wishlist_item({"person": who, "title": "Lego set", "url": "http://x/y",
                                 "price": 39.99, "notes": "the big one"})
    b = db.create_wishlist_item({"person": other, "title": "Slippers"})
    try:
        assert a["purchased"] is False                      # default unpurchased
        assert a["price"] == 39.99
        assert a["notes"] == "the big one"
        assert db.get_wishlist_item(a["id"])["title"] == "Lego set"

        # person filter returns only that person's items
        mine = db.list_wishlist_items(who)
        assert any(x["id"] == a["id"] for x in mine)
        assert all(x["person"] == who for x in mine)
        assert all(x["id"] != b["id"] for x in mine)        # other person excluded

        # unfiltered listing sees both
        all_ids = {x["id"] for x in db.list_wishlist_items()}
        assert {a["id"], b["id"]} <= all_ids

        # partial update: clear price to NULL (presence-based), tweak notes
        upd = db.update_wishlist_item(a["id"], {"price": None, "notes": "on sale"})
        assert upd["price"] is None and upd["notes"] == "on sale"

        # purchased toggle round-trips through update
        assert db.update_wishlist_item(a["id"], {"purchased": True})["purchased"] is True
        assert db.update_wishlist_item(a["id"], {"purchased": False})["purchased"] is False

        assert db.update_wishlist_item("nope-id", {"title": "x"}) is None
    finally:
        assert db.delete_wishlist_item(a["id"]) is True
        assert db.delete_wishlist_item(b["id"]) is True
    assert db.delete_wishlist_item(a["id"]) is False        # already gone
    assert db.get_wishlist_item(a["id"]) is None


# --- Wishlist: routes GET/POST/PATCH/DELETE + /purchased + person filter ----

def test_wishlist_routes_and_purchased_toggle(client):
    alice = f"Alice {uuid.uuid4().hex[:5]}"
    bob = f"Bob {uuid.uuid4().hex[:5]}"
    title = f"Headphones {uuid.uuid4().hex[:5]}"

    r = client.post("/api/wishlist", json={"title": title, "person": alice,
                                           "price": 120, "url": "http://shop/hp", "notes": "wireless"})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    wid = item["id"]
    assert item["purchased"] is False
    assert item["price"] == 120.0

    # a second item for a different person, to prove the ?person= filter
    r2 = client.post("/api/wishlist", json={"title": "Book", "person": bob})
    assert r2.status_code == 200, r2.text
    bid = r2.json()["item"]["id"]

    try:
        assert client.post("/api/wishlist", json={"title": "   "}).status_code == 400   # blank title rejected

        # unfiltered GET sees both
        listed = client.get("/api/wishlist").json()["items"]
        assert {wid, bid} <= {x["id"] for x in listed}

        # filtered GET returns only Alice's item
        just_alice = client.get("/api/wishlist", params={"person": alice}).json()["items"]
        assert any(x["id"] == wid for x in just_alice)
        assert all(x["person"] == alice for x in just_alice)
        assert all(x["id"] != bid for x in just_alice)

        # PATCH updates fields; missing id → 404
        patched = client.patch(f"/api/wishlist/{wid}", json={"notes": "over-ear"}).json()["item"]
        assert patched["notes"] == "over-ear"
        assert client.patch("/api/wishlist/missing", json={"notes": "x"}).status_code == 404

        # /purchased marks it bought, then un-buys it; missing id → 404
        done = client.post(f"/api/wishlist/{wid}/purchased", json={"purchased": True})
        assert done.status_code == 200 and done.json()["item"]["purchased"] is True
        undo = client.post(f"/api/wishlist/{wid}/purchased", json={"purchased": False})
        assert undo.json()["item"]["purchased"] is False
        assert client.post("/api/wishlist/missing/purchased", json={"purchased": True}).status_code == 404

        assert client.delete(f"/api/wishlist/{wid}").json()["ok"] is True
        assert client.delete(f"/api/wishlist/{wid}").status_code == 404    # already gone
    finally:
        client.delete(f"/api/wishlist/{wid}")
        client.delete(f"/api/wishlist/{bid}")


# --- budget_alerts preference round-trips (db + route) ---------------------

def test_budget_alerts_pref_round_trip():
    # db-level round-trip
    assert db.update_notification_prefs({"budget_alerts": False})["budget_alerts"] is False
    assert db.get_notification_prefs()["budget_alerts"] is False
    assert db.update_notification_prefs({"budget_alerts": True})["budget_alerts"] is True
    assert db.get_notification_prefs()["budget_alerts"] is True


def test_budget_alerts_pref_route_round_trip(client):
    off = client.patch("/api/notifications/prefs", json={"budget_alerts": False})
    assert off.status_code == 200, off.text
    assert off.json()["budget_alerts"] is False
    assert client.get("/api/notifications/prefs").json()["budget_alerts"] is False

    on = client.patch("/api/notifications/prefs", json={"budget_alerts": True})
    assert on.json()["budget_alerts"] is True
    assert client.get("/api/notifications/prefs").json()["budget_alerts"] is True


# --- reminders: an over-budget category alerts the household once ----------

def test_over_budget_alert_fires_once(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900888"})

    # A unique category so it's identifiable in the message body and its dedupe
    # key can't collide with any other budget in the shared DB.
    category = f"W8Cat {uuid.uuid4().hex[:6]}"
    acc = _ensure_account("W8 Budget", "current", 0.0)

    # Budget limit £100; spend £150 this month → 150% → 'over'.
    db.create_budget(category, 100.0)
    txn = db.create_transaction({"account_id": acc, "description": "Big spend",
                                 "category": category, "amount": -150.0})

    # Confirm list_budgets() reports us over the limit before running reminders.
    mine = next(b for b in db.list_budgets() if b["category"] == category)
    assert mine["spent"] >= mine["limit"] and mine["limit"] > 0

    # Master on, budget alerts on, every OTHER reminder category off so only the
    # budget block can fire.
    db.update_notification_prefs({
        "master_enabled": True, "budget_alerts": True,
        "appointment_reminders": False, "bill_reminders": False,
        "renewal_reminders": False, "document_expiry_reminders": False,
        "large_transaction_alerts": False,
    })

    try:
        asyncio.run(reminders_svc.run_reminders())
        over = [b for _to, b in calls if category in b and "Over budget" in b]
        assert len(over) == 1, calls                # fired exactly once (one phoned member)

        calls.clear()
        asyncio.run(reminders_svc.run_reminders())
        assert not any(category in b for _to, b in calls)   # deduped on the second run
    finally:
        db.update_user("luke", {"phone": ""})
        db.delete_budget(category)
        db.delete_transaction(txn["id"])
        with db.get_conn() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (acc,))
