"""Family-data export — a single downloadable JSON the family can keep.

SECURITY IS CRITICAL. This module is WHITELIST-ONLY:

* Only tables listed in ``SAFE_TABLES`` are ever queried. Anything not on the
  list (bank_connections, google_accounts, push_subscriptions, settings,
  sent_notifications, activity_log, merchant_rules, pending_actions, receipts,
  trip_documents, maintenance_items, notification_log, and anything else
  holding tokens/keys) is simply never touched.
* The ``users`` table is NEVER ``SELECT *``-ed. We pick a small explicit set of
  safe columns (never ``password_hash``, never ``google_token_json``).
* As a belt-and-braces net, every row is passed through a redactor that drops
  any key whose name looks like a credential/secret.

Nothing here reads file bytes — document/media rows keep their metadata (paths
etc.) but the files themselves are not opened.
"""

import re

from server import database as db

# --- Whitelist of safe family-data tables (NEVER a blacklist) ---------------
# Only these are exported. Missing ones are skipped so the export never errors.
SAFE_TABLES = [
    "events",
    "transactions",
    "accounts",
    "bills",
    "budgets",
    "savings_goals",
    "tasks",
    "appointments",
    "holiday_trips",
    "holiday_checklist",
    "itinerary_items",
    "documents",
    "media_items",
    "memory_facts",
    "occasions",
    "dependents",
    "care_items",
    "vehicles",
    "recipes",
    "meal_plans",
    "shopping_items",
    "chores",
    "wishlist_items",
    "inventory_items",
    "tradespeople",
    "subscriptions",
    "notification_prefs",
]

# The users table is special: NEVER "SELECT *". Only these safe columns, and
# only the ones that actually exist in the schema (so it can't error, and a
# non-existent column like ``phone`` is simply omitted).
USER_SAFE_COLUMNS = ["id", "name", "email", "colour", "phone"]

# Belt-and-braces: drop any row key that looks like a credential/secret, even
# if it somehow slipped through the whitelist above.
_SECRET_KEY_RE = re.compile(
    r"(password|token|secret|api_key|refresh|access_key|p256dh|auth_key)",
    re.IGNORECASE,
)

# Internal/derived columns that are useless to a human and would bloat the file
# (e.g. the RAG embedding vector — a long array of floats). Dropped from export.
_SKIP_COLUMNS = {"embedding"}


def _redact_row(row: dict) -> dict:
    """Drop credential/secret keys and internal/derived columns."""
    return {
        k: v for k, v in row.items()
        if k not in _SKIP_COLUMNS and not _SECRET_KEY_RE.search(k)
    }


def _existing_tables(conn) -> set:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r["name"] for r in rows}


def _table_columns(conn, table: str) -> list:
    # ``table`` is always a hardcoded literal here, so no injection surface.
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]


def _read_table(conn, table: str) -> list:
    # ``table`` comes only from the hardcoded SAFE_TABLES whitelist.
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [_redact_row(dict(r)) for r in rows]


def _read_users(conn) -> list:
    """Read ONLY the safe user columns that actually exist (never secrets)."""
    have = set(_table_columns(conn, "users"))
    cols = [c for c in USER_SAFE_COLUMNS if c in have]
    if not cols:
        return []
    col_sql = ", ".join(cols)  # cols are from a fixed allowlist, not user input
    rows = conn.execute(f"SELECT {col_sql} FROM users").fetchall()
    return [_redact_row(dict(r)) for r in rows]


def build_export(exported_at=None) -> dict:
    """Build the whole export as a plain dict.

    Returns ``{"exported_at"?, "app", "tables": {name: [rows]}, "counts": {...}}``.
    ``exported_at`` is included only when passed in (the route stamps it); this
    function does no time lookups of its own.
    """
    tables: dict = {}
    with db.get_conn() as conn:
        present = _existing_tables(conn)

        # Safe subset of the users table (explicit columns — never a secret).
        if "users" in present:
            try:
                tables["users"] = _read_users(conn)
            except Exception:
                # Never let one bad table break the whole export.
                tables["users"] = []

        for table in SAFE_TABLES:
            if table not in present:
                continue  # skip missing tables so we never error
            try:
                tables[table] = _read_table(conn, table)
            except Exception:
                tables[table] = []

    payload: dict = {}
    if exported_at is not None:
        payload["exported_at"] = exported_at
    payload["app"] = "The Hub"
    payload["tables"] = tables
    payload["counts"] = {name: len(rows) for name, rows in tables.items()}
    return payload
