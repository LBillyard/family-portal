"""Test fixtures. Point the app at an isolated temp DB BEFORE importing anything
from `server` (database.py reads FAMILY_PORTAL_DB at import time)."""

import os
import tempfile

_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="familyportal-test-"), "test.db")
os.environ["FAMILY_PORTAL_DB"] = _TMP_DB
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only")
# http scheme → session cookie isn't Secure, so TestClient (http://testserver) resends it.
os.environ["PUBLIC_URL"] = "http://testserver"

import pytest  # noqa: E402

from server import database as db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    db.init_db()  # creates schema + seeds two users (family123)
    yield


@pytest.fixture()
def client():
    """A FastAPI TestClient logged in as the seeded user."""
    from fastapi.testclient import TestClient

    from server.main import app

    c = TestClient(app)
    resp = c.post("/api/auth/login", json={"email": "lbillyard@gmail.com", "password": "family123"})
    assert resp.status_code == 200, resp.text
    return c
