"""Budget targets and savings goals CRUD."""


def test_budget_crud(client):
    # create
    r = client.post("/api/budgets", json={"category": "Groceries", "monthly_limit": 400})
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "Groceries"
    assert r.json()["limit"] == 400
    assert "spent" in r.json()

    # appears in /finances
    budgets = client.get("/api/finances").json()["budgets"]
    assert any(b["category"] == "Groceries" and b["limit"] == 400 for b in budgets)

    # creating the same category again replaces the limit (category is unique)
    r = client.post("/api/budgets", json={"category": "Groceries", "monthly_limit": 500})
    assert r.status_code == 200
    assert r.json()["limit"] == 500

    # update
    r = client.patch("/api/budgets/Groceries", json={"monthly_limit": 350})
    assert r.status_code == 200
    assert r.json()["limit"] == 350

    # update missing -> 404
    assert client.patch("/api/budgets/Nonexistent", json={"monthly_limit": 10}).status_code == 404

    # zero/negative limit rejected
    assert client.post("/api/budgets", json={"category": "Transport", "monthly_limit": 0}).status_code == 422

    # delete
    assert client.delete("/api/budgets/Groceries").status_code == 200
    assert client.delete("/api/budgets/Groceries").status_code == 404
    budgets = client.get("/api/finances").json()["budgets"]
    assert not any(b["category"] == "Groceries" for b in budgets)


def test_savings_goal_crud(client):
    r = client.post("/api/savings-goals", json={"name": "New car", "target": 8000, "current": 1500})
    assert r.status_code == 200, r.text
    gid = r.json()["id"]
    assert r.json()["name"] == "New car"
    assert r.json()["current"] == 1500
    assert r.json()["colour"] == "#00a89e"  # default

    goals = client.get("/api/finances").json()["savings_goals"]
    assert any(g["id"] == gid for g in goals)

    # update current + colour
    r = client.patch(f"/api/savings-goals/{gid}", json={"current": 2000, "colour": "#2563eb"})
    assert r.status_code == 200
    assert r.json()["current"] == 2000
    assert r.json()["colour"] == "#2563eb"

    # bad colour rejected
    assert client.patch(f"/api/savings-goals/{gid}", json={"colour": "blue"}).status_code == 422
    # zero target rejected on create
    assert client.post("/api/savings-goals", json={"name": "x", "target": 0}).status_code == 422
    # update missing -> 404
    assert client.patch("/api/savings-goals/ghost", json={"current": 1}).status_code == 404

    # delete
    assert client.delete(f"/api/savings-goals/{gid}").status_code == 200
    assert client.delete(f"/api/savings-goals/{gid}").status_code == 404


def test_budget_requires_auth(client):
    client.post("/api/auth/logout")
    assert client.post("/api/budgets", json={"category": "Groceries", "monthly_limit": 400}).status_code == 401
    assert client.post("/api/savings-goals", json={"name": "x", "target": 100}).status_code == 401
