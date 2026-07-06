"""API smoke tests via FastAPI TestClient (authenticated where needed)."""

from fastapi.testclient import TestClient

from server.main import app


def test_requires_auth():
    c = TestClient(app)
    assert c.get("/api/settings").status_code == 401
    assert c.get("/api/finances").status_code == 401


def test_login_rejects_bad_password():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "lbillyard@gmail.com", "password": "wrong"})
    assert r.status_code == 401


def test_settings_shape(client):
    data = client.get("/api/settings").json()
    assert "sync" in data and "integrations" in data
    assert set(["google_last", "banking_last", "last_sync"]).issubset(data["sync"].keys())
    # weather is a known integration key after the rebuild
    assert "weather" in data["integrations"]


def test_settings_sync_filters_non_iso(client):
    from server import database as db

    db.set_setting("banking_last_sync", "just now")  # legacy junk
    db.set_setting("google_last_sync", "2026-07-06T10:00:00+00:00")  # valid ISO
    sync = client.get("/api/settings").json()["sync"]
    assert sync["banking_last"] is None  # junk dropped
    assert sync["google_last"] == "2026-07-06T10:00:00+00:00"
    assert sync["last_sync"] == "2026-07-06T10:00:00+00:00"


def test_weather_endpoint_returns_configured_flag(client):
    data = client.get("/api/weather").json()
    assert "configured" in data


def test_csv_export_downloadable(client):
    r = client.get("/api/finances/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "Date,Description,Category,Account,Amount" in r.text.splitlines()[0]
