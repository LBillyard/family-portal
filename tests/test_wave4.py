"""Wave-4 backend: meal planner (+ shopping integration), weekly finance recap,
plan_meal assistant tool, and the weekly_finance_summary pref.

Service/DB tests run directly; route tests use the shared authenticated `client`.
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import assistant as assistant_svc
from server.services import weekly_finance as weekly_finance_svc


def _ensure_account(name: str, acc_type: str, balance: float) -> str:
    aid = f"acc-{uuid.uuid4().hex[:8]}"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, name, acc_type, balance, "Test Bank"),
        )
    return aid


# --- meal planner DB ------------------------------------------------------

def test_meal_upsert_is_date_stable_and_lists_range():
    d = "2099-03-10"
    m1 = db.upsert_meal_plan(d, "  Spaghetti  ", "mince, pasta, tomatoes")
    assert m1["title"] == "Spaghetti"          # trimmed
    m2 = db.upsert_meal_plan(d, "Lasagne", "mince, pasta")
    assert m2["id"] == m1["id"]                 # same date reuses the row
    assert m2["title"] == "Lasagne"
    assert db.get_meal_plan(d)["title"] == "Lasagne"

    week = db.list_meal_plans("2099-03-09", "2099-03-15")
    assert [m["date"] for m in week] == [d]
    # out-of-range excluded
    assert db.list_meal_plans("2099-04-01", "2099-04-07") == []

    assert db.delete_meal_plan(d) is True
    assert db.delete_meal_plan(d) is False


# --- meal planner routes --------------------------------------------------

def test_meal_routes_and_to_shopping(client):
    d = "2099-05-20"
    r = client.put("/api/meals", json={"date": d, "title": "Fajitas", "ingredients": "peppers, chicken\nwraps"})
    assert r.status_code == 200, r.text
    assert r.json()["meal"]["title"] == "Fajitas"

    got = client.get("/api/meals", params={"start": "2099-05-18", "end": "2099-05-24"}).json()
    assert any(m["date"] == d for m in got["meals"])

    # blank title rejected; bad date rejected
    assert client.put("/api/meals", json={"date": d, "title": "  "}).status_code == 400
    assert client.put("/api/meals", json={"date": "nope", "title": "x"}).status_code == 400

    # push the meal's ingredients onto the shopping list (comma + newline split)
    added = client.post(f"/api/meals/{d}/to-shopping")
    assert added.status_code == 200, added.text
    assert set(added.json()["added"]) == {"peppers", "chicken", "wraps"}
    texts = {i["text"] for i in db.list_shopping_items()}
    assert {"peppers", "chicken", "wraps"} <= texts

    # to-shopping on a missing day 404s
    assert client.post("/api/meals/2099-01-01/to-shopping").status_code == 404

    assert client.delete(f"/api/meals/{d}").json()["ok"] is True
    assert client.delete(f"/api/meals/{d}").status_code == 404


def test_meals_default_to_current_week(client):
    # No params → current Mon..Sun. Plant a meal on today and expect it back.
    today = date.today().isoformat()
    client.put("/api/meals", json={"date": today, "title": "Weeknight curry"})
    body = client.get("/api/meals").json()
    assert body["start"] <= today <= body["end"]
    assert any(m["date"] == today for m in body["meals"])
    client.delete(f"/api/meals/{today}")


# --- assistant plan_meal tool ---------------------------------------------

def test_assistant_plan_meal_tool():
    user = db.get_user("luke")
    d = "2099-06-05"
    out = asyncio.run(
        assistant_svc.execute_tool(
            "plan_meal", {"date": d, "title": "Roast chicken", "ingredients": "chicken, potatoes"}, user
        )
    )
    assert out["ok"] is True
    assert out["meal"]["title"] == "Roast chicken"
    assert db.get_meal_plan(d)["title"] == "Roast chicken"
    db.delete_meal_plan(d)


# --- weekly finance recap --------------------------------------------------

def test_weekly_summary_builds_and_never_raises():
    # Seed a spend in the current week so the recap has real content.
    acc = _ensure_account("W4 Weekly", "current", 0.0)
    db.create_transaction({"account_id": acc, "description": "Weekly shop", "category": "Groceries",
                           "amount": -75.0, "date": date.today().isoformat()})
    text = weekly_finance_svc.build_weekly_summary()
    assert isinstance(text, str) and text.strip()
    assert "week in money" in text.lower() or "week" in text.lower()
    # money is GBP-formatted
    assert "£" in text
    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE account_id = ?", (acc,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (acc,))


def test_weekly_pref_roundtrip(client):
    r = client.patch("/api/notifications/prefs", json={"weekly_finance_summary": False})
    assert r.status_code == 200, r.text
    assert r.json()["weekly_finance_summary"] is False
    r2 = client.patch("/api/notifications/prefs", json={"weekly_finance_summary": True})
    assert r2.json()["weekly_finance_summary"] is True
    assert client.get("/api/notifications/prefs").json()["weekly_finance_summary"] is True
