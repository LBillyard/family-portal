"""SQLite persistence for Family Portal."""

import base64
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("FAMILY_PORTAL_DB") or (Path(__file__).parent.parent / "data" / "family.db"))


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
            FOREIGN KEY (trip_id) REFERENCES holiday_trips(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )"""
    )
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

    netflix_count = conn.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE description LIKE '%NETFLIX%'"
    ).fetchone()["c"]
    account_ids = [r[0] for r in conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()]
    if netflix_count == 0 and account_ids:
        now = _utcnow()
        recurring = [
            ("NETFLIX.COM", "Subscriptions", -17.99),
            ("SPOTIFY PREMIUM", "Subscriptions", -10.99),
            ("DISNEY PLUS", "Subscriptions", -7.99),
            ("AMAZON PRIME", "Subscriptions", -8.99),
        ]
        for month in range(1, 7):
            pay = f"2026-{month:02d}-15"
            for i, (desc, cat, amt) in enumerate(recurring):
                acct = account_ids[i % len(account_ids)]
                conn.execute(
                    "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_new_id(), acct, desc, cat, amt, pay, now),
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

    maint_count = conn.execute("SELECT COUNT(*) AS c FROM maintenance_items").fetchone()["c"]
    if maint_count == 0:
        now = _utcnow()
        seed_maint = [
            ("Boiler service", "heating", "2025-09-01", "2026-09-01", 12, "British Gas", "Annual service"),
            ("Gutter clearing", "exterior", "2025-11-01", "2026-11-01", 12, "Local roofer", ""),
            ("Washing machine warranty", "appliance", "", "2027-03-01", 0, "Currys", "Extended warranty"),
        ]
        for title, cat, last_d, next_d, interval, vendor, notes in seed_maint:
            conn.execute(
                """INSERT INTO maintenance_items
                   (id, title, category, last_service_date, next_due_date, interval_months, vendor, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id(), title, cat, last_d, next_d, interval, vendor, notes, now),
            )


