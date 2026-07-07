"""Wave-16 backend: persistent, deduplicated inbox SUGGESTIONS.

Covers the whole stack of the "we spotted this in your email — add it?" layer:

1. db.create_suggestion idempotency on (user_id, dedupe_key) — a re-insert of the
   same key makes NO second row and returns None, and a dismissed suggestion is
   NOT resurrected by a re-insert.
2. The rest of the DB helpers: list_suggestions(status=...), get_suggestion,
   set_suggestion_status, count_pending_suggestions, delete_suggestion.
3. The routes: GET /api/inbox/suggestions, PATCH accept (files the underlying
   trip/appointment/document/bill AND flips status to accepted), PATCH dismiss
   (status dismissed, creates nothing), 404 on an unknown id.
4. inbox_actions.apply_suggestion — each kind files the right row.
5. inbox_actions.scan_and_store — Gmail/AI fully mocked (NO network): canned
   candidates get stored and deduped across scans.
6. The proactive_inbox notification pref round-trips via get/update.

Isolation: the suggestions table is shared on a session-scoped DB, so DB-level
tests tag their rows with a throwaway user_id (any text is allowed) and clean up
in a finally; route/apply tests use unique titles and delete every row they file.
"""

import asyncio
import uuid

import pytest

from server import database as db
from server.services import inbox_actions


# --- helpers ---------------------------------------------------------------

def _uid() -> str:
    """A throwaway user_id so count/list-by-user are isolated from other tests."""
    return f"wave16-user-{uuid.uuid4().hex}"


def _mk_suggestion(kind, title, *, payload=None, user_id=None, dedupe_key=None):
    return db.create_suggestion({
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "summary": "test summary",
        "payload": payload or {},
        "source_subject": "Test subject",
        "source_message_id": "",
        "dedupe_key": dedupe_key or f"{kind}:{uuid.uuid4().hex}",
    })


# Per-kind apply payloads + the table the row lands in.
_APPLY_PAYLOADS = {
    "trip": {"destination": "Rome", "start": "2026-10-01", "end": "2026-10-05"},
    "appointment": {"provider": "Dr Smith", "datetime": "2026-09-01T10:00", "category": "health"},
    "document": {"expiry_date": "2027-01-01", "notes": "Passport renewal"},
    "bill": {"amount": 9.99, "due_day": 15, "recurrence": "monthly", "category": "Streaming"},
}


def _find_row(kind, title):
    if kind == "trip":
        return next((t for t in db.list_trips() if t["title"] == title), None)
    if kind == "appointment":
        return next((a for a in db.list_appointments() if a["title"] == title), None)
    if kind == "document":
        return next((d for d in db.list_documents() if d["name"] == title), None)
    if kind == "bill":
        return next((b for b in db.list_bills() if b["name"] == title), None)
    raise AssertionError(kind)


def _delete_row(kind, row_id):
    if kind == "trip":
        db.delete_trip(row_id)
    elif kind == "appointment":
        db.delete_appointment(row_id)
    elif kind == "document":
        db.delete_document(row_id)
    elif kind == "bill":
        db.delete_bill(row_id)


# --- (1) create_suggestion idempotency -------------------------------------

def test_create_suggestion_idempotent_same_key_makes_one_row():
    uid = _uid()
    key = f"trip:{uuid.uuid4().hex}"
    first = _mk_suggestion("trip", "Flights to Barcelona", user_id=uid, dedupe_key=key)
    try:
        assert first is not None
        assert first["status"] == "pending"
        assert first["kind"] == "trip"
        assert first["dedupe_key"] == key

        # Same (user_id, dedupe_key) again -> no new row, returns None.
        second = _mk_suggestion("trip", "Flights to Barcelona (dupe)", user_id=uid, dedupe_key=key)
        assert second is None

        rows = db.list_suggestions(status=None, user_id=uid)
        assert len(rows) == 1, "re-insert must not create a 2nd row"
        # The original row is untouched (its title, not the dupe's).
        assert rows[0]["title"] == "Flights to Barcelona"
        assert rows[0]["id"] == first["id"]
    finally:
        db.delete_suggestion(first["id"])


