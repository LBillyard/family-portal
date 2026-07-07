"""Wave-7 backend: household recipe box (with plan-into-meal-planner), dependents
(children & pets) with cascade-deleting care items, per-dependent care schedule
(+ care_due_within window), and the care-due nudge folded into run_reminders().
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import reminders as reminders_svc
from server.services import whatsapp


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


# --- Recipes: db CRUD -------------------------------------------------------

def test_recipe_crud():
    r = db.create_recipe({"title": "Chilli", "ingredients": "beef, beans, tomato",
                          "method": "simmer", "tags": "dinner", "serves": 4})
    assert r["title"] == "Chilli"
    assert r["ingredients"] == "beef, beans, tomato"
    assert r["serves"] == 4                                   # coerced to int
    assert any(x["id"] == r["id"] for x in db.list_recipes())
    assert db.get_recipe(r["id"])["method"] == "simmer"

    upd = db.update_recipe(r["id"], {"serves": 6, "tags": "dinner,spicy"})
    assert upd["serves"] == 6 and upd["tags"] == "dinner,spicy"
    # clearing serves → NULL
    assert db.update_recipe(r["id"], {"serves": None})["serves"] is None

    assert db.update_recipe("nope-id", {"title": "x"}) is None
    assert db.delete_recipe(r["id"]) is True
    assert db.get_recipe(r["id"]) is None
    assert db.delete_recipe(r["id"]) is False


# --- Recipes: routes + /plan drops a meal onto the planner ------------------

def test_recipe_routes_and_plan(client):
    ing = f"eggs, flour {uuid.uuid4().hex[:5]}"
    title = f"Pancakes {uuid.uuid4().hex[:5]}"
    r = client.post("/api/recipes", json={"title": title, "ingredients": ing, "serves": 2})
    assert r.status_code == 200, r.text
    rid = r.json()["recipe"]["id"]
    assert any(x["id"] == rid for x in client.get("/api/recipes").json()["recipes"])

    assert client.post("/api/recipes", json={"title": "   "}).status_code == 400   # blank title rejected

    assert client.patch(f"/api/recipes/{rid}", json={"method": "flip"}).json()["recipe"]["method"] == "flip"
    assert client.patch("/api/recipes/missing", json={"method": "x"}).status_code == 404

    # --- /plan: recipe title + ingredients carry into the meal for that date ---
    day = "2099-03-14"
    try:
        assert client.post(f"/api/recipes/{rid}/plan", json={"date": "bad"}).status_code == 400  # date validated
        assert client.post("/api/recipes/missing/plan", json={"date": day}).status_code == 404    # unknown recipe

        resp = client.post(f"/api/recipes/{rid}/plan", json={"date": day})
        assert resp.status_code == 200, resp.text
        meal = resp.json()["meal"]
        assert meal["date"] == day and meal["title"] == title

        # verify via db.get_meal_plan
        planned = db.get_meal_plan(day)
        assert planned is not None
        assert planned["title"] == title
        assert planned["ingredients"] == ing                 # ingredients carried over

        # verify via GET /api/meals
        meals = client.get("/api/meals", params={"start": day, "end": day}).json()["meals"]
        assert any(m["title"] == title and m["ingredients"] == ing for m in meals)
    finally:
        db.delete_meal_plan(day)

    assert client.delete(f"/api/recipes/{rid}").json()["ok"] is True
    assert client.delete(f"/api/recipes/{rid}").status_code == 404


# --- Dependents: db CRUD + cascade delete removes care items ----------------

def test_dependent_crud_and_cascade_delete():
    d = db.create_dependent({"name": "Rex", "kind": "pet", "breed": "Labrador", "notes": "good boy"})
    assert d["name"] == "Rex" and d["kind"] == "pet" and d["breed"] == "Labrador"
    assert any(x["id"] == d["id"] for x in db.list_dependents())

    upd = db.update_dependent(d["id"], {"notes": "very good boy"})
    assert upd["notes"] == "very good boy"
    assert db.update_dependent(d["id"], {"breed": None})["breed"] is None   # nullable cleared
    assert db.update_dependent("nope", {"name": "x"}) is None

    # attach care items, then prove delete cascades them away
    c1 = db.create_care_item({"dependent_id": d["id"], "title": "Jab", "due_date": "2030-01-01"})
    c2 = db.create_care_item({"dependent_id": d["id"], "title": "Groom"})
    assert {c1["id"], c2["id"]} <= {x["id"] for x in db.list_care_items(d["id"])}

    assert db.delete_dependent(d["id"]) is True
    assert db.get_dependent(d["id"]) is None
    assert db.get_care_item(c1["id"]) is None                # cascade removed care items
    assert db.get_care_item(c2["id"]) is None
    assert db.delete_dependent(d["id"]) is False


# --- Dependents + care items: routes ---------------------------------------

def test_dependent_and_care_routes(client):
    r = client.post("/api/dependents", json={"name": "Mia", "kind": "child", "dob": "2018-04-01"})
    assert r.status_code == 200, r.text
    did = r.json()["dependent"]["id"]
    assert any(x["id"] == did for x in client.get("/api/dependents").json()["dependents"])
    assert client.post("/api/dependents", json={"name": "  "}).status_code == 400   # name required

    assert client.patch(f"/api/dependents/{did}", json={"notes": "peanut allergy"}).json()["dependent"]["notes"] == "peanut allergy"
    assert client.patch("/api/dependents/missing", json={"notes": "x"}).status_code == 404

    # care item CRUD via routes
    assert client.post("/api/care", json={"title": "Checkup", "dependent_id": ""}).status_code == 400      # blank dependent
    assert client.post("/api/care", json={"title": "Checkup", "dependent_id": "ghost"}).status_code == 400  # unknown dependent
    assert client.post("/api/care", json={"title": "  ", "dependent_id": did}).status_code == 400  # blank title

    cr = client.post("/api/care", json={"title": "MMR jab", "dependent_id": did,
                                        "category": "vaccination", "due_date": "2030-06-01"})
    assert cr.status_code == 200, cr.text
    cid = cr.json()["item"]["id"]
    assert cr.json()["item"]["done"] is False

    # filtered listing by dependent
    listed = client.get("/api/care", params={"dependent_id": did}).json()["items"]
    assert any(x["id"] == cid for x in listed)
    assert all(x["dependent_id"] == did for x in listed)

    assert client.patch(f"/api/care/{cid}", json={"notes": "at GP"}).json()["item"]["notes"] == "at GP"
    assert client.patch("/api/care/missing", json={"notes": "x"}).status_code == 404

    # /done marks it done
    done = client.post(f"/api/care/{cid}/done")
    assert done.status_code == 200 and done.json()["item"]["done"] is True
    assert client.post("/api/care/missing/done").status_code == 404

    assert client.delete(f"/api/care/{cid}").json()["ok"] is True
    assert client.delete(f"/api/care/{cid}").status_code == 404
    assert client.delete(f"/api/dependents/{did}").json()["ok"] is True


# --- care_due_within window correctness ------------------------------------

def test_care_due_within_window():
    d = db.create_dependent({"name": "Buddy", "kind": "pet"})
    near = db.create_care_item({"dependent_id": d["id"], "title": "Near jab",
                                "due_date": (date.today() + timedelta(days=3)).isoformat()})
    far = db.create_care_item({"dependent_id": d["id"], "title": "Far jab",
                               "due_date": (date.today() + timedelta(days=90)).isoformat()})
    done = db.create_care_item({"dependent_id": d["id"], "title": "Done jab",
                                "due_date": (date.today() + timedelta(days=2)).isoformat(),
                                "done": True})
    try:
        within = db.care_due_within(30)
        ids = {x["id"] for x in within}
        assert near["id"] in ids            # 3-day item included
        assert far["id"] not in ids         # 90-day item excluded (outside window)
        assert done["id"] not in ids        # already-done item excluded
    finally:
        db.delete_dependent(d["id"])        # cascades all three care items


# --- reminders integration: a due care item nudges the household once -------

def test_care_due_reminder_fires_once(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900333"})
    db.update_notification_prefs({
        "master_enabled": True, "appointment_reminders": False, "bill_reminders": False,
        "renewal_reminders": False, "document_expiry_reminders": False, "large_transaction_alerts": False,
    })
    marker = f"Rabies {uuid.uuid4().hex[:5]}"
    d = db.create_dependent({"name": "Nudge Pet", "kind": "pet"})
    ci = db.create_care_item({"dependent_id": d["id"], "title": marker,
                              "due_date": date.today().isoformat()})   # due today → inside lead window
    try:
        asyncio.run(reminders_svc.run_reminders())
        assert any(marker in b for _to, b in calls), calls          # care nudge fired
        calls.clear()
        asyncio.run(reminders_svc.run_reminders())
        assert not any(marker in b for _to, b in calls)             # deduped on second run
    finally:
        db.update_user("luke", {"phone": ""})
        db.delete_care_item(ci["id"])
        db.delete_dependent(d["id"])