def _seed(conn: sqlite3.Connection) -> None:
    from server.auth import hash_password

    users = [
        ("luke", "lbillyard@gmail.com", "Luke", "#00a89e"),
        ("partner", "lebillyard@gmail.com", "Laura", "#243a5e"),
    ]
    pw = hash_password("family123")
    now = _utcnow()
    for uid, email, name, colour in users:
        conn.execute(
            "INSERT INTO users (id, email, name, password_hash, colour, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, email, name, pw, colour, now),
        )

    accounts = [
        ("starling", "Starling", "current", 0, "Starling Bank"),
        ("revolut", "Revolut", "current", 0, "Revolut"),
        ("amex", "American Express", "credit", 0, "American Express"),
        ("virgin_cc", "Virgin credit card", "credit", 0, "Virgin Money"),
    ]
    for aid, name, typ, bal, inst in accounts:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, name, typ, bal, inst),
        )

    for cat, limit in [("Groceries", 400), ("Eating out", 150), ("Transport", 200), ("Entertainment", 80), ("Shopping", 120)]:
        conn.execute("INSERT INTO budgets (id, category, monthly_limit) VALUES (?, ?, ?)", (_new_id(), cat, limit))

    for name, target, current, colour in [("Holiday fund", 3000, 2100, "#00a89e"), ("Emergency buffer", 10000, 7850, "#243a5e")]:
        conn.execute(
            "INSERT INTO savings_goals (id, name, target, current, colour) VALUES (?, ?, ?, ?, ?)",
            (_new_id(), name, target, current, colour),
        )

    bills = [
        ("Mortgage", 1245.0, 1, "Housing", 1),
        ("Council tax", 186.0, 15, "Housing", 0),
        ("Energy (Octopus)", 142.5, 22, "Utilities", 0),
        ("Netflix", 17.99, 28, "Subscriptions", 0),
        ("Car insurance", 48.0, 5, "Transport", 1),
        ("Broadband", 34.99, 18, "Utilities", 0),
    ]
    for name, amt, day, cat, paid in bills:
        conn.execute(
            "INSERT INTO bills (id, name, amount, due_day, category, paid) VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id(), name, amt, day, cat, paid),
        )

    txns = [
        ("starling", "Weekly shop — Tesco", "Groceries", -87.42, "2026-07-03"),
        ("revolut", "Salary", "Income", 3200.0, "2026-07-02"),
        ("starling", "Petrol", "Transport", -54.2, "2026-07-01"),
        ("amex", "Restaurant", "Eating out", -62.0, "2026-06-30"),
        ("revolut", "Transfer in", "Income", 2800.0, "2026-06-28"),
    ]
    for acct, desc, cat, amt, d in txns:
        conn.execute(
            "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_new_id(), acct, desc, cat, amt, d, now),
        )

    recurring = [
        ("starling", "NETFLIX.COM", "Subscriptions", -17.99),
        ("starling", "SPOTIFY PREMIUM", "Subscriptions", -10.99),
        ("amex", "DISNEY PLUS", "Subscriptions", -7.99),
        ("revolut", "AMAZON PRIME", "Subscriptions", -8.99),
        ("starling", "OCTOPUS ENERGY", "Utilities", -142.50),
    ]
    for month in range(1, 7):
        pay = f"2026-{month:02d}-15"
        for acct, desc, cat, amt in recurring:
            conn.execute(
                "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_new_id(), acct, desc, cat, amt, pay, now),
            )

    tasks = [
        ("Book Portugal airport parking", "luke", "2026-07-10", 0, "high"),
        ("Renew home insurance quote", "partner", "2026-07-20", 0, "medium"),
        ("Sort summer wardrobe", "partner", "2026-07-15", 1, "low"),
        ("Pay council tax", "luke", "2026-07-15", 0, "high"),
    ]
    for title, assignee, due, done, pri in tasks:
        conn.execute(
            "INSERT INTO tasks (id, title, assignee_id, due_date, done, priority, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_new_id(), title, assignee, due, done, pri, now),
        )

    events = [
        ("luke", "Team standup", "2026-07-07T09:00:00", "2026-07-07T09:30:00", 0, "google", "Zoom"),
        ("partner", "Dentist — 6-month check", "2026-07-08T14:00:00", "2026-07-08T15:00:00", 0, "portal", "Smile Dental"),
        ("luke", "Date night", "2026-07-11T19:00:00", "2026-07-11T23:00:00", 0, "portal", "The Ivy"),
        ("luke", "Portugal holiday", "2026-08-15", "2026-08-22", 1, "portal", "Algarve"),
        ("partner", "Gym", "2026-07-07T18:00:00", "2026-07-07T19:00:00", 0, "google", "PureGym"),
    ]
    for uid, title, start, end, all_day, source, loc in events:
        conn.execute(
            """INSERT INTO events (id, user_id, title, start_at, end_at, all_day, source, location, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_new_id(), uid, title, start, end, all_day, source, loc, now),
        )

    appts = [
        ("luke", "GP — prescription review", "Oakwood Medical Centre", "2026-07-14T10:30:00", "health", "12 Oak Lane", 2),
        ("partner", "Dentist — check-up", "Smile Dental", "2026-07-08T14:00:00", "dental", "High Street", 1),
        ("luke", "Car MOT", "Kwik Fit", "2026-07-25T08:30:00", "car", "Retail Park", 7),
    ]
    for uid, title, prov, dt, cat, loc, rem in appts:
        conn.execute(
            """INSERT INTO appointments (id, user_id, title, provider, datetime, category, location, reminder_days, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_new_id(), uid, title, prov, dt, cat, loc, rem, now),
        )

    trip_id = _new_id()
    conn.execute(
        "INSERT INTO holiday_trips (id, title, status, start_date, end_date, budget, spent) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trip_id, "Algarve, Portugal", "booked", "2026-08-15", "2026-08-22", 2400, 1850),
    )
    for i, (label, done) in enumerate([
        ("Flights booked", 1), ("Hotel confirmed", 1), ("Travel insurance", 1),
        ("Airport parking", 0), ("Pack sun cream", 0),
    ]):
        conn.execute(
            "INSERT INTO holiday_checklist (id, trip_id, label, done, sort_order) VALUES (?, ?, ?, ?, ?)",
            (_new_id(), trip_id, label, done, i),
        )

    conn.execute(
        "INSERT INTO holiday_trips (id, title, status, budget, spent) VALUES (?, ?, ?, ?, ?)",
        (_new_id(), "City break — Prague?", "idea", 800, 0),
    )
    conn.execute(
        "INSERT INTO holiday_trips (id, title, status, start_date, end_date, budget, spent) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_new_id(), "Lake District weekend", "planning", "2026-09-12", "2026-09-14", 450, 120),
    )

    ideas = [
        ("Santorini, Greece", "7 nights, boutique hotel, flights from £680pp.", 2200, 1, '["Beach","Romantic"]'),
        ("Edinburgh Fringe weekend", "Train from home, central Airbnb, 3 days of shows.", 550, 0, '["City","Culture"]'),
    ]
    for dest, summary, est, saved, tags in ideas:
        conn.execute(
            "INSERT INTO holiday_ideas (id, destination, summary, budget_estimate, saved, tags_json) VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id(), dest, summary, est, saved, tags),
        )

    docs = [
        ("Luke passport", "passport", "2027-03-14", "ok", ""),
        ("Partner passport", "passport", "2026-11-02", "renew_soon", ""),
        ("Home insurance", "insurance", "2026-08-01", "renew_soon", "Buildings & contents"),
        ("Car MOT certificate", "mot", "2027-01-25", "ok", ""),
    ]
    for name, category, expiry, status, notes in docs:
        conn.execute(
            """INSERT INTO documents (id, name, category, expiry, status, notes, file_size)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (_new_id(), name, category, expiry, status, notes),
        )

    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("google_last_sync", "3 min ago"))


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
    return {
        "id": u["id"],
        "name": u["name"],
        "email": u["email"],
        "colour": u["colour"],
        "phone": u.get("phone"),
        "google_connected": bool(u.get("google_token_json")),
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


def update_event(event_id: str, data: dict) -> Optional[dict]:
    mapping = {"title": "title", "start": "start_at", "end": "end_at", "location": "location", "user_id": "user_id"}
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

def list_bills() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM bills ORDER BY due_day").fetchall()
        return [_bill_out(row_to_dict(r)) for r in rows]


def create_bill(data: dict) -> dict:
    bid = _new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bills (id, name, amount, due_day, recurrence, category, paid) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (bid, data["name"], data["amount"], data["due_day"], data.get("recurrence", "monthly"), data.get("category", "Other")),
        )
        row = conn.execute("SELECT * FROM bills WHERE id = ?", (bid,)).fetchone()
        return _bill_out(row_to_dict(row))


def mark_bill_paid(bill_id: str) -> Optional[dict]:
    with get_conn() as conn:
        conn.execute("UPDATE bills SET paid = 1, paid_at = ? WHERE id = ?", (_utcnow(), bill_id))
        row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        return _bill_out(row_to_dict(row)) if row else None


def delete_bill(bill_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        return cur.rowcount > 0


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
    account_id = data.get("account_id") or "joint"
    amount = float(data["amount"])
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, account_id, data["description"], data["category"], amount, txn_date, now),
        )
        conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id))
        row = conn.execute(
            """SELECT t.*, a.name AS account_name FROM transactions t
               LEFT JOIN accounts a ON a.id = t.account_id WHERE t.id = ?""",
            (tid,),
        ).fetchone()
        return _txn_out(row_to_dict(row))


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
    }


def get_transaction(txn_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        return row_to_dict(row) if row else None


# --- Accounts & budgets ---

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


def list_savings_goals() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM savings_goals ORDER BY name").fetchall()
        return [row_to_dict(r) for r in rows]


def finance_summary() -> dict:
    month_prefix = date.today().strftime("%Y-%m")
    with get_conn() as conn:
        income = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions WHERE amount > 0 AND txn_date LIKE ?",
            (f"{month_prefix}%",),
        ).fetchone()["s"]
        spent = conn.execute(
            "SELECT COALESCE(SUM(ABS(amount)), 0) AS s FROM transactions WHERE amount < 0 AND txn_date LIKE ?",
            (f"{month_prefix}%",),
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
            "INSERT INTO tasks (id, title, assignee_id, due_date, priority, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tid, data["title"], data.get("assignee_id"), data.get("due"), data.get("priority", "medium"), now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        return _task_out(row_to_dict(row))


def delete_task(task_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0


def update_task(task_id: str, data: dict) -> Optional[dict]:
    with get_conn() as conn:
        if "done" in data:
            conn.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(data["done"]), task_id))
        if data.get("title"):
            conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (data["title"], task_id))
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_out(row_to_dict(row)) if row else None


def _task_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "assignee": r["assignee_id"],
        "due": r["due_date"],
        "done": bool(r["done"]),
        "priority": r["priority"],
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
                "SELECT label, done, item_type FROM holiday_checklist WHERE trip_id = ? ORDER BY sort_order",
                (d["id"],),
            ).fetchall()
            checklist_items = []
            packing_items = []
            for c in checklist:
                item = {"label": c["label"], "done": bool(c["done"])}
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
    fields = []
    values = []
    for key, col in colmap.items():
        if data.get(key) is not None:
            fields.append(f"{col} = ?")
            values.append(data[key])
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM holiday_trips WHERE id = ?", (trip_id,)).fetchone():
            return None
        if fields:
            values.append(trip_id)
            conn.execute(f"UPDATE holiday_trips SET {', '.join(fields)} WHERE id = ?", values)
    return next((t for t in list_trips() if t["id"] == trip_id), None)


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
               (id, name, category, expiry, status, notes, file_name, file_path, mime_type, file_size, uploaded_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
        return _document_out(row_to_dict(row))


def delete_document(doc_id: str) -> Optional[str]:
    """Delete document row; returns stored file_path for filesystem cleanup."""
    with get_conn() as conn:
        row = conn.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return row["file_path"]


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
            conn.execute(
                """INSERT INTO transactions (id, account_id, description, category, amount, txn_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tid, row.get("account_id", "joint"), row["description"], row.get("category", "Imported"),
                 row["amount"], row["date"], now),
            )
            conn.execute(
                "UPDATE accounts SET balance = balance + ? WHERE id = ?",
                (row["amount"], row.get("account_id", "joint")),
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
               (id, title, caption, media_type, trip_id, file_name, file_path, mime_type, file_size, taken_at, uploaded_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                conn.execute(
                    """UPDATE subscriptions SET display_name = ?, amount = ?, frequency = ?,
                       last_charge_date = ?, next_expected_date = ?, occurrence_count = ?,
                       account = ?, category = ?, updated_at = ?
                       WHERE merchant_key = ?""",
                    (
                        d["display_name"],
                        d["amount"],
                        d["frequency"],
                        d.get("last_charge_date"),
                        d.get("next_expected_date"),
                        d["occurrence_count"],
                        d.get("account", ""),
                        d.get("category", "Subscriptions"),
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
            "SELECT COUNT(*) AS c FROM holiday_checklist WHERE trip_id = ? AND item_type = 'packing'",
            (trip_id,),
        ).fetchone()["c"]
        start_order = existing
        for i, label in enumerate(labels):
            conn.execute(
                """INSERT INTO holiday_checklist (id, trip_id, label, done, sort_order, item_type)
                   VALUES (?, ?, ?, 0, ?, 'packing')""",
                (_new_id(), trip_id, label, start_order + i),
            )
    trip = get_trip_detail(trip_id)
    return trip.get("packing", []) if trip else []


def toggle_checklist_item(trip_id: str, label: str, item_type: str = "checklist") -> bool:
    with get_conn() as conn:
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