def test_create_suggestion_dedupes_household_wide_across_users():
    # The same booking lands in both partners' inboxes; each member's scan tags it
    # with their own user_id but the SAME dedupe_key. It must surface only once.
    key = f"trip:{uuid.uuid4().hex}"
    luke = _mk_suggestion("trip", "Flights to Seville", user_id="luke", dedupe_key=key)
    partner = _mk_suggestion("trip", "Flights to Seville", user_id="partner", dedupe_key=key)
    try:
        assert luke is not None
        assert partner is None, "same key under a different user must not duplicate"
        assert len(db.list_suggestions(status=None)) >= 1
        matches = [r for r in db.list_suggestions(status=None) if r["dedupe_key"] == key]
        assert len(matches) == 1
    finally:
        db.delete_suggestion(luke["id"])


def test_create_suggestion_does_not_resurrect_dismissed():
    uid = _uid()
    key = f"appointment:{uuid.uuid4().hex}"
    row = _mk_suggestion("appointment", "Dentist", user_id=uid, dedupe_key=key)
    try:
        assert row is not None
        # Dismiss it, then re-scan surfaces the same key again.
        db.set_suggestion_status(row["id"], "dismissed")

        again = _mk_suggestion("appointment", "Dentist", user_id=uid, dedupe_key=key)
        assert again is None, "a dismissed suggestion must not be resurrected"

        # Still exactly one row, still dismissed (not flipped back to pending).
        rows = db.list_suggestions(status=None, user_id=uid)
        assert len(rows) == 1
        assert rows[0]["status"] == "dismissed"
        assert db.count_pending_suggestions(user_id=uid) == 0
    finally:
        db.delete_suggestion(row["id"])


# --- (2) list / get / set-status / count / delete --------------------------

def test_suggestion_crud_helpers():
    uid = _uid()
    row = _mk_suggestion("document", "Car insurance renewal", user_id=uid)
    sid = row["id"]
    try:
        # get
        got = db.get_suggestion(sid)
        assert got is not None and got["id"] == sid and got["status"] == "pending"

        # list by status + user
        pending = db.list_suggestions(status="pending", user_id=uid)
        assert [r["id"] for r in pending] == [sid]
        assert db.list_suggestions(status="accepted", user_id=uid) == []

        # count
        assert db.count_pending_suggestions(user_id=uid) == 1

        # set_suggestion_status flips it and drops it out of pending
        updated = db.set_suggestion_status(sid, "accepted")
        assert updated is not None and updated["status"] == "accepted"
        assert db.count_pending_suggestions(user_id=uid) == 0
        assert db.list_suggestions(status="pending", user_id=uid) == []
        assert [r["id"] for r in db.list_suggestions(status="accepted", user_id=uid)] == [sid]

        # unknown id -> None, not a crash
        assert db.set_suggestion_status(f"nope-{uuid.uuid4().hex}", "accepted") is None
        assert db.get_suggestion(f"nope-{uuid.uuid4().hex}") is None
    finally:
        db.delete_suggestion(sid)

    # delete really removes it, and a second delete reports False
    assert db.get_suggestion(sid) is None
    assert db.delete_suggestion(sid) is False


def test_list_suggestions_status_none_spans_all_statuses():
    uid = _uid()
    a = _mk_suggestion("trip", "Trip A", user_id=uid)
    b = _mk_suggestion("trip", "Trip B", user_id=uid)
    try:
        db.set_suggestion_status(b["id"], "dismissed")
        all_ids = {r["id"] for r in db.list_suggestions(status=None, user_id=uid)}
        assert all_ids == {a["id"], b["id"]}
        pending_ids = {r["id"] for r in db.list_suggestions(status="pending", user_id=uid)}
        assert pending_ids == {a["id"]}
    finally:
        db.delete_suggestion(a["id"])
        db.delete_suggestion(b["id"])


