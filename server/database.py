"""SQLite persistence for Family Portal."""

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("FAMILY_PORTAL_DB") or (Path(__file__).parent.parent / "data" / "family.db"))

logger = logging.getLogger(__name__)


# --- Encryption at rest for OAuth/bank tokens (key derived from SECRET_KEY) ---

_ENC_PREFIX = "enc:"


def _fernet():
    from cryptography.fernet import Fernet

    secret = os.environ.get("SECRET_KEY", "dev-change-me-in-production").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _enc(value: Optional[str]) -> Optional[str]:
    """Encrypt a secret before storing. None/empty pass through unchanged."""
    if not value:
        return value
    return _ENC_PREFIX + _fernet().encrypt(value.encode()).decode()


def _dec(value: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret. Legacy plaintext (no prefix) is returned as-is."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        return None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                colour TEXT NOT NULL DEFAULT '#00a89e',
                google_token_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'current',
                balance REAL NOT NULL DEFAULT 0,
                institution TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT,
                all_day INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'portal',
                location TEXT,
                google_event_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS bills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                due_day INTEGER NOT NULL,
                recurrence TEXT NOT NULL DEFAULT 'monthly',
                category TEXT NOT NULL DEFAULT 'Other',
                paid INTEGER NOT NULL DEFAULT 0,
                paid_at TEXT
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                txn_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL UNIQUE,
                monthly_limit REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS savings_goals (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                target REAL NOT NULL,
                current REAL NOT NULL DEFAULT 0,
                colour TEXT NOT NULL DEFAULT '#00a89e'
            );

            -- Long-term family memory (RAG). Each fact carries an embedding (JSON
            -- array) so the assistant can semantically retrieve what's relevant.
            CREATE TABLE IF NOT EXISTS memory_facts (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'preferences',
                subject TEXT NOT NULL DEFAULT 'family',
                source TEXT NOT NULL DEFAULT 'manual',
                pinned INTEGER NOT NULL DEFAULT 0,
                embedding TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                assignee_id TEXT,
                due_date TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'medium',
                created_at TEXT NOT NULL,
                FOREIGN KEY (assignee_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                datetime TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'upcoming',
                category TEXT NOT NULL DEFAULT 'health',
                location TEXT,
                reminder_days INTEGER NOT NULL DEFAULT 2,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS holiday_trips (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idea',
                start_date TEXT,
                end_date TEXT,
                budget REAL NOT NULL DEFAULT 0,
                spent REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS holiday_checklist (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL,
                label TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (trip_id) REFERENCES holiday_trips(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS holiday_ideas (
                id TEXT PRIMARY KEY,
                destination TEXT NOT NULL,
                summary TEXT NOT NULL,
                budget_estimate REAL NOT NULL DEFAULT 0,
                saved INTEGER NOT NULL DEFAULT 0,
                tags_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                expiry TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok',
                notes TEXT NOT NULL DEFAULT '',
                file_name TEXT,
                file_path TEXT,
                mime_type TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT,
                user_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bank_connections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                token_expires_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                connected_at TEXT NOT NULL,
                last_synced_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS media_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                caption TEXT NOT NULL DEFAULT '',
                media_type TEXT NOT NULL,
                trip_id TEXT,
                file_name TEXT,
                file_path TEXT,
                mime_type TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                taken_at TEXT,
                uploaded_at TEXT NOT NULL,
                user_id TEXT,
                source TEXT NOT NULL DEFAULT 'upload',
                FOREIGN KEY (trip_id) REFERENCES holiday_trips(id) ON DELETE SET NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                merchant_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                amount REAL NOT NULL,
                frequency TEXT NOT NULL DEFAULT 'monthly',
                status TEXT NOT NULL DEFAULT 'detected',
                category TEXT NOT NULL DEFAULT 'Subscriptions',
                last_charge_date TEXT,
                next_expected_date TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                account TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            -- Household-level notification/digest preferences (a single row).
            CREATE TABLE IF NOT EXISTS notification_prefs (
                id TEXT PRIMARY KEY,
                master_enabled INTEGER NOT NULL DEFAULT 1,
                morning_digest INTEGER NOT NULL DEFAULT 1,
                evening_digest INTEGER NOT NULL DEFAULT 0,
                appointment_reminders INTEGER NOT NULL DEFAULT 1,
                bill_reminders INTEGER NOT NULL DEFAULT 1,
                renewal_reminders INTEGER NOT NULL DEFAULT 1,
                document_expiry_reminders INTEGER NOT NULL DEFAULT 1,
                reminder_lead_days INTEGER NOT NULL DEFAULT 2,
                large_transaction_alerts INTEGER NOT NULL DEFAULT 1,
                large_transaction_threshold INTEGER NOT NULL DEFAULT 200,
                weekly_finance_summary INTEGER NOT NULL DEFAULT 1,
                budget_alerts INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT
            );

            -- Dedupe ledger so any given reminder is only ever sent once.
            CREATE TABLE IF NOT EXISTS sent_notifications (
                key TEXT PRIMARY KEY,
                sent_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tradespeople (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trade TEXT,
                phone TEXT,
                email TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Browser/PWA Web Push subscriptions (one row per push endpoint).
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            -- Shared household shopping list.
            CREATE TABLE IF NOT EXISTS shopping_items (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                added_by TEXT,
                created_at TEXT NOT NULL
            );

            -- Household assets (for net worth).
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'other',
                value REAL NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Weekly dinner planner: one planned dinner per calendar day.
            CREATE TABLE IF NOT EXISTS meal_plans (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                ingredients TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Net worth trend history: one snapshot per calendar day so the
            -- finance page can chart how net worth moves over time.
            CREATE TABLE IF NOT EXISTS networth_snapshots (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL UNIQUE,
                net_worth REAL NOT NULL,
                cash_total REAL NOT NULL,
                assets_total REAL NOT NULL,
                liabilities_total REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            -- Recurring rotating household chores.
            CREATE TABLE IF NOT EXISTS chores (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                cadence TEXT NOT NULL DEFAULT 'weekly',
                assignee_id TEXT,
                rotate INTEGER NOT NULL DEFAULT 1,
                next_due TEXT,
                last_done TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Birthdays / anniversaries that recur annually on their month/day.
            CREATE TABLE IF NOT EXISTS occasions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'birthday',
                date TEXT NOT NULL,
                person TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Home inventory / warranty tracker.
            CREATE TABLE IF NOT EXISTS inventory_items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                brand TEXT,
                model TEXT,
                serial TEXT,
                purchase_date TEXT,
                price REAL,
                warranty_expiry TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Recipe box: free-text ingredients/method, comma-tagged.
            CREATE TABLE IF NOT EXISTS recipes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                ingredients TEXT NOT NULL DEFAULT '',
                method TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                serves INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Dependents: children & pets tracked by the household.
            CREATE TABLE IF NOT EXISTS dependents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'child',
                dob TEXT,
                breed TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Care items for a dependent (vaccinations, checkups, milestones...).
            CREATE TABLE IF NOT EXISTS care_items (
                id TEXT PRIMARY KEY,
                dependent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                due_date TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Gift ideas / wishlist, optionally tagged to a person.
            CREATE TABLE IF NOT EXISTS wishlist_items (
                id TEXT PRIMARY KEY,
                person TEXT,
                title TEXT NOT NULL,
                url TEXT,
                price REAL,
                notes TEXT NOT NULL DEFAULT '',
                purchased INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Household vehicles with MOT/tax/insurance/service due dates.
            CREATE TABLE IF NOT EXISTS vehicles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                reg TEXT,
                make TEXT,
                model TEXT,
                mot_due TEXT,
                tax_due TEXT,
                insurance_due TEXT,
                service_due TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Day-by-day itinerary entries for a holiday trip.
            CREATE TABLE IF NOT EXISTS itinerary_items (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL,
                day_date TEXT,
                start_time TEXT,
                kind TEXT NOT NULL DEFAULT 'activity',
                title TEXT NOT NULL,
                location TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        _migrate(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row["c"] == 0:
            _seed(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns/tables for existing databases."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    for col, ddl in [
        ("connection_id", "ALTER TABLE accounts ADD COLUMN connection_id TEXT"),
        ("external_id", "ALTER TABLE accounts ADD COLUMN external_id TEXT"),
        ("linked", "ALTER TABLE accounts ADD COLUMN linked INTEGER NOT NULL DEFAULT 0"),
        ("last_synced_at", "ALTER TABLE accounts ADD COLUMN last_synced_at TEXT"),
        ("name_custom", "ALTER TABLE accounts ADD COLUMN name_custom INTEGER NOT NULL DEFAULT 0"),
        ("hidden", "ALTER TABLE accounts ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(ddl)

    tcols = {r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()}
    if "external_id" not in tcols:
        conn.execute("ALTER TABLE transactions ADD COLUMN external_id TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_external_id ON transactions(external_id) WHERE external_id IS NOT NULL"
        )
    for col, ddl in [
        ("hidden", "ALTER TABLE transactions ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"),
        ("merchant_key", "ALTER TABLE transactions ADD COLUMN merchant_key TEXT"),
        ("person", "ALTER TABLE transactions ADD COLUMN person TEXT"),
    ]:
        if col not in tcols:
            conn.execute(ddl)

    conn.execute(
        """CREATE TABLE IF NOT EXISTS merchant_rules (
            merchant_key TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            display_name TEXT,
            source TEXT NOT NULL DEFAULT 'user',
            updated_at TEXT NOT NULL
        )"""
    )

    tripcols = {r[1] for r in conn.execute("PRAGMA table_info(holiday_trips)").fetchall()}
    if "destination" not in tripcols:
        conn.execute("ALTER TABLE holiday_trips ADD COLUMN destination TEXT")

    dcols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    for col, ddl in [
        ("category", "ALTER TABLE documents ADD COLUMN category TEXT NOT NULL DEFAULT 'other'"),
        ("notes", "ALTER TABLE documents ADD COLUMN notes TEXT NOT NULL DEFAULT ''"),
        ("file_name", "ALTER TABLE documents ADD COLUMN file_name TEXT"),
        ("file_path", "ALTER TABLE documents ADD COLUMN file_path TEXT"),
        ("mime_type", "ALTER TABLE documents ADD COLUMN mime_type TEXT"),
        ("file_size", "ALTER TABLE documents ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0"),
        ("uploaded_at", "ALTER TABLE documents ADD COLUMN uploaded_at TEXT"),
        ("user_id", "ALTER TABLE documents ADD COLUMN user_id TEXT"),
        ("expiry_date", "ALTER TABLE documents ADD COLUMN expiry_date TEXT"),
    ]:
        if col not in dcols:
            conn.execute(ddl)

    conn.execute(
        """CREATE TABLE IF NOT EXISTS media_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            caption TEXT NOT NULL DEFAULT '',
            media_type TEXT NOT NULL,
            trip_id TEXT,
            file_name TEXT,
            file_path TEXT,
            mime_type TEXT,
            file_size INTEGER NOT NULL DEFAULT 0,
            taken_at TEXT,
            uploaded_at TEXT NOT NULL,
            user_id TEXT,
            source TEXT NOT NULL DEFAULT 'upload',
            FOREIGN KEY (trip_id) REFERENCES holiday_trips(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""
    )
    mcols = {r[1] for r in conn.execute("PRAGMA table_info(media_items)").fetchall()}
    if "source" not in mcols:
        conn.execute("ALTER TABLE media_items ADD COLUMN source TEXT NOT NULL DEFAULT 'upload'")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
            id TEXT PRIMARY KEY,
            merchant_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            amount REAL NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'monthly',
            status TEXT NOT NULL DEFAULT 'detected',
            category TEXT NOT NULL DEFAULT 'Subscriptions',
            last_charge_date TEXT,
            next_expected_date TEXT,
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            account TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )"""
    )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS maintenance_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            last_service_date TEXT,
            next_due_date TEXT,
            interval_months INTEGER NOT NULL DEFAULT 12,
            vendor TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            warranty_expiry TEXT,
            user_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS activity_log (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            user_name TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS trip_documents (
            trip_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            PRIMARY KEY (trip_id, document_id),
            FOREIGN KEY (trip_id) REFERENCES holiday_trips(id) ON DELETE CASCADE,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pending_actions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            args_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS receipts (
            id TEXT PRIMARY KEY,
            transaction_id TEXT,
            user_id TEXT,
            merchant TEXT NOT NULL DEFAULT '',
            extracted_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notification_log (
            id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )"""
    )

    hcols = {r[1] for r in conn.execute("PRAGMA table_info(holiday_checklist)").fetchall()}
    if "item_type" not in hcols:
        conn.execute("ALTER TABLE holiday_checklist ADD COLUMN item_type TEXT NOT NULL DEFAULT 'checklist'")

    bcols = {r[1] for r in conn.execute("PRAGMA table_info(bills)").fetchall()}
    if "subscription_id" not in bcols:
        conn.execute("ALTER TABLE bills ADD COLUMN subscription_id TEXT")
    if "locked" not in bcols:
        conn.execute("ALTER TABLE bills ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")

    taskcols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "remind_at" not in taskcols:
        conn.execute("ALTER TABLE tasks ADD COLUMN remind_at TEXT")
    if "reminded_at" not in taskcols:
        conn.execute("ALTER TABLE tasks ADD COLUMN reminded_at TEXT")

    ecols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "google_event_id_written" not in ecols:
        conn.execute("ALTER TABLE events ADD COLUMN google_event_id_written TEXT")
    if "google_account_id" not in ecols:
        conn.execute("ALTER TABLE events ADD COLUMN google_account_id TEXT")
    if "calendar_name" not in ecols:
        conn.execute("ALTER TABLE events ADD COLUMN calendar_name TEXT")
    if "description" not in ecols:
        conn.execute("ALTER TABLE events ADD COLUMN description TEXT")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS google_accounts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            token_json TEXT NOT NULL,
            label TEXT,
            created_at TEXT NOT NULL,
            last_synced_at TEXT,
            UNIQUE(user_id, email)
        )"""
    )

    ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "phone" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")

    pcols = {r[1] for r in conn.execute("PRAGMA table_info(notification_prefs)").fetchall()}
    if "large_transaction_alerts" not in pcols:
        conn.execute("ALTER TABLE notification_prefs ADD COLUMN large_transaction_alerts INTEGER NOT NULL DEFAULT 1")
    if "large_transaction_threshold" not in pcols:
        conn.execute("ALTER TABLE notification_prefs ADD COLUMN large_transaction_threshold INTEGER NOT NULL DEFAULT 200")
    if "weekly_finance_summary" not in pcols:
        conn.execute("ALTER TABLE notification_prefs ADD COLUMN weekly_finance_summary INTEGER NOT NULL DEFAULT 1")
    if "budget_alerts" not in pcols:
        conn.execute("ALTER TABLE notification_prefs ADD COLUMN budget_alerts INTEGER NOT NULL DEFAULT 1")


def _seed(conn: sqlite3.Connection) -> None:
    """Seed ONLY the two real household accounts. No demo/sample content —
    the household adds their own bills, tasks, trips, etc."""
    from server.auth import hash_password

    users = [
        ("luke", "lbillyard@gmail.com", "Luke", "#2563eb"),
        ("partner", "lebillyard@gmail.com", "Laura", "#db2777"),
    ]
    password = os.environ.get("FAMILY_PORTAL_SEED_PASSWORD", "").strip()
    if not password:
        password = secrets.token_urlsafe(12)[:16]
        logger.warning("=" * 62)
        logger.warning("FAMILY_PORTAL_SEED_PASSWORD not set — generated seed password:")
        logger.warning("    %s", password)
        logger.warning("Log in with it and change it in Settings, or set the env var.")
        logger.warning("=" * 62)
    pw = hash_password(password)
    now = _utcnow()
    for uid, email, name, colour in users:
        conn.execute(
            "INSERT INTO users (id, email, name, password_hash, colour, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, email, name, pw, colour, now),
        )


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# --- Users ---

def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        return row_to_dict(row) if row else None


def get_user(user_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        d["google_token_json"] = _dec(d.get("google_token_json"))
        return d


def list_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [row_to_dict(r) for r in rows]


def user_public(u: dict) -> dict:
    with get_conn() as conn:
        connected = conn.execute(
            "SELECT 1 FROM google_accounts WHERE user_id = ? LIMIT 1", (u["id"],)
        ).fetchone()
    return {
        "id": u["id"],
        "name": u["name"],
        "email": u["email"],
        "colour": u["colour"],
        "phone": u.get("phone"),
        "google_connected": bool(connected),
    }


def _phone_digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def get_user_by_phone(phone: str) -> Optional[dict]:
    """Match an inbound WhatsApp number (e.g. '447911...') to a portal user by
    the last 9 significant digits, so 0/+44 prefixes don't matter."""
    target = _phone_digits(phone)[-9:]
    if not target:
        return None
    for u in list_users():
        if u.get("phone") and _phone_digits(u["phone"])[-9:] == target:
            return get_user(u["id"])
    return None


def update_user(user_id: str, data: dict) -> Optional[dict]:
    fields = []
    values = []
    if data.get("name"):
        fields.append("name = ?")
        values.append(data["name"].strip())
    if data.get("colour"):
        fields.append("colour = ?")
        values.append(data["colour"])
    if "phone" in data:
        fields.append("phone = ?")
        values.append((data["phone"] or "").strip() or None)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone():
            return None
        if fields:
            values.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return user_public(row_to_dict(row))


def update_user_password(user_id: str, password_hash: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        return cur.rowcount > 0


# --- Events ---

def list_events() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY start_at").fetchall()
        return [_event_out(row_to_dict(r)) for r in rows]


def create_event(data: dict, user_id: str) -> dict:
    eid = _new_id()
    now = _utcnow()
    uid = data.get("user_id") or user_id
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO events (id, user_id, title, start_at, end_at, all_day, source, location, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'portal', ?, ?)""",
            (eid, uid, data["title"], data["start"], data.get("end"), int(data.get("all_day", False)), data.get("location"), now),
        )
        row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
        return _event_out(row_to_dict(row))


def get_event(event_id: str) -> Optional[dict]:
    """Raw event row (includes source/google_event_id/google_account_id) — server use."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return row_to_dict(row) if row else None


def update_event(event_id: str, data: dict) -> Optional[dict]:
    mapping = {"title": "title", "start": "start_at", "end": "end_at", "location": "location", "user_id": "user_id", "description": "description"}
    fields, values = [], []
    for key, col in mapping.items():
        if data.get(key) is not None:
            fields.append(f"{col} = ?")
            values.append(data[key])
    if data.get("all_day") is not None:
        fields.append("all_day = ?")
        values.append(int(bool(data["all_day"])))
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone():
            return None
        if fields:
            values.append(event_id)
            conn.execute(f"UPDATE events SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _event_out(row_to_dict(row))


def delete_event(event_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return cur.rowcount > 0


def _event_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "start": r["start_at"],
        "end": r["end_at"],
        "user_id": r["user_id"],
        "source": r["source"],
        "all_day": bool(r["all_day"]),
        "location": r.get("location"),
        "calendar_name": r.get("calendar_name"),
        "description": r.get("description"),
    }


# --- Bills ---

def _reset_unlocked_bills(conn: sqlite3.Connection) -> int:
    """Un-tick manually-paid bills once a new billing period starts, so they
    come back as due instead of staying paid forever. Returns rows changed."""
    changed = 0
    rows = conn.execute("SELECT id, recurrence, paid_at FROM bills WHERE locked = 0 AND paid = 1").fetchall()
    for r in rows:
        period_start = _lock_period_start(r["recurrence"] or "monthly")
        if not r["paid_at"] or str(r["paid_at"])[:10] < period_start:
            conn.execute("UPDATE bills SET paid = 0, paid_at = NULL WHERE id = ?", (r["id"],))
            changed += 1
    return changed


def list_bills() -> list[dict]:
    with get_conn() as conn:
        _reset_unlocked_bills(conn)
        rows = conn.execute(
            """SELECT b.*, s.display_name AS locked_to_name, s.last_charge_date AS last_charge_date
               FROM bills b LEFT JOIN subscriptions s ON s.id = b.subscription_id
               ORDER BY b.due_day"""
        ).fetchall()
        return [_bill_out(row_to_dict(r)) for r in rows]


def get_bill(bill_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT b.*, s.display_name AS locked_to_name, s.last_charge_date AS last_charge_date
               FROM bills b LEFT JOIN subscriptions s ON s.id = b.subscription_id
               WHERE b.id = ?""",
            (bill_id,),
        ).fetchone()
        return _bill_out(row_to_dict(row)) if row else None


def create_bill(data: dict) -> dict:
    bid = _new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bills (id, name, amount, due_day, recurrence, category, paid) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (bid, data["name"], data["amount"], data["due_day"], data.get("recurrence", "monthly"), data.get("category", "Other")),
        )
        row = conn.execute("SELECT * FROM bills WHERE id = ?", (bid,)).fetchone()
        return _bill_out(row_to_dict(row))


def update_bill(bill_id: str, data: dict) -> Optional[dict]:
    mapping = {"name": "name", "amount": "amount", "due_day": "due_day", "recurrence": "recurrence", "category": "category"}
    fields, values = [], []
    for key, col in mapping.items():
        if data.get(key) is not None:
            fields.append(f"{col} = ?")
            values.append(data[key])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM bills WHERE id = ?", (bill_id,)).fetchone():
            return None
        if fields:
            values.append(bill_id)
            conn.execute(f"UPDATE bills SET {', '.join(fields)} WHERE id = ?", values)
    return get_bill(bill_id)


def mark_bill_paid(bill_id: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.execute("UPDATE bills SET paid = 1, paid_at = ? WHERE id = ?", (_utcnow(), bill_id))
        if not conn.execute("SELECT id FROM bills WHERE id = ?", (bill_id,)).fetchone():
            return None
    return get_bill(bill_id)


def delete_bill(bill_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        return cur.rowcount > 0


def set_bill_lock(bill_id: str, subscription_id: str | None = None, locked: bool = True) -> Optional[dict]:
    """Lock/unlock a bill to a detected bank subscription. When locked, the bill's
    paid state is auto-managed by reconcile_locked_bills()."""
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM bills WHERE id = ?", (bill_id,)).fetchone():
            return None
        if locked:
            conn.execute(
                "UPDATE bills SET locked = 1, subscription_id = COALESCE(?, subscription_id) WHERE id = ?",
                (subscription_id, bill_id),
            )
        else:
            conn.execute("UPDATE bills SET locked = 0 WHERE id = ?", (bill_id,))
    return get_bill(bill_id)


def _lock_period_start(recurrence: str) -> str:
    """The earliest charge date that counts as 'paid this period' for a locked bill."""
    today = date.today()
    if recurrence == "yearly":
        return (today - timedelta(days=365)).isoformat()
    if recurrence == "quarterly":
        return (today - timedelta(days=92)).isoformat()
    if recurrence == "weekly":
        return (today - timedelta(days=7)).isoformat()
    return today.replace(day=1).isoformat()  # monthly (default): this calendar month


def reconcile_locked_bills() -> int:
    """For each locked bill linked to a subscription, auto-set paid based on whether
    the matched bank payment landed in the current billing period. Returns rows changed."""
    changed = 0
    with get_conn() as conn:
        changed += _reset_unlocked_bills(conn)  # manual bills roll over each period too
        rows = conn.execute(
            """SELECT b.id, b.paid, b.recurrence, s.last_charge_date
               FROM bills b JOIN subscriptions s ON s.id = b.subscription_id
               WHERE b.locked = 1"""
        ).fetchall()
        for r in rows:
            since = _lock_period_start(r["recurrence"] or "monthly")
            charged = bool(r["last_charge_date"] and str(r["last_charge_date"])[:10] >= since)
            want_paid = 1 if charged else 0
            if int(bool(r["paid"])) != want_paid:
                if want_paid:
                    conn.execute("UPDATE bills SET paid = 1, paid_at = ? WHERE id = ?", (r["last_charge_date"], r["id"]))
                else:
                    conn.execute("UPDATE bills SET paid = 0, paid_at = NULL WHERE id = ?", (r["id"],))
                changed += 1
    return changed


def _bill_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "amount": r["amount"],
        "due_day": r["due_day"],
        "recurrence": r["recurrence"],
        "category": r["category"],
        "paid": bool(r["paid"]),
        "subscription_id": r.get("subscription_id"),
        "locked": bool(r.get("locked")),
        "locked_to_name": r.get("locked_to_name"),
        "last_charge_date": r.get("last_charge_date"),
    }


# --- Transactions ---

def list_transactions(limit: int = 50, include_hidden: bool = False) -> list[dict]:
    where = "" if include_hidden else "WHERE t.hidden = 0"
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT t.*, a.name AS account_name, m.display_name AS merchant_display
               FROM transactions t
               LEFT JOIN accounts a ON a.id = t.account_id
               LEFT JOIN merchant_rules m ON m.merchant_key = t.merchant_key
               {where}
               ORDER BY t.txn_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_txn_out(row_to_dict(r)) for r in rows]


def list_transactions_for_analysis(limit: int = 1000) -> list[dict]:
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.*, a.name AS account_name FROM transactions t
               LEFT JOIN accounts a ON a.id = t.account_id
               WHERE t.txn_date >= ? AND t.hidden = 0
               ORDER BY t.txn_date DESC LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
        return [_txn_out(row_to_dict(r)) for r in rows]


def create_transaction(data: dict) -> dict:
    tid = _new_id()
    now = _utcnow()
    txn_date = data.get("date") or date.today().isoformat()
    account_id = resolve_account_id(data.get("account_id"))
    amount = float(data["amount"])
    ext = data.get("external_id")
    with get_conn() as conn:
        if ext:
            # Idempotent: if this external source (e.g. a Gmail message) was already
            # imported, return the existing row without double-inserting or
            # double-adjusting the balance.
            existing = conn.execute(
                """SELECT t.*, a.name AS account_name FROM transactions t
                   LEFT JOIN accounts a ON a.id = t.account_id WHERE t.external_id = ?""",
                (ext,),
            ).fetchone()
            if existing:
                return _txn_out(row_to_dict(existing))
        conn.execute(
            "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, external_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, account_id, data["description"], data["category"], amount, txn_date, ext, now),
        )
        if account_id:
            conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id))
        row = conn.execute(
            """SELECT t.*, a.name AS account_name FROM transactions t
               LEFT JOIN accounts a ON a.id = t.account_id WHERE t.id = ?""",
            (tid,),
        ).fetchone()
        return _txn_out(row_to_dict(row))


def existing_external_ids(prefix: str = "") -> set[str]:
    """External ids already in the ledger (optionally filtered by a prefix like
    'gmail:'). Used to skip re-importing the same source rows."""
    with get_conn() as conn:
        if prefix:
            rows = conn.execute(
                "SELECT external_id FROM transactions WHERE external_id LIKE ?", (f"{prefix}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT external_id FROM transactions WHERE external_id IS NOT NULL"
            ).fetchall()
        return {r["external_id"] for r in rows}


def create_transfer(from_id: str, to_id: str, amount: float, description: str = "Transfer", txn_date: str | None = None) -> dict:
    """Move money between two accounts atomically: both transaction rows and
    both balance updates happen in one transaction (all-or-nothing)."""
    amount = abs(float(amount))
    when = txn_date or date.today().isoformat()
    now = _utcnow()
    with get_conn() as conn:
        names = {
            r["id"]: r["name"]
            for r in conn.execute("SELECT id, name FROM accounts WHERE id IN (?, ?)", (from_id, to_id)).fetchall()
        }
        if from_id not in names or to_id not in names:
            raise ValueError("Unknown account")
        out_id, in_id = _new_id(), _new_id()
        conn.execute(
            "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (out_id, from_id, f"{description} → {names[to_id]}", "Transfers", -amount, when, now),
        )
        conn.execute(
            "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (in_id, to_id, f"{description} ← {names[from_id]}", "Transfers", amount, when, now),
        )
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_id))
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))
    return {"ok": True, "from": names[from_id], "to": names[to_id], "amount": amount}


def delete_transaction(txn_id: str) -> bool:
    """Delete a transaction and reverse its effect on the account balance."""
    with get_conn() as conn:
        row = conn.execute("SELECT account_id, amount FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (row["amount"], row["account_id"]))
        conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        return True


def _txn_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "date": r["txn_date"],
        "description": r["description"],
        "display_name": r.get("merchant_display") or r["description"],
        "merchant_key": r.get("merchant_key"),
        "category": r["category"],
        "amount": r["amount"],
        "account": r.get("account_name") or r.get("account_id", ""),
        "person": r.get("person"),
    }


def get_transaction(txn_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        return row_to_dict(row) if row else None


# --- Accounts & budgets ---

def resolve_account_id(preferred: str | None = None) -> str | None:
    """Resolve `preferred` (an account id OR name) to a real accounts.id.
    Falls back to the first current account, then any account, else None."""
    accounts = list_accounts(include_hidden=True)
    if not accounts:
        return None
    if preferred:
        if any(a["id"] == preferred for a in accounts):
            return preferred
        by_name = {a["name"]: a["id"] for a in accounts}
        if preferred in by_name:
            return by_name[preferred]
    return next((a["id"] for a in accounts if a["type"] == "current"), accounts[0]["id"])


def list_accounts(include_hidden: bool = False) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY linked DESC, name").fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            d["linked"] = bool(d.get("linked"))
            d["name_custom"] = bool(d.get("name_custom"))
            d["hidden"] = bool(d.get("hidden"))
            if d["hidden"] and not include_hidden:
                continue
            result.append(d)
        return result


def rename_account(account_id: str, name: str) -> Optional[dict]:
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone():
            return None
        conn.execute("UPDATE accounts SET name = ?, name_custom = 1 WHERE id = ?", (name.strip(), account_id))
    return next((a for a in list_accounts(include_hidden=True) if a["id"] == account_id), None)


def set_account_hidden(account_id: str, hidden: bool) -> Optional[dict]:
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone():
            return None
        conn.execute("UPDATE accounts SET hidden = ? WHERE id = ?", (1 if hidden else 0, account_id))
    return next((a for a in list_accounts(include_hidden=True) if a["id"] == account_id), None)


def list_budgets() -> list[dict]:
    month_prefix = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM budgets ORDER BY category").fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            spent_row = conn.execute(
                """SELECT COALESCE(SUM(ABS(amount)), 0) AS s FROM transactions
                   WHERE category = ? AND amount < 0 AND hidden = 0 AND txn_date LIKE ?""",
                (d["category"], f"{month_prefix}%"),
            ).fetchone()
            result.append({
                "category": d["category"],
                "limit": d["monthly_limit"],
                "spent": round(spent_row["s"], 2),
            })
        return result


def _budget_out(category: str) -> Optional[dict]:
    month_prefix = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM budgets WHERE category = ?", (category,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        spent = conn.execute(
            """SELECT COALESCE(SUM(ABS(amount)), 0) AS s FROM transactions
               WHERE category = ? AND amount < 0 AND hidden = 0 AND txn_date LIKE ?""",
            (d["category"], f"{month_prefix}%"),
        ).fetchone()["s"]
        return {"category": d["category"], "limit": d["monthly_limit"], "spent": round(spent, 2)}


def create_budget(category: str, monthly_limit: float) -> dict:
    """Create (or replace) a budget target for a category. Category is unique."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO budgets (id, category, monthly_limit) VALUES (?, ?, ?)
               ON CONFLICT(category) DO UPDATE SET monthly_limit = excluded.monthly_limit""",
            (_new_id(), category, monthly_limit),
        )
    return _budget_out(category)


def update_budget(category: str, monthly_limit: float) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.execute("UPDATE budgets SET monthly_limit = ? WHERE category = ?", (monthly_limit, category))
        if cur.rowcount == 0:
            return None
    return _budget_out(category)


def delete_budget(category: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM budgets WHERE category = ?", (category,))
        return cur.rowcount > 0


def list_savings_goals() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM savings_goals ORDER BY name").fetchall()
        return [row_to_dict(r) for r in rows]


def get_savings_goal(goal_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM savings_goals WHERE id = ?", (goal_id,)).fetchone()
        return row_to_dict(row) if row else None


def create_savings_goal(data: dict) -> dict:
    gid = _new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO savings_goals (id, name, target, current, colour) VALUES (?, ?, ?, ?, ?)",
            (gid, data["name"], data["target"], data.get("current", 0) or 0, data.get("colour") or "#00a89e"),
        )
        row = conn.execute("SELECT * FROM savings_goals WHERE id = ?", (gid,)).fetchone()
        return row_to_dict(row)


def update_savings_goal(goal_id: str, data: dict) -> Optional[dict]:
    mapping = {"name": "name", "target": "target", "current": "current", "colour": "colour"}
    fields, values = [], []
    for key, col in mapping.items():
        if data.get(key) is not None:
            fields.append(f"{col} = ?")
            values.append(data[key])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM savings_goals WHERE id = ?", (goal_id,)).fetchone():
            return None
        if fields:
            values.append(goal_id)
            conn.execute(f"UPDATE savings_goals SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM savings_goals WHERE id = ?", (goal_id,)).fetchone()
        return row_to_dict(row)


def delete_savings_goal(goal_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM savings_goals WHERE id = ?", (goal_id,))
        return cur.rowcount > 0


# --- Family memory (RAG facts) ---

def _memory_out(r: dict, *, include_embedding: bool = False) -> dict:
    out = {
        "id": r["id"],
        "text": r["text"],
        "category": r["category"],
        "subject": r["subject"],
        "source": r["source"],
        "pinned": bool(r["pinned"]),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }
    if include_embedding:
        raw = r.get("embedding")
        try:
            out["embedding"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            out["embedding"] = None
    return out


def list_memory_facts(include_embedding: bool = True) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM memory_facts ORDER BY pinned DESC, updated_at DESC").fetchall()
        return [_memory_out(row_to_dict(r), include_embedding=include_embedding) for r in rows]


def get_memory_fact(fact_id: str, include_embedding: bool = False) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        return _memory_out(row_to_dict(row), include_embedding=include_embedding) if row else None


def create_memory_fact(data: dict) -> dict:
    fid = _new_id()
    now = _utcnow()
    emb = data.get("embedding")
    emb_json = json.dumps(emb) if emb is not None else None
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO memory_facts (id, text, category, subject, source, pinned, embedding, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fid, data["text"], data.get("category", "preferences"), data.get("subject", "family"),
             data.get("source", "manual"), 1 if data.get("pinned") else 0, emb_json, now, now),
        )
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fid,)).fetchone()
        return _memory_out(row_to_dict(row))


def update_memory_fact(fact_id: str, data: dict) -> Optional[dict]:
    now = _utcnow()
    sets, values = [], []
    for key in ("text", "category", "subject", "source"):
        if data.get(key) is not None:
            sets.append(f"{key} = ?")
            values.append(data[key])
    if "pinned" in data and data["pinned"] is not None:
        sets.append("pinned = ?")
        values.append(1 if data["pinned"] else 0)
    if "embedding" in data:
        sets.append("embedding = ?")
        values.append(json.dumps(data["embedding"]) if data["embedding"] is not None else None)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM memory_facts WHERE id = ?", (fact_id,)).fetchone():
            return None
        if sets:
            sets.append("updated_at = ?")
            values.append(now)
            values.append(fact_id)
            conn.execute(f"UPDATE memory_facts SET {', '.join(sets)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        return _memory_out(row_to_dict(row))


def touch_memory_facts(fact_ids: list[str]) -> None:
    """Record that these facts were surfaced (for 'recently used' insight)."""
    if not fact_ids:
        return
    now = _utcnow()
    with get_conn() as conn:
        conn.executemany("UPDATE memory_facts SET last_used_at = ? WHERE id = ?", [(now, fid) for fid in fact_ids])


def delete_memory_fact(fact_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
        return cur.rowcount > 0


def finance_summary() -> dict:
    from server.services import categorize as cz

    month_prefix = date.today().strftime("%Y-%m")
    # Transfers/savings/crypto shuffles aren't income or spending (matches
    # list_budgets/category_breakdown). Income stays countable as income.
    spend_excluded = sorted(cz.NON_SPEND_CATEGORIES)
    income_excluded = sorted(cz.NON_SPEND_CATEGORIES - {"Income"})
    with get_conn() as conn:
        income = conn.execute(
            f"""SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
                WHERE amount > 0 AND hidden = 0 AND txn_date LIKE ?
                  AND category NOT IN ({','.join('?' * len(income_excluded))})""",
            (f"{month_prefix}%", *income_excluded),
        ).fetchone()["s"]
        spent = conn.execute(
            f"""SELECT COALESCE(SUM(ABS(amount)), 0) AS s FROM transactions
                WHERE amount < 0 AND hidden = 0 AND txn_date LIKE ?
                  AND category NOT IN ({','.join('?' * len(spend_excluded))})""",
            (f"{month_prefix}%", *spend_excluded),
        ).fetchone()["s"]
        bills_due = conn.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM bills WHERE paid = 0").fetchone()["s"]
        current_total = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS s FROM accounts WHERE type = 'current'"
        ).fetchone()["s"]
        savings = conn.execute("SELECT COALESCE(SUM(current), 0) AS s FROM savings_goals").fetchone()["s"]
        return {
            "monthly_income": round(income, 2),
            "monthly_spent": round(spent, 2),
            "bills_due_this_month": round(bills_due, 2),
            "joint_balance": round(current_total, 2),
            "savings_total": round(savings, 2),
        }


# --- Transaction categorisation (rules + learned overrides + AI) ---

def get_merchant_rules() -> dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT merchant_key, category, display_name FROM merchant_rules").fetchall()
        return {r["merchant_key"]: {"category": r["category"], "display_name": r["display_name"]} for r in rows}


def upsert_merchant_rule(merchant_key: str, category: str, display_name: Optional[str], source: str = "user") -> None:
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO merchant_rules (merchant_key, category, display_name, source, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(merchant_key) DO UPDATE SET
                 category = excluded.category,
                 display_name = COALESCE(excluded.display_name, merchant_rules.display_name),
                 source = excluded.source, updated_at = excluded.updated_at""",
            (merchant_key, category, display_name, source, now),
        )


def apply_categorization() -> dict:
    """Re-derive category/merchant_key/hidden for all transactions.
    Learned rules win; then built-in rules; already-friendly categories are preserved."""
    from server.services import categorize as cz

    learned = {k: v["category"] for k, v in get_merchant_rules().items()}
    counts: dict[str, int] = {}
    with get_conn() as conn:
        rows = conn.execute("SELECT id, description, amount, category FROM transactions").fetchall()
        for r in rows:
            key = cz.normalize_merchant(r["description"])
            if key in learned:
                cat = learned[key]
            else:
                rc = cz.rule_category(r["description"])
                if rc:
                    cat = rc
                elif r["category"] in cz.CATEGORIES:
                    cat = r["category"]
                elif (r["amount"] or 0) > 0:
                    cat = "Income"
                else:
                    cat = "Other"
            hidden = 1 if cat in cz.HIDDEN_CATEGORIES else 0
            conn.execute(
                "UPDATE transactions SET category = ?, merchant_key = ?, hidden = ? WHERE id = ?",
                (cat, key, hidden, r["id"]),
            )
            counts[cat] = counts.get(cat, 0) + 1
    return {"updated": sum(counts.values()), "by_category": counts}


def learn_and_reclassify(merchant_key: str, category: str, display_name: Optional[str] = None, source: str = "user") -> int:
    """Save a merchant rule and re-apply it to every matching transaction."""
    from server.services import categorize as cz

    upsert_merchant_rule(merchant_key, category, display_name, source)
    hidden = 1 if category in cz.HIDDEN_CATEGORIES else 0
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE transactions SET category = ?, hidden = ? WHERE merchant_key = ?",
            (category, hidden, merchant_key),
        )
        return cur.rowcount


def set_transaction_category(txn_id: str, category: str) -> Optional[dict]:
    from server.services import categorize as cz

    hidden = 1 if category in cz.HIDDEN_CATEGORIES else 0
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM transactions WHERE id = ?", (txn_id,)).fetchone():
            return None
        conn.execute("UPDATE transactions SET category = ?, hidden = ? WHERE id = ?", (category, hidden, txn_id))
    return get_transaction(txn_id)


def set_transaction_person(txn_id: str, person: Optional[str]) -> Optional[dict]:
    """Assign a transaction to a person ('luke'|'partner'|'joint') or clear it.
    None/''/'unassigned' store NULL. Returns the updated txn, or None if not found."""
    value = person if person not in (None, "", "unassigned") else None
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM transactions WHERE id = ?", (txn_id,)).fetchone():
            return None
        conn.execute("UPDATE transactions SET person = ? WHERE id = ?", (value, txn_id))
    return get_transaction(txn_id)


def spend_by_person(month: Optional[str] = None) -> list[dict]:
    """Spend (ABS of outgoings) grouped by person for a 'YYYY-MM' month.
    Defaults to the latest month present in the ledger, else the current month.
    Excludes hidden rows. Persons with no spend are omitted; sorted amount desc."""
    with get_conn() as conn:
        if not month:
            latest = conn.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0]
            month = latest[:7] if latest else date.today().strftime("%Y-%m")
        rows = conn.execute(
            """SELECT COALESCE(person, 'unassigned') AS person,
                      COALESCE(SUM(ABS(amount)), 0) AS spent
               FROM transactions
               WHERE hidden = 0 AND amount < 0 AND txn_date LIKE ?
               GROUP BY COALESCE(person, 'unassigned')
               ORDER BY spent DESC""",
            (f"{month}%",),
        ).fetchall()
        return [{"person": r["person"], "amount": round(r["spent"], 2)} for r in rows if r["spent"]]


def category_breakdown() -> list[dict]:
    """This month's spending grouped by category, excluding hidden + non-spend buckets."""
    from server.services import categorize as cz

    month_prefix = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT category, COALESCE(SUM(ABS(amount)), 0) AS spent, COUNT(*) AS n
               FROM transactions
               WHERE hidden = 0 AND amount < 0 AND txn_date LIKE ?
               GROUP BY category ORDER BY spent DESC""",
            (f"{month_prefix}%",),
        ).fetchall()
        return [
            {"category": r["category"], "spent": round(r["spent"], 2), "count": r["n"]}
            for r in rows
            if r["category"] not in cz.NON_SPEND_CATEGORIES
        ]


def get_uncategorized_merchants(limit: int = 60) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT description FROM transactions
               WHERE hidden = 0 AND category = 'Other'
               GROUP BY UPPER(description) ORDER BY COUNT(*) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [r["description"] for r in rows]


# --- Tasks ---

def list_tasks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY done, due_date").fetchall()
        return [_task_out(row_to_dict(r)) for r in rows]


def create_task(data: dict) -> dict:
    tid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, assignee_id, due_date, priority, remind_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, data["title"], data.get("assignee_id"), data.get("due"), data.get("priority", "medium"), data.get("remind_at"), now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        return _task_out(row_to_dict(row))


def get_task(task_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_out(row_to_dict(row)) if row else None


def delete_task(task_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0


def update_task(task_id: str, data: dict) -> Optional[dict]:
    fields = []
    values = []
    if "done" in data:
        fields.append("done = ?")
        values.append(int(data["done"]))
    if data.get("title"):
        fields.append("title = ?")
        values.append(data["title"])
    if "assignee_id" in data:
        fields.append("assignee_id = ?")
        values.append(data["assignee_id"])
    if "due" in data:
        fields.append("due_date = ?")
        values.append(data["due"])
    if data.get("priority"):
        fields.append("priority = ?")
        values.append(data["priority"])
    if "remind_at" in data:
        fields.append("remind_at = ?")
        values.append(data["remind_at"])
        # A newly-set (or changed) reminder time should be free to fire again.
        fields.append("reminded_at = ?")
        values.append(None)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
            return None
        if fields:
            values.append(task_id)
            conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_out(row_to_dict(row)) if row else None


def _uk_now_iso() -> str:
    """Naive Europe/London wall-clock time, matching how remind_at is entered
    (a plain datetime-local value with no timezone) so string comparison works."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None, second=0, microsecond=0).isoformat(timespec="minutes")


def list_tasks_due_for_reminder() -> list[dict]:
    """Open tasks whose remind_at has passed and haven't been reminded since."""
    now = _uk_now_iso()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM tasks
               WHERE done = 0 AND remind_at IS NOT NULL AND remind_at <= ?
                 AND (reminded_at IS NULL OR reminded_at < remind_at)""",
            (now,),
        ).fetchall()
        return [_task_out(row_to_dict(r)) for r in rows]


def mark_task_reminded(task_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET reminded_at = ? WHERE id = ?", (_uk_now_iso(), task_id))


def _task_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "assignee": r["assignee_id"],
        "due": r["due_date"],
        "done": bool(r["done"]),
        "priority": r["priority"],
        "remind_at": r.get("remind_at"),
        "reminded_at": r.get("reminded_at"),
    }


# --- Appointments ---

def list_appointments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM appointments ORDER BY datetime").fetchall()
        return [_appt_out(row_to_dict(r)) for r in rows]


def create_appointment(data: dict, default_user: str) -> dict:
    aid = _new_id()
    now = _utcnow()
    uid = data.get("user_id") or default_user
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO appointments (id, user_id, title, provider, datetime, category, location, reminder_days, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, uid, data["title"], data["provider"], data["datetime"], data.get("category", "health"),
             data.get("location"), data.get("reminder_days", 2), now),
        )
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
        return _appt_out(row_to_dict(row))


def update_appointment(appt_id: str, data: dict) -> Optional[dict]:
    fields = []
    values = []
    for key in ("title", "provider", "datetime", "user_id", "category", "location", "status"):
        if data.get(key) is not None:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if data.get("reminder_days") is not None:
        fields.append("reminder_days = ?")
        values.append(int(data["reminder_days"]))
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM appointments WHERE id = ?", (appt_id,)).fetchone():
            return None
        if fields:
            values.append(appt_id)
            conn.execute(f"UPDATE appointments SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        return _appt_out(row_to_dict(row))


def delete_appointment(appt_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        return cur.rowcount > 0


def _appt_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "provider": r["provider"],
        "datetime": r["datetime"],
        "user_id": r["user_id"],
        "status": r["status"],
        "category": r["category"],
        "location": r.get("location"),
        "reminder_days": r["reminder_days"],
    }


# --- Holidays ---

def list_trips() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM holiday_trips ORDER BY start_date").fetchall()
        trips = []
        today = date.today()
        for r in rows:
            d = row_to_dict(r)
            checklist = conn.execute(
                "SELECT id, label, done, item_type FROM holiday_checklist WHERE trip_id = ? ORDER BY sort_order",
                (d["id"],),
            ).fetchall()
            checklist_items = []
            packing_items = []
            for c in checklist:
                item = {"id": c["id"], "label": c["label"], "done": bool(c["done"])}
                if c["item_type"] == "packing":
                    packing_items.append(item)
                else:
                    checklist_items.append(item)
            media_count = conn.execute(
                "SELECT COUNT(*) AS c FROM media_items WHERE trip_id = ?", (d["id"],)
            ).fetchone()["c"]
            doc_count = conn.execute(
                "SELECT COUNT(*) AS c FROM trip_documents WHERE trip_id = ?", (d["id"],)
            ).fetchone()["c"]
            days_until = None
            if d.get("start_date") and d["status"] == "booked":
                try:
                    start = date.fromisoformat(d["start_date"])
                    trip_end = date.fromisoformat(d["end_date"]) if d.get("end_date") else start
                    if trip_end >= today:  # ended trips have no countdown
                        days_until = max((start - today).days, 0)
                except ValueError:
                    pass
            trips.append({
                "id": d["id"],
                "title": d["title"],
                "status": d["status"],
                "start": d.get("start_date"),
                "end": d.get("end_date"),
                "destination": d.get("destination"),
                "budget": d["budget"],
                "spent": d["spent"],
                "days_until": days_until,
                "checklist": checklist_items,
                "packing": packing_items,
                "media_count": media_count,
                "doc_count": doc_count,
                "bookings": [],
            })
        return trips


def create_trip(data: dict) -> dict:
    tid = _new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO holiday_trips (id, title, status, start_date, end_date, budget, spent, destination) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (tid, data["title"], data.get("status", "idea"), data.get("start"), data.get("end"), data.get("budget", 0), data.get("destination")),
        )
    trips = list_trips()
    return next(t for t in trips if t["id"] == tid)


def update_trip(trip_id: str, data: dict) -> Optional[dict]:
    colmap = {
        "title": "title",
        "status": "status",
        "start": "start_date",
        "end": "end_date",
        "budget": "budget",
        "spent": "spent",
        "destination": "destination",
    }
    nullable = {"start", "end", "destination"}  # explicit null clears these
    fields = []
    values = []
    for key, col in colmap.items():
        if key in data and (data[key] is not None or key in nullable):
            fields.append(f"{col} = ?")
            values.append(data[key])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM holiday_trips WHERE id = ?", (trip_id,)).fetchone():
            return None
        if fields:
            values.append(trip_id)
            conn.execute(f"UPDATE holiday_trips SET {', '.join(fields)} WHERE id = ?", values)
    return next((t for t in list_trips() if t["id"] == trip_id), None)


def delete_trip(trip_id: str) -> bool:
    """Delete a trip and its checklist/packing rows and document links;
    photos linked to the trip are kept but unlinked."""
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM holiday_trips WHERE id = ?", (trip_id,)).fetchone():
            return False
        conn.execute("DELETE FROM holiday_checklist WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM trip_documents WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM itinerary_items WHERE trip_id = ?", (trip_id,))
        conn.execute("UPDATE media_items SET trip_id = NULL WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM holiday_trips WHERE id = ?", (trip_id,))
        return True


def list_holiday_ideas() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM holiday_ideas ORDER BY saved DESC, destination").fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            result.append({
                "id": d["id"],
                "destination": d["destination"],
                "summary": d["summary"],
                "budget_estimate": d["budget_estimate"],
                "saved": bool(d["saved"]),
                "tags": json.loads(d.get("tags_json") or "[]"),
            })
        return result


def toggle_idea_saved(idea_id: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.execute("UPDATE holiday_ideas SET saved = 1 - saved WHERE id = ?", (idea_id,))
        row = conn.execute("SELECT * FROM holiday_ideas WHERE id = ?", (idea_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        return {
            "id": d["id"],
            "destination": d["destination"],
            "summary": d["summary"],
            "budget_estimate": d["budget_estimate"],
            "saved": bool(d["saved"]),
            "tags": json.loads(d.get("tags_json") or "[]"),
        }


# --- Documents ---

def _document_status(expiry: str, stored: str = "ok") -> str:
    if not expiry:
        return stored if stored != "renew_soon" else stored
    try:
        exp = date.fromisoformat(expiry[:10])
        today = date.today()
        if exp < today:
            return "expired"
        if (exp - today).days <= 60:
            return "renew_soon"
        return "ok"
    except ValueError:
        return stored or "ok"


def _document_out(row: dict) -> dict:
    d = dict(row)
    d["has_file"] = bool(d.get("file_path"))
    d["status"] = _document_status(d.get("expiry") or "", d.get("status", "ok"))
    d["file_size"] = d.get("file_size") or 0
    d["expiry_date"] = d.get("expiry_date")
    return d


def list_documents(category: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if category and category != "all":
            rows = conn.execute(
                "SELECT * FROM documents WHERE category = ? ORDER BY expiry, name",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM documents ORDER BY expiry, name").fetchall()
        return [_document_out(row_to_dict(r)) for r in rows]


def get_document(doc_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return _document_out(row_to_dict(row)) if row else None


def create_document(data: dict) -> dict:
    did = data.get("id") or _new_id()
    now = _utcnow()
    expiry = data.get("expiry") or ""
    status = _document_status(expiry)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, name, category, expiry, status, notes, file_name, file_path, mime_type, file_size, uploaded_at, user_id, expiry_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                did,
                data["name"],
                data.get("category", "other"),
                expiry,
                status,
                data.get("notes", ""),
                data.get("file_name"),
                data.get("file_path"),
                data.get("mime_type"),
                data.get("file_size", 0),
                data.get("uploaded_at", now if data.get("file_path") else None),
                data.get("user_id"),
                data.get("expiry_date") or None,
            ),
        )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
        return _document_out(row_to_dict(row))


def delete_document(doc_id: str) -> tuple[bool, Optional[str]]:
    """Delete document row. Returns (found, stored file_path for filesystem
    cleanup) — metadata-only documents are (True, None), missing rows (False, None)."""
    with get_conn() as conn:
        row = conn.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return False, None
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return True, row["file_path"]


def documents_expiring_within(days: int) -> list[dict]:
    """Documents whose expiry_date falls within `days` from today. Includes ones
    that lapsed at most 1 day ago (a small grace window) but nothing older, so a
    reminder can still fire the day something expires."""
    today = date.today()
    horizon = today + timedelta(days=days)
    floor = today - timedelta(days=1)
    out: list[dict] = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE expiry_date IS NOT NULL AND expiry_date != '' ORDER BY expiry_date, name"
        ).fetchall()
        for r in rows:
            d = row_to_dict(r)
            try:
                exp = date.fromisoformat(str(d["expiry_date"])[:10])
            except (TypeError, ValueError):
                continue
            if floor <= exp <= horizon:
                out.append(_document_out(d))
    return out


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def save_google_token(user_id: str, token_json: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET google_token_json = ? WHERE id = ?", (_enc(token_json), user_id))


# --- Google accounts (multiple per user: e.g. personal + work) ---

def upsert_google_account(user_id: str, email: str, token_json: str, label: str | None = None) -> str:
    """Insert or update a connected Google account, keyed by (user, email). Returns its id."""
    now = _utcnow()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM google_accounts WHERE user_id = ? AND email = ?", (user_id, email)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE google_accounts SET token_json = ?, label = COALESCE(?, label) WHERE id = ?",
                (_enc(token_json), label, row["id"]),
            )
            return row["id"]
        aid = _new_id()
        conn.execute(
            """INSERT INTO google_accounts (id, user_id, email, token_json, label, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (aid, user_id, email, _enc(token_json), label, now),
        )
        return aid


def list_google_accounts(user_id: str | None = None) -> list[dict]:
    """Public rows (no token). Optionally scoped to one portal user."""
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT id, user_id, email, label, last_synced_at FROM google_accounts WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, email, label, last_synced_at FROM google_accounts ORDER BY created_at"
            ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_google_account_internal(account_id: str) -> dict | None:
    """Full row with decrypted token_json — server-side only."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM google_accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        d["token_json"] = _dec(d["token_json"])
        return d


def update_google_account_token(account_id: str, token_json: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE google_accounts SET token_json = ? WHERE id = ?", (_enc(token_json), account_id))


def mark_google_account_synced(account_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE google_accounts SET last_synced_at = ? WHERE id = ?", (_utcnow(), account_id))


def delete_google_account(account_id: str) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE google_account_id = ?", (account_id,))
        cur = conn.execute("DELETE FROM google_accounts WHERE id = ?", (account_id,))
        return cur.rowcount > 0


def delete_events_for_google_account(account_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE google_account_id = ?", (account_id,))


def create_google_event(*, user_id: str, google_account_id: str, google_id: str, title: str,
                        start: str, end: str | None, all_day: bool, location: str | None,
                        calendar_name: str | None = None, description: str | None = None) -> None:
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO events (id, user_id, title, start_at, end_at, all_day, source, location,
                                   google_event_id, google_account_id, calendar_name, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'google', ?, ?, ?, ?, ?, ?)""",
            (_new_id(), user_id, title, start, end, int(all_day), location, google_id,
             google_account_id, calendar_name, description, now),
        )


def create_holiday_ideas(ideas: list[dict]) -> list[dict]:
    with get_conn() as conn:
        for idea in ideas:
            conn.execute(
                """INSERT INTO holiday_ideas (id, destination, summary, budget_estimate, saved, tags_json)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (
                    _new_id(),
                    idea["destination"],
                    idea["summary"],
                    idea.get("budget_estimate", 0),
                    json.dumps(idea.get("tags", [])),
                ),
            )
    return list_holiday_ideas()


def import_transactions(rows: list[dict]) -> int:
    """Bulk insert transactions from CSV. Returns count imported."""
    now = _utcnow()
    count = 0
    with get_conn() as conn:
        for row in rows:
            tid = _new_id()
            account_id = row.get("account_id")
            conn.execute(
                """INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tid, account_id, row["description"], row.get("category", "Imported"),
                 row["amount"], row["date"], now),
            )
            if account_id:
                conn.execute(
                    "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                    (row["amount"], account_id),
                )
            count += 1
    return count


# --- Open Banking OAuth state (survives cross-domain redirect via tunnel) ---

def save_banking_oauth_state(state: str, user_id: str, provider_id: str) -> None:
    payload = json.dumps({"user_id": user_id, "provider_id": provider_id, "created_at": _utcnow()})
    set_setting(f"bank_oauth_{state}", payload)


def pop_banking_oauth_state(state: str) -> Optional[dict]:
    key = f"bank_oauth_{state}"
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    try:
        data = json.loads(row["value"])
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - created).total_seconds() > 900:
            return None
        return data
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


# --- Open Banking connections ---

def create_bank_connection(
    user_id: str,
    provider_id: str,
    provider_name: str,
    access_token: str,
    refresh_token: str,
    token_expires_at: str,
) -> dict:
    cid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bank_connections
               (id, user_id, provider_id, provider_name, access_token, refresh_token,
                token_expires_at, status, connected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (cid, user_id, provider_id, provider_name, _enc(access_token), _enc(refresh_token), token_expires_at, now),
        )
        row = conn.execute("SELECT * FROM bank_connections WHERE id = ?", (cid,)).fetchone()
        return _connection_public(row_to_dict(row))


def update_bank_tokens(
    connection_id: str,
    access_token: str,
    refresh_token: str,
    token_expires_at: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE bank_connections
               SET access_token = ?, refresh_token = ?, token_expires_at = ?, status = 'active'
               WHERE id = ?""",
            (_enc(access_token), _enc(refresh_token), token_expires_at, connection_id),
        )


def list_bank_connections(user_id: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM bank_connections WHERE user_id = ? ORDER BY connected_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM bank_connections ORDER BY connected_at DESC").fetchall()
        return [_connection_public(row_to_dict(r)) for r in rows]


def get_bank_connection_internal(connection_id: str) -> Optional[dict]:
    """Full connection including decrypted tokens — server use only."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bank_connections WHERE id = ?", (connection_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        d["access_token"] = _dec(d.get("access_token"))
        d["refresh_token"] = _dec(d.get("refresh_token"))
        return d


def delete_bank_connection(connection_id: str) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM bank_connections WHERE id = ?", (connection_id,))
        conn.execute("UPDATE accounts SET linked = 0, connection_id = NULL WHERE connection_id = ?", (connection_id,))
        return True


def mark_connection_synced(connection_id: str) -> None:
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            "UPDATE bank_connections SET last_synced_at = ? WHERE id = ?",
            (now, connection_id),
        )


def set_connection_status(connection_id: str, status: str) -> None:
    """e.g. 'needs_reauth' when a sync fails; update_bank_tokens resets to 'active'."""
    with get_conn() as conn:
        conn.execute("UPDATE bank_connections SET status = ? WHERE id = ?", (status, connection_id))


def upsert_linked_account(
    *,
    connection_id: str,
    external_id: str,
    name: str,
    account_type: str,
    institution: str,
) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM accounts WHERE connection_id = ? AND external_id = ?",
            (connection_id, external_id),
        ).fetchone()
        if row:
            existing = conn.execute("SELECT name_custom FROM accounts WHERE id = ?", (row["id"],)).fetchone()
            if existing and existing["name_custom"]:
                conn.execute(
                    "UPDATE accounts SET type = ?, institution = ?, linked = 1 WHERE id = ?",
                    (account_type, institution, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE accounts SET name = ?, type = ?, institution = ?, linked = 1 WHERE id = ?",
                    (name, account_type, institution, row["id"]),
                )
            return row["id"]

        aid = _new_id()
        conn.execute(
            """INSERT INTO accounts (id, name, type, balance, institution, connection_id, external_id, linked)
               VALUES (?, ?, ?, 0, ?, ?, ?, 1)""",
            (aid, name, account_type, institution, connection_id, external_id),
        )
        return aid


def set_account_balance(account_id: str, balance: float) -> None:
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET balance = ?, last_synced_at = ? WHERE id = ?",
            (round(balance, 2), now, account_id),
        )


def import_external_transactions(rows: list[dict]) -> int:
    """Insert bank-synced transactions (auto-categorised), skipping duplicates by external_id."""
    from server.services import categorize as cz

    learned = {k: v["category"] for k, v in get_merchant_rules().items()}
    now = _utcnow()
    count = 0
    with get_conn() as conn:
        for row in rows:
            ext = row.get("external_id")
            if ext:
                if conn.execute("SELECT id FROM transactions WHERE external_id = ?", (ext,)).fetchone():
                    continue
            desc = row["description"]
            amount = row["amount"]
            key = cz.normalize_merchant(desc)
            cat = cz.categorize(desc, amount, learned)
            hidden = 1 if cat in cz.HIDDEN_CATEGORIES else 0
            tid = _new_id()
            conn.execute(
                """INSERT INTO transactions
                   (id, account_id, description, category, amount, txn_date, created_at, external_id, merchant_key, hidden)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, row["account_id"], desc, cat, amount, row["date"], now, ext, key, hidden),
            )
            count += 1
    return count


def _connection_public(conn: dict) -> dict:
    return {
        "id": conn["id"],
        "user_id": conn["user_id"],
        "provider_id": conn["provider_id"],
        "provider_name": conn["provider_name"],
        "status": conn["status"],
        "connected_at": conn["connected_at"],
        "last_synced_at": conn.get("last_synced_at"),
    }


# --- Media ---

def list_media(trip_id: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if trip_id:
            rows = conn.execute(
                """SELECT m.*, t.title AS trip_title FROM media_items m
                   LEFT JOIN holiday_trips t ON t.id = m.trip_id
                   WHERE m.trip_id = ? ORDER BY m.taken_at DESC, m.uploaded_at DESC""",
                (trip_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT m.*, t.title AS trip_title FROM media_items m
                   LEFT JOIN holiday_trips t ON t.id = m.trip_id
                   ORDER BY m.taken_at DESC, m.uploaded_at DESC"""
            ).fetchall()
        return [_media_out(row_to_dict(r)) for r in rows]


def get_media(media_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT m.*, t.title AS trip_title FROM media_items m
               LEFT JOIN holiday_trips t ON t.id = m.trip_id WHERE m.id = ?""",
            (media_id,),
        ).fetchone()
        return _media_out(row_to_dict(row)) if row else None


def create_media(data: dict) -> dict:
    mid = data.get("id") or _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO media_items
               (id, title, caption, media_type, trip_id, file_name, file_path, mime_type, file_size, taken_at, uploaded_at, user_id, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                data["title"],
                data.get("caption", ""),
                data["media_type"],
                data.get("trip_id") or None,
                data.get("file_name"),
                data.get("file_path"),
                data.get("mime_type"),
                data.get("file_size", 0),
                data.get("taken_at") or "",
                now,
                data.get("user_id"),
                data.get("source", "upload"),
            ),
        )
    return get_media(mid)  # type: ignore[return-value]


def update_media(media_id: str, data: dict) -> Optional[dict]:
    with get_conn() as conn:
        if "title" in data:
            conn.execute("UPDATE media_items SET title = ? WHERE id = ?", (data["title"], media_id))
        if "caption" in data:
            conn.execute("UPDATE media_items SET caption = ? WHERE id = ?", (data["caption"], media_id))
        if "trip_id" in data:
            conn.execute("UPDATE media_items SET trip_id = ? WHERE id = ?", (data["trip_id"] or None, media_id))
        if "taken_at" in data:
            conn.execute("UPDATE media_items SET taken_at = ? WHERE id = ?", (data["taken_at"] or "", media_id))
    return get_media(media_id)


def delete_media(media_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT file_path FROM media_items WHERE id = ?", (media_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM media_items WHERE id = ?", (media_id,))
        return row["file_path"]


def _media_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "caption": r.get("caption", ""),
        "media_type": r["media_type"],
        "trip_id": r.get("trip_id"),
        "trip_title": r.get("trip_title"),
        "file_name": r.get("file_name"),
        "file_path": r.get("file_path"),
        "mime_type": r.get("mime_type"),
        "file_size": r.get("file_size", 0),
        "taken_at": r.get("taken_at") or "",
        "uploaded_at": r.get("uploaded_at"),
        "user_id": r.get("user_id"),
        "source": r.get("source", "upload"),
        "has_file": bool(r.get("file_path")),
    }


# --- Subscriptions ---

def list_subscriptions(include_ignored: bool = True) -> list[dict]:
    with get_conn() as conn:
        if include_ignored:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY amount DESC, display_name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE status != 'ignored' ORDER BY amount DESC, display_name"
            ).fetchall()
        return [_subscription_out(row_to_dict(r)) for r in rows]


def get_subscription(sub_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return _subscription_out(row_to_dict(row)) if row else None


def sync_subscriptions(detected: list[dict]) -> list[dict]:
    now = _utcnow()
    with get_conn() as conn:
        for d in detected:
            row = conn.execute(
                "SELECT id, status FROM subscriptions WHERE merchant_key = ?",
                (d["merchant_key"],),
            ).fetchone()
            if row and row["status"] == "ignored":
                continue
            if row:
                # display_name/category are user-editable — never clobber them on re-sync.
                conn.execute(
                    """UPDATE subscriptions SET amount = ?, frequency = ?,
                       last_charge_date = ?, next_expected_date = ?, occurrence_count = ?,
                       account = ?, updated_at = ?
                       WHERE merchant_key = ?""",
                    (
                        d["amount"],
                        d["frequency"],
                        d.get("last_charge_date"),
                        d.get("next_expected_date"),
                        d["occurrence_count"],
                        d.get("account", ""),
                        now,
                        d["merchant_key"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO subscriptions
                       (id, merchant_key, display_name, amount, frequency, status, category,
                        last_charge_date, next_expected_date, occurrence_count, account, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'detected', ?, ?, ?, ?, ?, ?)""",
                    (
                        _new_id(),
                        d["merchant_key"],
                        d["display_name"],
                        d["amount"],
                        d["frequency"],
                        d.get("category", "Subscriptions"),
                        d.get("last_charge_date"),
                        d.get("next_expected_date"),
                        d["occurrence_count"],
                        d.get("account", ""),
                        now,
                    ),
                )
        # Lapse pass: no charge for ~2x the expected period means it has stopped;
        # a fresh charge within the window revives it. Only auto-manage 'detected'
        # and 'lapsed' rows — never a user-'confirmed' sub (that flag is theirs to
        # keep) and never 'ignored'. Revival restores 'detected', not a phantom
        # 'active' status the UI has no label for.
        stale_days = {"weekly": 14, "monthly": 60, "quarterly": 184, "yearly": 730}
        today = date.today()
        for r in conn.execute(
            "SELECT id, frequency, status, last_charge_date FROM subscriptions WHERE status IN ('detected', 'lapsed')"
        ).fetchall():
            cutoff = (today - timedelta(days=stale_days.get(r["frequency"], 60))).isoformat()
            last = str(r["last_charge_date"] or "")[:10]
            if last and last < cutoff:
                if r["status"] != "lapsed":
                    conn.execute("UPDATE subscriptions SET status = 'lapsed', updated_at = ? WHERE id = ?", (now, r["id"]))
            elif r["status"] == "lapsed":
                conn.execute("UPDATE subscriptions SET status = 'detected', updated_at = ? WHERE id = ?", (now, r["id"]))
    return list_subscriptions(include_ignored=True)


def update_subscription(sub_id: str, data: dict) -> Optional[dict]:
    now = _utcnow()
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        if not row:
            return None
        if "status" in data:
            conn.execute("UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (data["status"], now, sub_id))
        if "display_name" in data:
            conn.execute("UPDATE subscriptions SET display_name = ?, updated_at = ? WHERE id = ?", (data["display_name"], now, sub_id))
        if "notes" in data:
            conn.execute("UPDATE subscriptions SET notes = ?, updated_at = ? WHERE id = ?", (data["notes"], now, sub_id))
        if "category" in data:
            conn.execute("UPDATE subscriptions SET category = ?, updated_at = ? WHERE id = ?", (data["category"], now, sub_id))
    return get_subscription(sub_id)


def _subscription_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "merchant_key": r["merchant_key"],
        "display_name": r["display_name"],
        "amount": r["amount"],
        "frequency": r["frequency"],
        "status": r["status"],
        "category": r["category"],
        "last_charge_date": r.get("last_charge_date"),
        "next_expected_date": r.get("next_expected_date"),
        "occurrence_count": r.get("occurrence_count", 0),
        "account": r.get("account", ""),
        "notes": r.get("notes", ""),
        "updated_at": r.get("updated_at"),
    }


# --- Maintenance ---

def list_maintenance() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM maintenance_items ORDER BY next_due_date, title").fetchall()
        return [_maintenance_out(row_to_dict(r)) for r in rows]


def create_maintenance(data: dict) -> dict:
    mid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO maintenance_items
               (id, title, category, last_service_date, next_due_date, interval_months, vendor, notes, warranty_expiry, user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                data["title"],
                data.get("category", "general"),
                data.get("last_service_date", ""),
                data.get("next_due_date", ""),
                int(data.get("interval_months") or 12),
                data.get("vendor", ""),
                data.get("notes", ""),
                data.get("warranty_expiry", ""),
                data.get("user_id"),
                now,
            ),
        )
    return get_maintenance(mid)  # type: ignore[return-value]


def get_maintenance(item_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM maintenance_items WHERE id = ?", (item_id,)).fetchone()
        return _maintenance_out(row_to_dict(row)) if row else None


def update_maintenance(item_id: str, data: dict) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM maintenance_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        fields = []
        values = []
        for key in ("title", "category", "last_service_date", "next_due_date", "vendor", "notes", "warranty_expiry"):
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if "interval_months" in data:
            fields.append("interval_months = ?")
            values.append(int(data["interval_months"]))
        if fields:
            values.append(item_id)
            conn.execute(f"UPDATE maintenance_items SET {', '.join(fields)} WHERE id = ?", values)
    return get_maintenance(item_id)


def mark_maintenance_done(item_id: str, service_date: str | None = None) -> Optional[dict]:
    item = get_maintenance(item_id)
    if not item:
        return None
    svc = service_date or date.today().isoformat()
    next_due = ""
    months = int(item.get("interval_months") or 0)
    if months > 0:
        d = date.fromisoformat(svc[:10])
        month_idx = d.month - 1 + months
        year = d.year + month_idx // 12
        month = month_idx % 12 + 1
        next_due = date(year, month, min(d.day, 28)).isoformat()
    return update_maintenance(item_id, {"last_service_date": svc, "next_due_date": next_due})


def delete_maintenance(item_id: str) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM maintenance_items WHERE id = ?", (item_id,))
        return True


def _maintenance_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "category": r["category"],
        "last_service_date": r.get("last_service_date") or "",
        "next_due_date": r.get("next_due_date") or "",
        "interval_months": r.get("interval_months", 12),
        "vendor": r.get("vendor", ""),
        "notes": r.get("notes", ""),
        "warranty_expiry": r.get("warranty_expiry") or "",
        "user_id": r.get("user_id"),
    }


# --- Activity feed ---

def create_activity(data: dict) -> dict:
    aid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO activity_log (id, user_id, user_name, action, entity_type, entity_id, summary, meta_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                data.get("user_id", ""),
                data.get("user_name", ""),
                data["action"],
                data["entity_type"],
                data.get("entity_id", ""),
                data["summary"],
                data.get("meta_json", "{}"),
                now,
            ),
        )
    return {"id": aid, "summary": data["summary"], "created_at": now}


def list_activity(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_activity_out(row_to_dict(r)) for r in rows]


def _activity_out(r: dict) -> dict:
    meta = {}
    try:
        meta = json.loads(r.get("meta_json") or "{}")
    except json.JSONDecodeError:
        pass
    return {
        "id": r["id"],
        "user_id": r.get("user_id"),
        "user_name": r.get("user_name"),
        "action": r["action"],
        "entity_type": r["entity_type"],
        "entity_id": r.get("entity_id"),
        "summary": r["summary"],
        "meta": meta,
        "created_at": r["created_at"],
    }


# --- Trip documents & packing ---

def link_trip_document(trip_id: str, document_id: str) -> bool:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO trip_documents (trip_id, document_id) VALUES (?, ?)",
            (trip_id, document_id),
        )
        return True


def unlink_trip_document(trip_id: str, document_id: str) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM trip_documents WHERE trip_id = ? AND document_id = ?", (trip_id, document_id))
        return True


def list_trip_documents(trip_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT d.* FROM documents d
               INNER JOIN trip_documents td ON td.document_id = d.id
               WHERE td.trip_id = ? ORDER BY d.name""",
            (trip_id,),
        ).fetchall()
        return [_document_out(row_to_dict(r)) for r in rows]


def add_packing_items(trip_id: str, labels: list[str]) -> list[dict]:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT label FROM holiday_checklist WHERE trip_id = ? AND item_type = 'packing'",
            (trip_id,),
        ).fetchall()
        seen = {str(r["label"]).strip().lower() for r in existing}
        order = len(existing)
        for label in labels:
            key = label.strip().lower()
            if key in seen:  # re-applying a template shouldn't duplicate items
                continue
            conn.execute(
                """INSERT INTO holiday_checklist (id, trip_id, label, done, sort_order, item_type)
                   VALUES (?, ?, ?, 0, ?, 'packing')""",
                (_new_id(), trip_id, label, order),
            )
            seen.add(key)
            order += 1
    trip = get_trip_detail(trip_id)
    return trip.get("packing", []) if trip else []


def toggle_checklist_item(trip_id: str, label: str, item_type: str = "checklist") -> bool:
    """`label` may be the row id or the visible label (list_trips only exposes labels)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, done FROM holiday_checklist WHERE trip_id = ? AND id = ?",
            (trip_id, label),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id, done FROM holiday_checklist WHERE trip_id = ? AND label = ? AND item_type = ?",
                (trip_id, label, item_type),
            ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE holiday_checklist SET done = ? WHERE id = ?",
            (0 if row["done"] else 1, row["id"]),
        )
        return True


def get_trip_detail(trip_id: str) -> Optional[dict]:
    trips = list_trips()
    trip = next((t for t in trips if t["id"] == trip_id), None)
    if not trip:
        return None
    trip["linked_documents"] = list_trip_documents(trip_id)
    return trip


# --- Pending AI actions ---

def create_pending_action(data: dict) -> dict:
    pid = _new_id()
    now = _utcnow()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_actions WHERE expires_at < ?", (now,))  # opportunistic cleanup
        conn.execute(
            """INSERT INTO pending_actions (id, user_id, tool_name, args_json, summary, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, data["user_id"], data["tool_name"], data["args_json"], data["summary"], now, expires),
        )
    return get_pending_action(pid)  # type: ignore[return-value]


def get_pending_action(action_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        return {
            "id": d["id"],
            "user_id": d["user_id"],
            "tool_name": d["tool_name"],
            "args": json.loads(d["args_json"]),
            "summary": d["summary"],
            "created_at": d["created_at"],
            "expires_at": d["expires_at"],
        }


def delete_pending_action(action_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_actions WHERE id = ?", (action_id,))


def list_pending_actions(user_id: str) -> list[dict]:
    now = _utcnow()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC",
            (user_id, now),
        ).fetchall()
        return [get_pending_action(row_to_dict(r)["id"]) for r in rows]  # type: ignore[misc]


# --- Receipts & notifications ---

def create_receipt(data: dict) -> dict:
    rid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO receipts (id, transaction_id, user_id, merchant, extracted_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rid, data.get("transaction_id"), data.get("user_id"), data.get("merchant", ""), data.get("extracted_json", "{}"), now),
        )
    return {"id": rid, "transaction_id": data.get("transaction_id"), "created_at": now}


def create_notification_log(data: dict) -> dict:
    nid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO notification_log (id, channel, subject, body, status, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (nid, data["channel"], data["subject"], data["body"], data["status"], data.get("detail", ""), now),
        )
    return {"id": nid, "status": data["status"], "created_at": now}


def list_notification_log(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def link_bill_subscription(bill_id: str, subscription_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE bills SET subscription_id = ? WHERE id = ?", (subscription_id, bill_id))


def set_event_google_written(event_id: str, google_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE events SET google_event_id_written = ?, source = 'portal' WHERE id = ?", (google_id, event_id))


def list_written_google_event_ids() -> set[str]:
    """Google event ids the portal wrote back — sync skips these to avoid duplicates."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT google_event_id_written FROM events WHERE google_event_id_written IS NOT NULL"
        ).fetchall()
        return {r["google_event_id_written"] for r in rows}


# --- Notification preferences (household-level, single row) ---

_PREFS_ID = "household"
_PREFS_BOOL_FIELDS = (
    "master_enabled",
    "morning_digest",
    "evening_digest",
    "appointment_reminders",
    "bill_reminders",
    "renewal_reminders",
    "document_expiry_reminders",
    "large_transaction_alerts",
    "weekly_finance_summary",
    "budget_alerts",
)


def _prefs_out(r: dict) -> dict:
    out: dict[str, Any] = {"id": r["id"]}
    for f in _PREFS_BOOL_FIELDS:
        out[f] = bool(r[f])
    out["reminder_lead_days"] = int(r["reminder_lead_days"])
    out["large_transaction_threshold"] = int(r["large_transaction_threshold"])
    out["updated_at"] = r.get("updated_at")
    return out


def get_notification_prefs() -> dict:
    """The single household prefs row, creating it with defaults on first call."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notification_prefs WHERE id = ?", (_PREFS_ID,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO notification_prefs (id, updated_at) VALUES (?, ?)", (_PREFS_ID, _utcnow())
            )
            row = conn.execute("SELECT * FROM notification_prefs WHERE id = ?", (_PREFS_ID,)).fetchone()
        return _prefs_out(row_to_dict(row))


def update_notification_prefs(data: dict) -> dict:
    """Update any subset of the prefs (bools accept truthy). Returns the fresh row."""
    get_notification_prefs()  # ensure the row exists before we UPDATE it
    fields, values = [], []
    for f in _PREFS_BOOL_FIELDS:
        if f in data and data[f] is not None:
            fields.append(f"{f} = ?")
            values.append(1 if data[f] else 0)
    if data.get("reminder_lead_days") is not None:
        fields.append("reminder_lead_days = ?")
        values.append(int(data["reminder_lead_days"]))
    if data.get("large_transaction_threshold") is not None:
        fields.append("large_transaction_threshold = ?")
        values.append(int(data["large_transaction_threshold"]))
    with get_conn() as conn:
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(_PREFS_ID)
            conn.execute(f"UPDATE notification_prefs SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM notification_prefs WHERE id = ?", (_PREFS_ID,)).fetchone()
        return _prefs_out(row_to_dict(row))


# --- Sent-notification dedupe ledger (a reminder is only ever sent once) ---

def was_notified(key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM sent_notifications WHERE key = ?", (key,)).fetchone()
        return row is not None


def mark_notified(key: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sent_notifications (key, sent_at) VALUES (?, ?)", (key, _utcnow())
        )


def prune_notifications(older_than_days: int = 90) -> int:
    """Housekeeping: drop dedupe rows older than `older_than_days`. Returns rows deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM sent_notifications WHERE sent_at < ?", (cutoff,))
        return cur.rowcount


# --- Tradespeople directory ---

def _tradesperson_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "trade": r.get("trade"),
        "phone": r.get("phone"),
        "email": r.get("email"),
        "notes": r.get("notes"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_tradespeople() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tradespeople ORDER BY trade, name").fetchall()
        return [_tradesperson_out(row_to_dict(r)) for r in rows]


def get_tradesperson(tradesperson_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tradespeople WHERE id = ?", (tradesperson_id,)).fetchone()
        return _tradesperson_out(row_to_dict(row)) if row else None


def create_tradesperson(data: dict) -> dict:
    tid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO tradespeople (id, name, trade, phone, email, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tid,
                data["name"],
                data.get("trade"),
                data.get("phone"),
                data.get("email"),
                data.get("notes"),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM tradespeople WHERE id = ?", (tid,)).fetchone()
        return _tradesperson_out(row_to_dict(row))


def update_tradesperson(tradesperson_id: str, data: dict) -> Optional[dict]:
    fields, values = [], []
    for key in ("name", "trade", "phone", "email", "notes"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(data[key])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM tradespeople WHERE id = ?", (tradesperson_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(tradesperson_id)
            conn.execute(f"UPDATE tradespeople SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM tradespeople WHERE id = ?", (tradesperson_id,)).fetchone()
        return _tradesperson_out(row_to_dict(row))


def delete_tradesperson(tradesperson_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tradespeople WHERE id = ?", (tradesperson_id,))
        return cur.rowcount > 0


# --- Push subscriptions (browser/PWA Web Push) ---

def _push_subscription_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "user_id": r.get("user_id"),
        "endpoint": r["endpoint"],
        "p256dh": r["p256dh"],
        "auth": r["auth"],
        "created_at": r.get("created_at"),
    }


def add_push_subscription(user_id: Optional[str], endpoint: str, p256dh: str, auth: str) -> dict:
    """Register a Web Push subscription. Idempotent on endpoint — re-subscribing
    with the same endpoint refreshes its keys and owner rather than duplicating."""
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                 user_id = excluded.user_id,
                 p256dh = excluded.p256dh,
                 auth = excluded.auth""",
            (_new_id(), user_id, endpoint, p256dh, auth, now),
        )
        row = conn.execute("SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
        return _push_subscription_out(row_to_dict(row))


def list_push_subscriptions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM push_subscriptions ORDER BY created_at").fetchall()
        return [_push_subscription_out(row_to_dict(r)) for r in rows]


def delete_push_subscription(endpoint: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        return cur.rowcount > 0


# --- Shopping list (shared household list) ---

def _shopping_item_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "text": r["text"],
        "done": bool(r["done"]),
        "added_by": r.get("added_by"),
        "created_at": r.get("created_at"),
    }


def list_shopping_items() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM shopping_items ORDER BY done ASC, created_at ASC"
        ).fetchall()
        return [_shopping_item_out(row_to_dict(r)) for r in rows]


def create_shopping_item(text: str, added_by: str | None = None) -> dict:
    sid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO shopping_items (id, text, done, added_by, created_at)
               VALUES (?, ?, 0, ?, ?)""",
            (sid, text.strip(), added_by, now),
        )
        row = conn.execute("SELECT * FROM shopping_items WHERE id = ?", (sid,)).fetchone()
        return _shopping_item_out(row_to_dict(row))


def set_shopping_item_done(item_id: str, done: bool) -> Optional[dict]:
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM shopping_items WHERE id = ?", (item_id,)).fetchone():
            return None
        conn.execute(
            "UPDATE shopping_items SET done = ? WHERE id = ?", (1 if done else 0, item_id)
        )
        row = conn.execute("SELECT * FROM shopping_items WHERE id = ?", (item_id,)).fetchone()
        return _shopping_item_out(row_to_dict(row))


def delete_shopping_item(item_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM shopping_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


def clear_done_shopping_items() -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM shopping_items WHERE done = 1")
        return cur.rowcount


# --- Assets (net worth) ---

def _asset_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "type": r["type"],
        "value": float(r["value"]),
        "notes": r.get("notes"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_assets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM assets ORDER BY value DESC").fetchall()
        return [_asset_out(row_to_dict(r)) for r in rows]


def create_asset(data: dict) -> dict:
    aid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO assets (id, name, type, value, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                data["name"],
                data.get("type") or "other",
                float(data.get("value") or 0),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
        return _asset_out(row_to_dict(row))


def update_asset(asset_id: str, data: dict) -> Optional[dict]:
    fields, values = [], []
    for key in ("name", "type", "notes"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if data.get("value") is not None:
        fields.append("value = ?")
        values.append(float(data["value"]))
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(asset_id)
            conn.execute(f"UPDATE assets SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_out(row_to_dict(row))


def delete_asset(asset_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        return cur.rowcount > 0


# --- Meal plans (one planned dinner per calendar day) ---

def _meal_plan_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "date": r["date"],
        "title": r["title"],
        "ingredients": r["ingredients"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_meal_plans(start: str, end: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM meal_plans WHERE date BETWEEN ? AND ? ORDER BY date ASC",
            (start, end),
        ).fetchall()
        return [_meal_plan_out(row_to_dict(r)) for r in rows]


def get_meal_plan(day: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meal_plans WHERE date = ?", (day,)).fetchone()
        return _meal_plan_out(row_to_dict(row)) if row else None


def upsert_meal_plan(day: str, title: str, ingredients: str = "") -> dict:
    """Plan (or re-plan) the dinner for a single calendar day. Because `date` is
    UNIQUE, a second call for the same day updates the existing row in place
    (keeping its id) rather than inserting a duplicate."""
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO meal_plans (id, date, title, ingredients, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 title = excluded.title,
                 ingredients = excluded.ingredients,
                 updated_at = excluded.updated_at""",
            (_new_id(), day, title.strip(), ingredients or "", now, now),
        )
        row = conn.execute("SELECT * FROM meal_plans WHERE date = ?", (day,)).fetchone()
        return _meal_plan_out(row_to_dict(row))


def delete_meal_plan(day: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM meal_plans WHERE date = ?", (day,))
        return cur.rowcount > 0


# --- Net worth snapshots (finance trend history) ---

def _networth_snapshot_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "date": r["date"],
        "net_worth": float(r["net_worth"]),
        "cash_total": float(r["cash_total"]),
        "assets_total": float(r["assets_total"]),
        "liabilities_total": float(r["liabilities_total"]),
        "created_at": r.get("created_at"),
    }


def upsert_networth_snapshot(
    day: str,
    net_worth: float,
    cash_total: float,
    assets_total: float,
    liabilities_total: float,
) -> dict:
    """Record (or re-record) the net worth breakdown for a single calendar day.
    Because `date` is UNIQUE, a second call for the same day updates the existing
    row in place (keeping its id) rather than inserting a duplicate."""
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO networth_snapshots
                   (id, date, net_worth, cash_total, assets_total, liabilities_total, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 net_worth = excluded.net_worth,
                 cash_total = excluded.cash_total,
                 assets_total = excluded.assets_total,
                 liabilities_total = excluded.liabilities_total""",
            (
                _new_id(),
                day,
                float(net_worth),
                float(cash_total),
                float(assets_total),
                float(liabilities_total),
                now,
            ),
        )
        row = conn.execute("SELECT * FROM networth_snapshots WHERE date = ?", (day,)).fetchone()
        return _networth_snapshot_out(row_to_dict(row))


def list_networth_snapshots(limit: int = 30) -> list[dict]:
    """The most recent `limit` snapshots, returned oldest→newest so a chart can
    plot them left→right."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM networth_snapshots ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_networth_snapshot_out(row_to_dict(r)) for r in reversed(rows)]


# --- Chores (recurring rotating household jobs) ---

def _chore_out(r: dict) -> dict:
    assignee_id = r.get("assignee_id")
    assignee_name = None
    if assignee_id:
        user = get_user(assignee_id)
        assignee_name = user["name"] if user else None
    return {
        "id": r["id"],
        "title": r["title"],
        "cadence": r["cadence"],
        "assignee_id": assignee_id,
        "assignee_name": assignee_name,
        "rotate": bool(r["rotate"]),
        "next_due": r.get("next_due"),
        "last_done": r.get("last_done"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_chores() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chores ORDER BY (next_due IS NULL), next_due ASC, title"
        ).fetchall()
        return [_chore_out(row_to_dict(r)) for r in rows]


def get_chore(chore_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM chores WHERE id = ?", (chore_id,)).fetchone()
        return _chore_out(row_to_dict(row)) if row else None


def create_chore(data: dict) -> dict:
    cid = _new_id()
    now = _utcnow()
    rotate = 1 if data.get("rotate", True) else 0
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO chores
                   (id, title, cadence, assignee_id, rotate, next_due, last_done, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                data["title"].strip(),
                data.get("cadence") or "weekly",
                data.get("assignee_id"),
                rotate,
                data.get("next_due"),
                None,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM chores WHERE id = ?", (cid,)).fetchone()
        return _chore_out(row_to_dict(row))


def update_chore(chore_id: str, data: dict) -> Optional[dict]:
    """Partial update. `assignee_id`, `next_due` and `last_done` may be set to an
    explicit value INCLUDING None whenever the key is present in `data` (so the
    backend's rotation logic can clear/reassign), so presence — not truthiness —
    decides whether they're written."""
    fields, values = [], []
    if data.get("title") is not None:
        fields.append("title = ?")
        values.append(data["title"].strip())
    if data.get("cadence") is not None:
        fields.append("cadence = ?")
        values.append(data["cadence"])
    if "assignee_id" in data:
        fields.append("assignee_id = ?")
        values.append(data["assignee_id"])
    if "rotate" in data and data["rotate"] is not None:
        fields.append("rotate = ?")
        values.append(1 if data["rotate"] else 0)
    if "next_due" in data:
        fields.append("next_due = ?")
        values.append(data["next_due"])
    if "last_done" in data:
        fields.append("last_done = ?")
        values.append(data["last_done"])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM chores WHERE id = ?", (chore_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(chore_id)
            conn.execute(f"UPDATE chores SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM chores WHERE id = ?", (chore_id,)).fetchone()
        return _chore_out(row_to_dict(row))


def delete_chore(chore_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM chores WHERE id = ?", (chore_id,))
        return cur.rowcount > 0


# --- Occasions (birthdays / anniversaries, annually recurring) ---

def _occasion_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "kind": r["kind"],
        "date": r["date"],
        "person": r.get("person"),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_occasions() -> list[dict]:
    """All occasions, ordered by month-day (substr past the year) so they read in
    calendar order regardless of the original year stored in `date`."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM occasions ORDER BY substr(date, 6), title"
        ).fetchall()
        return [_occasion_out(row_to_dict(r)) for r in rows]


def get_occasion(occasion_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM occasions WHERE id = ?", (occasion_id,)).fetchone()
        return _occasion_out(row_to_dict(row)) if row else None


def create_occasion(data: dict) -> dict:
    oid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO occasions (id, title, kind, date, person, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                oid,
                data["title"].strip(),
                data.get("kind") or "birthday",
                data["date"],
                data.get("person"),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM occasions WHERE id = ?", (oid,)).fetchone()
        return _occasion_out(row_to_dict(row))


def update_occasion(occasion_id: str, data: dict) -> Optional[dict]:
    """Partial update. `person` and `notes` use presence (`key in data`) rather
    than truthiness so they can be cleared; `notes` coerces None to '' to honour
    its NOT NULL constraint."""
    fields, values = [], []
    if data.get("title") is not None:
        fields.append("title = ?")
        values.append(data["title"].strip())
    if data.get("kind") is not None:
        fields.append("kind = ?")
        values.append(data["kind"])
    if data.get("date") is not None:
        fields.append("date = ?")
        values.append(data["date"])
    if "person" in data:
        fields.append("person = ?")
        values.append(data["person"])
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM occasions WHERE id = ?", (occasion_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(occasion_id)
            conn.execute(f"UPDATE occasions SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM occasions WHERE id = ?", (occasion_id,)).fetchone()
        return _occasion_out(row_to_dict(row))


def delete_occasion(occasion_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM occasions WHERE id = ?", (occasion_id,))
        return cur.rowcount > 0


# --- Inventory items (home inventory / warranty tracker) ---

def _inventory_out(r: dict) -> dict:
    price = r.get("price")
    return {
        "id": r["id"],
        "name": r["name"],
        "category": r["category"],
        "brand": r.get("brand"),
        "model": r.get("model"),
        "serial": r.get("serial"),
        "purchase_date": r.get("purchase_date"),
        "price": float(price) if price is not None else None,
        "warranty_expiry": r.get("warranty_expiry"),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_inventory() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM inventory_items ORDER BY name").fetchall()
        return [_inventory_out(row_to_dict(r)) for r in rows]


def get_inventory_item(item_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        return _inventory_out(row_to_dict(row)) if row else None


def create_inventory_item(data: dict) -> dict:
    iid = _new_id()
    now = _utcnow()
    price = data.get("price")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO inventory_items
                   (id, name, category, brand, model, serial, purchase_date, price, warranty_expiry, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                iid,
                data["name"].strip(),
                data.get("category") or "other",
                data.get("brand"),
                data.get("model"),
                data.get("serial"),
                data.get("purchase_date"),
                float(price) if price is not None else None,
                data.get("warranty_expiry"),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (iid,)).fetchone()
        return _inventory_out(row_to_dict(row))


def update_inventory_item(item_id: str, data: dict) -> Optional[dict]:
    """Partial update. The nullable fields (brand/model/serial/purchase_date/
    warranty_expiry/price) use presence (`key in data`) so they can be cleared to
    NULL; `notes` coerces None to '' to honour its NOT NULL constraint."""
    fields, values = [], []
    if data.get("name") is not None:
        fields.append("name = ?")
        values.append(data["name"].strip())
    if data.get("category") is not None:
        fields.append("category = ?")
        values.append(data["category"])
    for key in ("brand", "model", "serial", "purchase_date", "warranty_expiry"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "price" in data:
        fields.append("price = ?")
        values.append(float(data["price"]) if data["price"] is not None else None)
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM inventory_items WHERE id = ?", (item_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(item_id)
            conn.execute(f"UPDATE inventory_items SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        return _inventory_out(row_to_dict(row))


def delete_inventory_item(item_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


def inventory_expiring_within(days: int) -> list[dict]:
    """Inventory items whose warranty_expiry falls within `days` from today.
    Mirrors documents_expiring_within: includes ones that lapsed at most 1 day
    ago (a small grace window) but nothing older, so a reminder can still fire
    the day a warranty expires."""
    today = date.today()
    horizon = today + timedelta(days=days)
    floor = today - timedelta(days=1)
    out: list[dict] = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inventory_items WHERE warranty_expiry IS NOT NULL AND warranty_expiry != '' ORDER BY warranty_expiry, name"
        ).fetchall()
        for r in rows:
            d = row_to_dict(r)
            try:
                exp = date.fromisoformat(str(d["warranty_expiry"])[:10])
            except (TypeError, ValueError):
                continue
            if floor <= exp <= horizon:
                out.append(_inventory_out(d))
    return out


# --- Recipes (recipe box) ---

def _recipe_out(r: dict) -> dict:
    serves = r.get("serves")
    return {
        "id": r["id"],
        "title": r["title"],
        "ingredients": r["ingredients"],
        "method": r["method"],
        "tags": r["tags"],
        "serves": int(serves) if serves is not None else None,
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_recipes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM recipes ORDER BY title").fetchall()
        return [_recipe_out(row_to_dict(r)) for r in rows]


def get_recipe(recipe_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        return _recipe_out(row_to_dict(row)) if row else None


def create_recipe(data: dict) -> dict:
    rid = _new_id()
    now = _utcnow()
    serves = data.get("serves")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO recipes (id, title, ingredients, method, tags, serves, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                data["title"].strip(),
                data.get("ingredients") or "",
                data.get("method") or "",
                data.get("tags") or "",
                int(serves) if serves is not None else None,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone()
        return _recipe_out(row_to_dict(row))


def update_recipe(recipe_id: str, data: dict) -> Optional[dict]:
    """Partial update. Text fields (ingredients/method/tags) use presence
    (`key in data`) and coerce None to '' to honour their NOT NULL constraints;
    `serves` uses presence so it can be cleared to NULL."""
    fields, values = [], []
    if data.get("title") is not None:
        fields.append("title = ?")
        values.append(data["title"].strip())
    for key in ("ingredients", "method", "tags"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key] if data[key] is not None else "")
    if "serves" in data:
        fields.append("serves = ?")
        values.append(int(data["serves"]) if data["serves"] is not None else None)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM recipes WHERE id = ?", (recipe_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(recipe_id)
            conn.execute(f"UPDATE recipes SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        return _recipe_out(row_to_dict(row))


def delete_recipe(recipe_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        return cur.rowcount > 0


# --- Dependents (children & pets) ---

def _dependent_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "kind": r["kind"],
        "dob": r.get("dob"),
        "breed": r.get("breed"),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_dependents() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM dependents ORDER BY kind, name").fetchall()
        return [_dependent_out(row_to_dict(r)) for r in rows]


def get_dependent(dependent_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM dependents WHERE id = ?", (dependent_id,)).fetchone()
        return _dependent_out(row_to_dict(row)) if row else None


def create_dependent(data: dict) -> dict:
    did = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO dependents (id, name, kind, dob, breed, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                did,
                data["name"].strip(),
                data.get("kind") or "child",
                data.get("dob"),
                data.get("breed"),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM dependents WHERE id = ?", (did,)).fetchone()
        return _dependent_out(row_to_dict(row))


def update_dependent(dependent_id: str, data: dict) -> Optional[dict]:
    """Partial update. The nullable fields (dob/breed) use presence (`key in
    data`) so they can be cleared to NULL; `notes` coerces None to '' to honour
    its NOT NULL constraint."""
    fields, values = [], []
    if data.get("name") is not None:
        fields.append("name = ?")
        values.append(data["name"].strip())
    if data.get("kind") is not None:
        fields.append("kind = ?")
        values.append(data["kind"])
    for key in ("dob", "breed"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM dependents WHERE id = ?", (dependent_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(dependent_id)
            conn.execute(f"UPDATE dependents SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM dependents WHERE id = ?", (dependent_id,)).fetchone()
        return _dependent_out(row_to_dict(row))


def delete_dependent(dependent_id: str) -> bool:
    """Delete a dependent and cascade-delete its care_items (done in Python since
    care_items has no FK ON DELETE CASCADE)."""
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM dependents WHERE id = ?", (dependent_id,)).fetchone():
            return False
        conn.execute("DELETE FROM care_items WHERE dependent_id = ?", (dependent_id,))
        conn.execute("DELETE FROM dependents WHERE id = ?", (dependent_id,))
        return True


# --- Care items (per-dependent health/care schedule) ---

def _care_item_out(r: dict) -> dict:
    dependent = get_dependent(r["dependent_id"])
    return {
        "id": r["id"],
        "dependent_id": r["dependent_id"],
        "dependent_name": dependent["name"] if dependent else None,
        "title": r["title"],
        "category": r["category"],
        "due_date": r.get("due_date"),
        "done": bool(r["done"]),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_care_items(dependent_id: Optional[str] = None) -> list[dict]:
    """All care items, or just one dependent's. NULL-due items sort last, then by
    due_date, then title."""
    with get_conn() as conn:
        if dependent_id:
            rows = conn.execute(
                "SELECT * FROM care_items WHERE dependent_id = ? ORDER BY (due_date IS NULL), due_date, title",
                (dependent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM care_items ORDER BY (due_date IS NULL), due_date, title"
            ).fetchall()
        return [_care_item_out(row_to_dict(r)) for r in rows]


def get_care_item(item_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM care_items WHERE id = ?", (item_id,)).fetchone()
        return _care_item_out(row_to_dict(row)) if row else None


def create_care_item(data: dict) -> dict:
    cid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO care_items
                   (id, dependent_id, title, category, due_date, done, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                data["dependent_id"],
                data["title"].strip(),
                data.get("category") or "other",
                data.get("due_date"),
                1 if data.get("done") else 0,
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM care_items WHERE id = ?", (cid,)).fetchone()
        return _care_item_out(row_to_dict(row))


def update_care_item(item_id: str, data: dict) -> Optional[dict]:
    """Partial update. `due_date` uses presence (`key in data`) so it can be
    cleared to NULL; `notes` coerces None to '' to honour its NOT NULL
    constraint; `done` is coerced to 0/1."""
    fields, values = [], []
    if data.get("dependent_id") is not None:
        fields.append("dependent_id = ?")
        values.append(data["dependent_id"])
    if data.get("title") is not None:
        fields.append("title = ?")
        values.append(data["title"].strip())
    if data.get("category") is not None:
        fields.append("category = ?")
        values.append(data["category"])
    if "due_date" in data:
        fields.append("due_date = ?")
        values.append(data["due_date"])
    if "done" in data and data["done"] is not None:
        fields.append("done = ?")
        values.append(1 if data["done"] else 0)
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM care_items WHERE id = ?", (item_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(item_id)
            conn.execute(f"UPDATE care_items SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM care_items WHERE id = ?", (item_id,)).fetchone()
        return _care_item_out(row_to_dict(row))


def delete_care_item(item_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM care_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


def care_due_within(days: int) -> list[dict]:
    """Not-done care items whose due_date falls within `days` from today. Mirrors
    documents_expiring_within/inventory_expiring_within: includes ones that
    lapsed at most 1 day ago (a small grace window) but nothing older, so a
    reminder can still fire the day something is due."""
    today = date.today()
    horizon = today + timedelta(days=days)
    floor = today - timedelta(days=1)
    out: list[dict] = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM care_items WHERE done = 0 AND due_date IS NOT NULL AND due_date != '' ORDER BY due_date, title"
        ).fetchall()
        for r in rows:
            d = row_to_dict(r)
            try:
                due = date.fromisoformat(str(d["due_date"])[:10])
            except (TypeError, ValueError):
                continue
            if floor <= due <= horizon:
                out.append(_care_item_out(d))
    return out


# --- Wishlist (gift ideas per person) ---

def _wishlist_item_out(r: dict) -> dict:
    price = r.get("price")
    return {
        "id": r["id"],
        "person": r.get("person"),
        "title": r["title"],
        "url": r.get("url"),
        "price": float(price) if price is not None else None,
        "notes": r["notes"],
        "purchased": bool(r["purchased"]),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_wishlist_items(person: Optional[str] = None) -> list[dict]:
    """All wishlist items, or just one person's. Unpurchased first, then by
    person and title."""
    with get_conn() as conn:
        if person is not None:
            rows = conn.execute(
                "SELECT * FROM wishlist_items WHERE person = ? ORDER BY purchased ASC, person, title",
                (person,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM wishlist_items ORDER BY purchased ASC, person, title"
            ).fetchall()
        return [_wishlist_item_out(row_to_dict(r)) for r in rows]


def get_wishlist_item(item_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM wishlist_items WHERE id = ?", (item_id,)).fetchone()
        return _wishlist_item_out(row_to_dict(row)) if row else None


def create_wishlist_item(data: dict) -> dict:
    wid = _new_id()
    now = _utcnow()
    price = data.get("price")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO wishlist_items
                   (id, person, title, url, price, notes, purchased, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                wid,
                data.get("person"),
                data["title"].strip(),
                data.get("url"),
                float(price) if price is not None else None,
                data.get("notes") or "",
                1 if data.get("purchased") else 0,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM wishlist_items WHERE id = ?", (wid,)).fetchone()
        return _wishlist_item_out(row_to_dict(row))


def update_wishlist_item(item_id: str, data: dict) -> Optional[dict]:
    """Partial update. The nullable fields (person/url/price) use presence
    (`key in data`) so they can be cleared to NULL; `notes` coerces None to ''
    to honour its NOT NULL constraint; `purchased` is coerced to 0/1."""
    fields, values = [], []
    if data.get("title") is not None:
        fields.append("title = ?")
        values.append(data["title"].strip())
    for key in ("person", "url"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "price" in data:
        fields.append("price = ?")
        values.append(float(data["price"]) if data["price"] is not None else None)
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    if "purchased" in data and data["purchased"] is not None:
        fields.append("purchased = ?")
        values.append(1 if data["purchased"] else 0)
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM wishlist_items WHERE id = ?", (item_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(item_id)
            conn.execute(f"UPDATE wishlist_items SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM wishlist_items WHERE id = ?", (item_id,)).fetchone()
        return _wishlist_item_out(row_to_dict(row))


def delete_wishlist_item(item_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM wishlist_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


# --- Vehicles (MOT/tax/insurance/service tracker) ---

def _vehicle_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "reg": r.get("reg"),
        "make": r.get("make"),
        "model": r.get("model"),
        "mot_due": r.get("mot_due"),
        "tax_due": r.get("tax_due"),
        "insurance_due": r.get("insurance_due"),
        "service_due": r.get("service_due"),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_vehicles() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM vehicles ORDER BY name").fetchall()
        return [_vehicle_out(row_to_dict(r)) for r in rows]


def get_vehicle(vehicle_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        return _vehicle_out(row_to_dict(row)) if row else None


def create_vehicle(data: dict) -> dict:
    vid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO vehicles
                   (id, name, reg, make, model, mot_due, tax_due, insurance_due, service_due, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vid,
                data["name"].strip(),
                data.get("reg"),
                data.get("make"),
                data.get("model"),
                data.get("mot_due"),
                data.get("tax_due"),
                data.get("insurance_due"),
                data.get("service_due"),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vid,)).fetchone()
        return _vehicle_out(row_to_dict(row))


def update_vehicle(vehicle_id: str, data: dict) -> Optional[dict]:
    """Partial update. The nullable fields (reg/make/model and the four *_due
    dates) use presence (`key in data`) so they can be cleared to NULL; `notes`
    coerces None to '' to honour its NOT NULL constraint."""
    fields, values = [], []
    if data.get("name") is not None:
        name = data["name"].strip()
        if name:  # never blank the required name via PATCH
            fields.append("name = ?")
            values.append(name)
    for key in ("reg", "make", "model", "mot_due", "tax_due", "insurance_due", "service_due"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(vehicle_id)
            conn.execute(f"UPDATE vehicles SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        return _vehicle_out(row_to_dict(row))


def delete_vehicle(vehicle_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
        return cur.rowcount > 0


def vehicles_due_within(days: int) -> list[dict]:
    """For each vehicle, one entry per due field (MOT/Tax/Insurance/Service) that
    is set and whose date falls within `days` from today, so a single vehicle can
    yield up to four entries. Mirrors documents_expiring_within: includes ones that
    lapsed at most 1 day ago (a small grace window) but nothing older, so a
    reminder can still fire the day something is due. Ordered by due_date."""
    today = date.today()
    horizon = today + timedelta(days=days)
    floor = today - timedelta(days=1)
    kinds = [
        ("mot_due", "MOT"),
        ("tax_due", "Tax"),
        ("insurance_due", "Insurance"),
        ("service_due", "Service"),
    ]
    out: list[dict] = []
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM vehicles ORDER BY name").fetchall()
        for r in rows:
            d = row_to_dict(r)
            for col, kind in kinds:
                raw = d.get(col)
                if not raw:
                    continue
                try:
                    due = date.fromisoformat(str(raw)[:10])
                except (TypeError, ValueError):
                    continue
                if floor <= due <= horizon:
                    out.append({
                        "vehicle_id": d["id"],
                        "name": d["name"],
                        "reg": d.get("reg"),
                        "kind": kind,
                        "due_date": raw,
                    })
    out.sort(key=lambda e: e["due_date"])
    return out


# --- Trip itinerary ---

def _itinerary_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "trip_id": r["trip_id"],
        "day_date": r.get("day_date"),
        "start_time": r.get("start_time"),
        "kind": r["kind"],
        "title": r["title"],
        "location": r.get("location"),
        "notes": r["notes"],
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


def list_itinerary(trip_id: str) -> list[dict]:
    """A trip's itinerary. Undated items sort last; within a day, timed items come
    first in time order, then untimed items by insertion order."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM itinerary_items WHERE trip_id = ?
               ORDER BY (day_date IS NULL), day_date, (start_time IS NULL), start_time, created_at""",
            (trip_id,),
        ).fetchall()
        return [_itinerary_out(row_to_dict(r)) for r in rows]


def get_itinerary_item(item_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM itinerary_items WHERE id = ?", (item_id,)).fetchone()
        return _itinerary_out(row_to_dict(row)) if row else None


def create_itinerary_item(data: dict) -> dict:
    iid = _new_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO itinerary_items
                   (id, trip_id, day_date, start_time, kind, title, location, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                iid,
                data["trip_id"],
                data.get("day_date"),
                data.get("start_time"),
                data.get("kind") or "activity",
                data["title"].strip(),
                data.get("location"),
                data.get("notes") or "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM itinerary_items WHERE id = ?", (iid,)).fetchone()
        return _itinerary_out(row_to_dict(row))


def update_itinerary_item(item_id: str, data: dict) -> Optional[dict]:
    """Partial update. The nullable fields (day_date/start_time/location) use
    presence (`key in data`) so they can be cleared to NULL; `notes` coerces None
    to '' to honour its NOT NULL constraint; `title`/`kind` are never blanked."""
    fields, values = [], []
    if data.get("title") is not None:
        title = data["title"].strip()
        if title:  # never blank the required title via PATCH
            fields.append("title = ?")
            values.append(title)
    if data.get("kind") is not None:
        fields.append("kind = ?")
        values.append(data["kind"])
    for key in ("day_date", "start_time", "location"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"] if data["notes"] is not None else "")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM itinerary_items WHERE id = ?", (item_id,)).fetchone():
            return None
        if fields:
            fields.append("updated_at = ?")
            values.append(_utcnow())
            values.append(item_id)
            conn.execute(f"UPDATE itinerary_items SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM itinerary_items WHERE id = ?", (item_id,)).fetchone()
        return _itinerary_out(row_to_dict(row))


def delete_itinerary_item(item_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM itinerary_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0
