"""Wave-3 backend: shopping list, finance insights, net worth + assets, large-txn alerts.

Service-level tests drive the code directly; route tests use the shared authenticated
`client` fixture from conftest. Reminders are exercised with whatsapp.send_text
monkeypatched to record (phone, body) instead of sending.
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import assistant as assistant_svc
from server.services import insights as insights_svc
from server.services import networth as networth_svc
from server.services import reminders as reminders_svc
from server.services import whatsapp


# --- helpers ---------------------------------------------------------------

def _ensure_account(name: str, acc_type: str, balance: float) -> str:
    """Create an account directly (no public create_account helper) and return its id."""
    aid = f"acc-{uuid.uuid4().hex[:8]}"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, name, acc_type, balance, "Test Bank"),
        )
    return aid


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


# --- shopping list ---------------------------------------------------------

def test_shopping_crud_orders_and_clears():
    before = {i["id"] for i in db.list_shopping_items()}
    a = db.create_shopping_item("  milk  ", "luke")
    b = db.create_shopping_item("bread", "partner")
    assert a["text"] == "milk"          # trimmed
    assert a["done"] is False
    assert a["added_by"] == "luke"

    # Mark the first done → it must sort AFTER the still-open one.
    db.set_shopping_item_done(a["id"], True)
    ours = [i for i in db.list_shopping_items() if i["id"] in {a["id"], b["id"]}]
    assert [i["id"] for i in ours] == [b["id"], a["id"]]
    assert next(i for i in ours if i["id"] == a["id"])["done"] is True

    # clear-done removes only the done one.
    cleared = db.clear_done_shopping_items()
    assert cleared >= 1
    ids = {i["id"] for i in db.list_shopping_items()}
    assert a["id"] not in ids and b["id"] in ids

    assert db.delete_shopping_item(b["id"]) is True
    assert db.delete_shopping_item(b["id"]) is False


def test_shopping_routes(client):
    r = client.post("/api/shopping", json={"text": "nappies"})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["text"] == "nappies" and item["added_by"] == "luke"

    assert any(i["id"] == item["id"] for i in client.get("/api/shopping").json()["items"])

    patched = client.patch(f"/api/shopping/{item['id']}", json={"done": True})
    assert patched.status_code == 200 and patched.json()["item"]["done"] is True

    cleared = client.post("/api/shopping/clear-done")
    assert cleared.status_code == 200 and cleared.json()["cleared"] >= 1

    # blank text rejected
    assert client.post("/api/shopping", json={"text": "   "}).status_code == 400
    # missing item 404s
    assert client.patch("/api/shopping/nope", json={"done": True}).status_code == 404


def test_assistant_add_shopping_item_tool():
    user = db.get_user("luke")
    out = asyncio.run(
        assistant_svc.execute_tool("add_shopping_item", {"items": ["eggs", "  ", "butter"]}, user)
    )
    assert out["ok"] is True
    assert out["added"] == ["eggs", "butter"]     # blank entry filtered
    texts = {i["text"] for i in db.list_shopping_items()}
    assert {"eggs", "butter"} <= texts
    # tolerates a bare string too
    out2 = asyncio.run(assistant_svc.execute_tool("add_shopping_item", {"text": "cheese"}, user))
    assert out2["added"] == ["cheese"]


# --- assets + net worth ----------------------------------------------------

def test_networth_math():
    # Snapshot the baseline so the shared session DB doesn't skew the assertions.
    base = networth_svc.build_networth()

    cash_id = _ensure_account("W3 Current", "current", 5000.0)
    credit_id = _ensure_account("W3 Credit Card", "credit", 1200.0)  # a debt
    asset = db.create_asset({"name": "W3 House", "type": "property", "value": 250000.0})

    nw = networth_svc.build_networth()
    assert round(nw["cash_total"] - base["cash_total"], 2) == 5000.0
    assert round(nw["liabilities_total"] - base["liabilities_total"], 2) == 1200.0
    assert round(nw["assets_total"] - base["assets_total"], 2) == 250000.0
    # net = cash + assets - liabilities
    assert round(nw["net_worth"] - base["net_worth"], 2) == round(5000 + 250000 - 1200, 2)

    labels = {b["label"] for b in nw["breakdown"]}
    assert {"W3 Current", "W3 Credit Card", "W3 House"} <= labels

    # cleanup so repeat runs stay clean
    db.delete_asset(asset["id"])
    with db.get_conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id IN (?, ?)", (cash_id, credit_id))


def test_assets_routes(client):
    r = client.post("/api/assets", json={"name": "Lotus", "type": "vehicle", "value": 45000, "notes": "X444 LES"})
    assert r.status_code == 200, r.text
    asset = r.json()["asset"]
    assert asset["name"] == "Lotus" and asset["value"] == 45000

    assert any(a["id"] == asset["id"] for a in client.get("/api/assets").json()["assets"])

    patched = client.patch(f"/api/assets/{asset['id']}", json={"value": 47000})
    assert patched.status_code == 200 and patched.json()["asset"]["value"] == 47000
    assert patched.json()["asset"]["name"] == "Lotus"   # unspecified field preserved

    assert client.get("/api/finances/networth").status_code == 200
    assert client.delete(f"/api/assets/{asset['id']}").json()["ok"] is True
    assert client.patch(f"/api/assets/{asset['id']}", json={"value": 1}).status_code == 404


# --- insights --------------------------------------------------------------

def test_insights_this_vs_last_month(monkeypatch):
    # build_insights now anchors to the CURRENT CALENDAR month (today's clock). Freeze
    # insights' clock to a fixed far-future month so the seed data is isolated from the
    # shared session DB (no other test writes txns in 2099) and the assertions stay
    # deterministic.
    this_m = "2099-08"
    last_m = "2099-07"

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2099, 8, 15)

    monkeypatch.setattr(insights_svc.datetime, "date", _FixedDate)

    acc = _ensure_account("W3 Insights", "current", 0.0)
    db.create_transaction({"account_id": acc, "description": "Groceries A", "category": "Groceries",
                           "amount": -100.0, "date": f"{last_m}-10"})
    db.create_transaction({"account_id": acc, "description": "Big TV", "category": "Shopping",
                           "amount": -400.0, "date": f"{this_m}-05"})
    db.create_transaction({"account_id": acc, "description": "Groceries B", "category": "Groceries",
                           "amount": -50.0, "date": f"{this_m}-06"})
    db.create_transaction({"account_id": acc, "description": "Salary", "category": "Income",
                           "amount": 3000.0, "date": f"{this_m}-01"})

    ins = insights_svc.build_insights()
    assert ins["has_data"] is True
    assert ins["this_month"]["label"] == "Aug 2099"
    assert ins["this_month"]["spend"] == 450.0        # 400 + 50
    # The "Income" category IS income — it's excluded from SPEND but kept for the income
    # figure (matches finance_summary); only Transfers/Savings/Crypto are dropped from income.
    assert ins["this_month"]["income"] == 3000.0
    assert ins["last_month"]["spend"] == 100.0
    # 450 vs 100 → +350%
    assert ins["spend_delta_pct"] == 350.0
    # biggest single expense this month
    assert ins["biggest_expense"]["amount"] == 400.0
    assert "TV" in ins["biggest_expense"]["description"]
    # top category this month = Shopping (400) ahead of Groceries (50)
    assert ins["top_categories"][0]["category"] == "Shopping"
    assert ins["top_categories"][0]["amount"] == 400.0

    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE account_id = ?", (acc,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (acc,))


def test_insights_route(client):
    r = client.get("/api/finances/insights")
    assert r.status_code == 200
    body = r.json()
    assert "has_data" in body and "subscriptions" in body


# --- large-transaction alerts ---------------------------------------------

def test_large_transaction_alert_fires_once(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900123"})
    # Only large-txn alerts on, so nothing else in the shared DB contributes sends.
    db.update_notification_prefs({
        "master_enabled": True,
        "appointment_reminders": False,
        "bill_reminders": False,
        "renewal_reminders": False,
        "document_expiry_reminders": False,
        "large_transaction_alerts": True,
        "large_transaction_threshold": 200,
    })
    acc = _ensure_account("W3 LargeTxn", "current", 0.0)
    marker = f"BigBuy-{uuid.uuid4().hex[:6]}"
    db.create_transaction({"account_id": acc, "description": marker, "category": "Shopping",
                           "amount": -750.0, "date": date.today().isoformat()})
    # A sub-threshold and an old txn must NOT alert.
    db.create_transaction({"account_id": acc, "description": "Small", "category": "Shopping",
                           "amount": -20.0, "date": date.today().isoformat()})
    db.create_transaction({"account_id": acc, "description": "OldBig", "category": "Shopping",
                           "amount": -900.0, "date": (date.today() - timedelta(days=30)).isoformat()})

    asyncio.run(reminders_svc.run_reminders())
    hits = [b for _p, b in calls if marker in b]
    assert len(hits) == 1, calls
    assert "750" in hits[0]
    assert not any("Small" in b or "OldBig" in b for _p, b in calls)

    # Second run dedupes — no new message for the same txn.
    calls.clear()
    asyncio.run(reminders_svc.run_reminders())
    assert not any(marker in b for _p, b in calls)

    db.update_user("luke", {"phone": ""})
    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE account_id = ?", (acc,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (acc,))


def test_prefs_large_txn_roundtrip(client):
    r = client.patch("/api/notifications/prefs",
                     json={"large_transaction_alerts": True, "large_transaction_threshold": 500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["large_transaction_alerts"] is True
    assert body["large_transaction_threshold"] == 500
    got = client.get("/api/notifications/prefs").json()
    assert got["large_transaction_threshold"] == 500