# --- (3) routes ------------------------------------------------------------

def test_route_list_suggestions_returns_pending(client):
    row = _mk_suggestion("trip", f"Route list {uuid.uuid4().hex[:6]}")
    try:
        resp = client.get("/api/inbox/suggestions")
        assert resp.status_code == 200, resp.text
        ids = {s["id"] for s in resp.json()["suggestions"]}
        assert row["id"] in ids
    finally:
        db.delete_suggestion(row["id"])


@pytest.mark.parametrize("kind", ["trip", "appointment", "document", "bill"])
def test_route_accept_files_row_and_flips_status(client, kind):
    title = f"Accept {kind} {uuid.uuid4().hex[:8]}"
    row = _mk_suggestion(kind, title, payload=_APPLY_PAYLOADS[kind])
    filed = None
    try:
        resp = client.patch(f"/api/inbox/suggestions/{row['id']}", json={"action": "accept"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["kind"] == kind

        # The underlying household record now exists.
        filed = _find_row(kind, title)
        assert filed is not None, f"accept must file a {kind} row"

        # And the suggestion itself is flipped to accepted (no longer pending).
        assert db.get_suggestion(row["id"])["status"] == "accepted"
    finally:
        if filed:
            _delete_row(kind, filed["id"])
        db.delete_suggestion(row["id"])


def test_route_dismiss_creates_nothing(client):
    title = f"Dismiss trip {uuid.uuid4().hex[:8]}"
    row = _mk_suggestion("trip", title, payload=_APPLY_PAYLOADS["trip"])
    try:
        resp = client.patch(f"/api/inbox/suggestions/{row['id']}", json={"action": "dismiss"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "dismissed"

        assert db.get_suggestion(row["id"])["status"] == "dismissed"
        # Nothing was filed.
        assert _find_row("trip", title) is None
    finally:
        db.delete_suggestion(row["id"])


def test_route_accept_unknown_id_404(client):
    resp = client.patch(
        f"/api/inbox/suggestions/nope-{uuid.uuid4().hex}", json={"action": "accept"}
    )
    assert resp.status_code == 404, resp.text


def test_route_dismiss_unknown_id_404(client):
    resp = client.patch(
        f"/api/inbox/suggestions/nope-{uuid.uuid4().hex}", json={"action": "dismiss"}
    )
    assert resp.status_code == 404, resp.text


# --- (4) inbox_actions.apply_suggestion, each kind -------------------------

@pytest.mark.parametrize("kind", ["trip", "appointment", "document", "bill"])
def test_apply_suggestion_files_each_kind(kind):
    title = f"Apply {kind} {uuid.uuid4().hex[:8]}"
    row = _mk_suggestion(kind, title, payload=_APPLY_PAYLOADS[kind])
    filed = None
    try:
        res = inbox_actions.apply_suggestion(row["id"])
        assert res == {"ok": True, "kind": kind}

        filed = _find_row(kind, title)
        assert filed is not None
        # Spot-check a payload field made it into the row.
        if kind == "trip":
            assert filed["destination"] == "Rome"
            assert filed["status"] == "booked"
        elif kind == "appointment":
            assert filed["datetime"] == "2026-09-01T10:00"
            assert filed["provider"] == "Dr Smith"
        elif kind == "document":
            assert filed["category"] == "personal"
        elif kind == "bill":
            assert filed["amount"] == 9.99
            assert filed["due_day"] == 15

        assert db.get_suggestion(row["id"])["status"] == "accepted"
    finally:
        if filed:
            _delete_row(kind, filed["id"])
        db.delete_suggestion(row["id"])


def test_apply_suggestion_unknown_id_is_graceful():
    res = inbox_actions.apply_suggestion(f"nope-{uuid.uuid4().hex}")
    assert res["ok"] is False
    assert "not found" in res["error"]


# --- (5) scan_and_store — Gmail/AI mocked, no network ----------------------

def _canned_scan_result():
    """Candidates as gmail_inbox.scan_for_items would hand them back, INCLUDING a
    duplicate trip (same normalised title) to prove storage-level dedup."""
    return {
        "candidates": [
            {"kind": "trip", "title": "Flights to Lisbon",
             "destination": "Lisbon", "start": "2026-08-01", "end": "2026-08-08"},
            {"kind": "appointment", "title": "Dentist check-up",
             "provider": "Dr Who", "datetime": "2026-08-15T09:00"},
            {"kind": "document", "title": "Passport renewal", "expiry_date": "2027-05-01"},
            # duplicate of the first (case/punctuation differ -> same dedupe key)
            {"kind": "trip", "title": "flights to LISBON!",
             "destination": "Lisbon", "start": "2026-08-01", "end": "2026-08-08"},
        ],
        "needs_reconnect": [],
        "scanned": 12,
    }


def test_scan_and_store_stores_and_dedupes(monkeypatch):
    uid = _uid()

    async def fake_scan(user_id, *a, **k):
        return _canned_scan_result()

    async def fake_bills(user_id):  # keep the optional bill pass off the network
        return []

    # Pretend a Google account is connected so scan_and_store doesn't short-circuit.
    monkeypatch.setattr(inbox_actions.db, "list_google_accounts", lambda *a, **k: [{"id": "acct1"}])
    monkeypatch.setattr(inbox_actions.gmail_inbox, "scan_for_items", fake_scan)
    monkeypatch.setattr(inbox_actions, "_detect_bills", fake_bills)

    try:
        res = asyncio.run(inbox_actions.scan_and_store(uid))
        assert res["no_account"] is False
        assert res["scanned"] == 12
        # 4 candidates in, 1 is a duplicate -> 3 fresh suggestions.
        assert res["new"] == 3

        stored = db.list_suggestions(status="pending", user_id=uid)
        assert len(stored) == 3
        assert {s["kind"] for s in stored} == {"trip", "appointment", "document"}
        # The trip suggestion carries the parsed payload from the candidate.
        trip = next(s for s in stored if s["kind"] == "trip")
        assert trip["payload"]["destination"] == "Lisbon"

        # A second identical scan surfaces NOTHING new (idempotent across scans).
        res2 = asyncio.run(inbox_actions.scan_and_store(uid))
        assert res2["new"] == 0
        assert len(db.list_suggestions(status="pending", user_id=uid)) == 3
    finally:
        for s in db.list_suggestions(status=None, user_id=uid):
            db.delete_suggestion(s["id"])


def test_scan_and_store_no_account_short_circuits(monkeypatch):
    monkeypatch.setattr(inbox_actions.db, "list_google_accounts", lambda *a, **k: [])

    called = {"scan": False}

    async def boom(*a, **k):  # must never be reached
        called["scan"] = True
        raise AssertionError("scan_for_items should not run without an account")

    monkeypatch.setattr(inbox_actions.gmail_inbox, "scan_for_items", boom)

    res = asyncio.run(inbox_actions.scan_and_store(_uid()))
    assert res == {"new": 0, "scanned": 0, "needs_reconnect": [], "no_account": True}
    assert called["scan"] is False


# --- (6) proactive_inbox pref round-trip -----------------------------------

def test_proactive_inbox_pref_roundtrips():
    original = db.get_notification_prefs()
    assert "proactive_inbox" in original
    assert isinstance(original["proactive_inbox"], bool)
    try:
        off = db.update_notification_prefs({"proactive_inbox": False})
        assert off["proactive_inbox"] is False
        assert db.get_notification_prefs()["proactive_inbox"] is False

        on = db.update_notification_prefs({"proactive_inbox": True})
        assert on["proactive_inbox"] is True
        assert db.get_notification_prefs()["proactive_inbox"] is True
    finally:
        db.update_notification_prefs({"proactive_inbox": original["proactive_inbox"]})
