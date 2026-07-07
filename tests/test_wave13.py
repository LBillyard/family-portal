"""Wave-13 backend: family-data export (GET /api/export) + services/export_data.

The export is a single downloadable JSON the family can keep. It is WHITELIST-ONLY
and MUST NEVER leak credentials:

- GET /api/export -> 200, Content-Type application/json, Content-Disposition
  attachment with a .json filename, and a body that parses to the documented
  shape (``app`` / ``tables`` / ``counts`` / ``exported_at``).
- SECURITY: the raw response never contains 'password_hash'; secret-holding
  tables (bank_connections, google_accounts, push_subscriptions, settings) are
  never exported; and NO row anywhere carries a key that looks like a
  credential (password/token/secret/api_key/refresh).
- export_data.build_export() returns the documented shape and never raises.

The seed user (conftest) is already in the DB, so the ``users`` table is a real,
populated table we can prove is scrubbed of its password_hash.
"""

import json
import re

from server.services import export_data

# Tables that hold tokens / keys / hashes and must NEVER appear in the export.
_FORBIDDEN_TABLES = [
    "bank_connections",
    "google_accounts",
    "push_subscriptions",
    "settings",
    "sent_notifications",
    "merchant_rules",
    "google_token_json",  # not a table, but must never surface as one either
]

# A key on ANY row that matches this is a leak.
_SECRET_KEY_RE = re.compile(
    r"(password|token|secret|api_key|refresh)",
    re.IGNORECASE,
)

# A few safe family-data tables we expect the export to always carry.
_EXPECTED_SAFE_TABLES = ["accounts", "tasks", "notification_prefs"]


# --- helpers ---------------------------------------------------------------

def _walk_keys(node):
    """Yield every dict key anywhere in a nested dict/list structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def _all_rows(tables: dict):
    """Yield every row dict across every exported table."""
    for rows in tables.values():
        assert isinstance(rows, list)
        for row in rows:
            yield row


# --- service level: build_export() -----------------------------------------

def test_build_export_shape_without_timestamp():
    """No exported_at when none is passed; app/tables/counts always present."""
    ex = export_data.build_export()
    assert isinstance(ex, dict)
    assert "exported_at" not in ex  # the function does no time lookups itself
    assert ex["app"] == "The Hub"
    assert isinstance(ex["tables"], dict) and ex["tables"]
    assert isinstance(ex["counts"], dict)
    # counts mirrors tables exactly (one count per table = number of rows).
    assert set(ex["counts"].keys()) == set(ex["tables"].keys())
    for name, rows in ex["tables"].items():
        assert ex["counts"][name] == len(rows), name


def test_build_export_stamps_supplied_timestamp():
    stamp = "2026-07-07T00:00:00+00:00"
    ex = export_data.build_export(exported_at=stamp)
    assert ex["exported_at"] == stamp
    assert ex["app"] == "The Hub"
    assert isinstance(ex["tables"], dict)


def test_build_export_is_deterministic_and_never_raises():
    # Two back-to-back calls agree on structure (no time lookups of its own).
    a = export_data.build_export()
    b = export_data.build_export()
    assert set(a["tables"].keys()) == set(b["tables"].keys())
    assert a["counts"] == b["counts"]


def test_build_export_carries_known_safe_tables():
    ex = export_data.build_export()
    for t in _EXPECTED_SAFE_TABLES:
        assert t in ex["tables"], f"expected safe table {t!r} missing"
    # The safe user subset is included as its own table too.
    assert "users" in ex["tables"]


def test_build_export_excludes_forbidden_tables():
    ex = export_data.build_export()
    for t in _FORBIDDEN_TABLES:
        assert t not in ex["tables"], f"forbidden table {t!r} leaked into export"


def test_build_export_only_whitelisted_tables():
    """Every table in the export is either 'users' or on the SAFE_TABLES list."""
    ex = export_data.build_export()
    allowed = set(export_data.SAFE_TABLES) | {"users"}
    assert set(ex["tables"].keys()) <= allowed, set(ex["tables"].keys()) - allowed


def test_build_export_no_secret_keys_anywhere():
    ex = export_data.build_export()
    for key in _walk_keys(ex["tables"]):
        assert not _SECRET_KEY_RE.search(key), f"secret-looking key exported: {key!r}"


def test_build_export_users_are_scrubbed():
    """The seed users are present but stripped of password_hash / any secret."""
    ex = export_data.build_export()
    users = ex["tables"]["users"]
    assert isinstance(users, list) and len(users) >= 1, "seed user should be present"
    for row in users:
        assert "password_hash" not in row
        assert "google_token_json" not in row
        for k in row:
            assert not _SECRET_KEY_RE.search(k), f"secret key on user row: {k!r}"
    # The safe columns we DO expect to be there.
    assert any("email" in row for row in users)


# --- route level: GET /api/export ------------------------------------------

def test_export_route_headers(client):
    r = client.get("/api/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd.lower(), cd
    assert ".json" in cd.lower(), cd


def test_export_route_body_parses_to_documented_shape(client):
    r = client.get("/api/export")
    assert r.status_code == 200, r.text
    ex = json.loads(r.text)  # must be valid JSON
    assert ex["app"] == "The Hub"
    assert "exported_at" in ex and isinstance(ex["exported_at"], str) and ex["exported_at"]
    assert isinstance(ex["tables"], dict) and ex["tables"]
    assert isinstance(ex["counts"], dict)
    # A few known-safe tables are present.
    for t in _EXPECTED_SAFE_TABLES:
        assert t in ex["tables"], t


def test_export_route_raw_text_has_no_password_hash(client):
    r = client.get("/api/export")
    assert r.status_code == 200, r.text
    # The most important guarantee: the hash string never appears in the bytes.
    assert "password_hash" not in r.text
    assert "google_token_json" not in r.text


def test_export_route_omits_secret_tables(client):
    r = client.get("/api/export")
    ex = r.json()
    for t in ("bank_connections", "google_accounts", "push_subscriptions", "settings"):
        assert t not in ex["tables"], f"{t} must not be exported"


def test_export_route_no_secret_key_on_any_row(client):
    r = client.get("/api/export")
    ex = r.json()
    for row in _all_rows(ex["tables"]):
        for k in row:
            assert not _SECRET_KEY_RE.search(k), f"secret-looking key in export: {k!r}"


def test_export_route_users_rows_have_no_password_hash(client):
    r = client.get("/api/export")
    ex = r.json()
    users = ex["tables"].get("users", [])
    assert len(users) >= 1, "seed user should be exported"
    for row in users:
        assert "password_hash" not in row


def test_export_requires_auth():
    """Unauthenticated callers cannot pull the family export."""
    from fastapi.testclient import TestClient

    from server.main import app

    anon = TestClient(app)
    r = anon.get("/api/export")
    assert r.status_code in (401, 403), r.status_code
