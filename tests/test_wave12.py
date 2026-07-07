"""Wave-12 backend: cashflow forecast + per-person spend tagging.

Covers:
- services/cashflow.build_forecast(): returns the documented keys with numeric
  values, is internally consistent, never raises (loaded DB), and matches the
  GET /api/finances/forecast route.
- transactions.person: db.set_transaction_person(), db.spend_by_person(month),
  and _txn_out() surfacing `person` on the ledger rows.
- routes: GET /api/finances/forecast, GET /api/finances/by-person, and
  PATCH /api/transactions/{id}/person (luke/partner/joint/null valid, 400 on a
  bogus value, 404 on an unknown id, and null/''/'unassigned' clearing it).

The DB is shared across the whole test session, so each test seeds its own
account + transactions with a unique marker and tears every row down in a
finally. Person tagging is a brand-new column no other test touches, so the
'luke'/'partner'/'joint' buckets returned by spend_by_person() belong solely to
whichever test is running.
"""

import uuid
from datetime import date

from server import database as db
from server.services import cashflow

# --- documented forecast contract ------------------------------------------

_NUMERIC_KEYS = {
    "days_left",
    "current_cash",
    "spent_so_far",
    "avg_daily_spend",
    "projected_further_spend",
    "bills_due_remaining",
    "projected_month_end_cash",
}
_STRING_KEYS = {"as_of", "month_label"}
_ALL_KEYS = _NUMERIC_KEYS | _STRING_KEYS


# --- helpers ---------------------------------------------------------------

def _seed_account(balance: float = 500.0, acc_type: str = "current") -> str:
    aid = f"acc-w12-{uuid.uuid4().hex[:8]}"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, f"W12 {aid}", acc_type, balance, "Test Bank"),
        )
    return aid


def _mk_txn(account_id: str, amount: float, when: str | None = None, category: str = "Shopping") -> str:
    """Create a transaction (defaults to today, i.e. the current month) and
    return its id. Negative amounts are outgoings (counted by spend_by_person)."""
    row = db.create_transaction({
        "account_id": account_id,
        "description": f"W12 {uuid.uuid4().hex[:6]}",
        "category": category,
        "amount": amount,
        "date": when or date.today().isoformat(),
    })
    return row["id"]


def _cleanup(account_id: str, *txn_ids: str) -> None:
    for tid in txn_ids:
        try:
            db.delete_transaction(tid)
        except Exception:
            pass
    with db.get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def _by_person_map(items: list[dict]) -> dict:
    return {p["person"]: p["amount"] for p in items}


# --- build_forecast() contract ---------------------------------------------

def test_build_forecast_returns_documented_keys_and_types():
    fc = cashflow.build_forecast()  # must never raise on the loaded session DB
    assert set(fc.keys()) == _ALL_KEYS, fc

    for k in _NUMERIC_KEYS:
        assert isinstance(fc[k], (int, float)) and not isinstance(fc[k], bool), (k, fc[k])
    for k in _STRING_KEYS:
        assert isinstance(fc[k], str) and fc[k], (k, fc[k])

    # as_of is today; days_left is a sane in-month count.
    assert fc["as_of"] == date.today().isoformat()
    assert 0 <= fc["days_left"] <= 31

    # The headline number is exactly the documented combination of the parts.
    expected_end = round(
        fc["current_cash"] - fc["bills_due_remaining"] - fc["projected_further_spend"], 2
    )
    assert fc["projected_month_end_cash"] == expected_end

    # Deterministic within a run: two back-to-back calls agree.
    assert cashflow.build_forecast() == fc


def test_build_forecast_reflects_seeded_current_month_spend():
    """Adding current-month outgoings never makes the forecast raise and pushes
    spent_so_far up by (at least) what we added."""
    acc = _seed_account(balance=1000.0)
    t1 = t2 = None
    try:
        before = cashflow.build_forecast()["spent_so_far"]
        t1 = _mk_txn(acc, -40.0)
        t2 = _mk_txn(acc, -60.0)
        after = cashflow.build_forecast()
        assert set(after.keys()) == _ALL_KEYS
        # spent_so_far is ABS of current-month outgoings, so it grew by >= 100.
        assert after["spent_so_far"] >= round(before + 100.0, 2) - 0.001
    finally:
        _cleanup(acc, t1, t2)


# --- routes: forecast + by-person -------------------------------------------

def test_forecast_route_matches_service(client):
    r = client.get("/api/finances/forecast")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == _ALL_KEYS, body
    for k in _NUMERIC_KEYS:
        assert isinstance(body[k], (int, float))
    assert body["as_of"] == date.today().isoformat()


def test_by_person_route_reflects_split(client):
    """Seed two current-month outgoings, tag them via the PATCH route, and check
    GET /api/finances/by-person surfaces the per-person split."""
    acc = _seed_account()
    t_luke = t_joint = None
    try:
        t_luke = _mk_txn(acc, -30.0)
        t_joint = _mk_txn(acc, -70.0)

        # Untagged rows report as 'unassigned' (person NULL).
        pre = _by_person_map(client.get("/api/finances/by-person").json()["people"])
        assert pre.get("luke", 0) == 0 and pre.get("joint", 0) == 0

        # Tag through the ROUTE, and confirm the echoed transaction carries person.
        r1 = client.patch(f"/api/transactions/{t_luke}/person", json={"person": "luke"})
        assert r1.status_code == 200, r1.text
        assert r1.json()["transaction"]["person"] == "luke"
        r2 = client.patch(f"/api/transactions/{t_joint}/person", json={"person": "joint"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["transaction"]["person"] == "joint"

        people = _by_person_map(client.get("/api/finances/by-person").json()["people"])
        # luke/joint buckets are ours alone (no other test tags people).
        assert people["luke"] == 30.0, people
        assert people["joint"] == 70.0, people
    finally:
        _cleanup(acc, t_luke, t_joint)


# --- routes: PATCH person validation ---------------------------------------

def test_patch_person_accepts_each_valid_value(client):
    acc = _seed_account()
    tid = None
    try:
        tid = _mk_txn(acc, -12.0)
        for value in ("luke", "partner", "joint"):
            r = client.patch(f"/api/transactions/{tid}/person", json={"person": value})
            assert r.status_code == 200, r.text
            assert r.json()["transaction"]["person"] == value
            assert db.get_transaction(tid)["person"] == value
    finally:
        _cleanup(acc, tid)


def test_patch_person_invalid_value_returns_400(client):
    acc = _seed_account()
    tid = None
    try:
        tid = _mk_txn(acc, -15.0)
        client.patch(f"/api/transactions/{tid}/person", json={"person": "joint"})  # pre-set
        bad = client.patch(f"/api/transactions/{tid}/person", json={"person": "bogus"})
        assert bad.status_code == 400, bad.text
        # The rejected write left the previous value untouched.
        assert db.get_transaction(tid)["person"] == "joint"
    finally:
        _cleanup(acc, tid)


def test_patch_person_unknown_id_returns_404(client):
    r = client.patch("/api/transactions/does-not-exist/person", json={"person": "luke"})
    assert r.status_code == 404, r.text


def test_patch_person_null_and_sentinels_clear_it(client):
    """null, '' and 'unassigned' all clear the tag (200) and drop the row out of
    the person's bucket."""
    for clearing in (None, "", "unassigned"):
        acc = _seed_account()
        tid = None
        try:
            tid = _mk_txn(acc, -25.0)
            client.patch(f"/api/transactions/{tid}/person", json={"person": "luke"})
            assert db.get_transaction(tid)["person"] == "luke"

            r = client.patch(f"/api/transactions/{tid}/person", json={"person": clearing})
            assert r.status_code == 200, (clearing, r.text)
            assert r.json()["transaction"]["person"] is None
            assert db.get_transaction(tid)["person"] is None
        finally:
            _cleanup(acc, tid)


# --- db layer: set_transaction_person / spend_by_person / _txn_out ----------

def test_spend_by_person_db_splits_and_excludes_non_spend():
    """spend_by_person(month) groups ABS(outgoings) by person, omits income and
    hidden rows, and reports NULL person as 'unassigned'."""
    month = date.today().strftime("%Y-%m")
    day = f"{month}-15"
    acc = _seed_account()
    ids: list[str] = []
    try:
        # Baseline 'unassigned' (other tests may leave untagged current-month
        # rows); luke/joint buckets are ours alone so they can be asserted exact.
        base_unassigned = {p["person"]: p["amount"] for p in db.spend_by_person(month)}.get("unassigned", 0)

        luke = _mk_txn(acc, -100.0, when=day)
        joint = _mk_txn(acc, -40.0, when=day)
        untagged = _mk_txn(acc, -10.0, when=day)
        income = _mk_txn(acc, 3000.0, when=day, category="Income")  # positive -> excluded
        ids = [luke, joint, untagged, income]

        assert db.set_transaction_person(luke, "luke")["person"] == "luke"
        assert db.set_transaction_person(joint, "joint")["person"] == "joint"

        got = {p["person"]: p["amount"] for p in db.spend_by_person(month)}
        assert got.get("luke") == 100.0, got
        assert got.get("joint") == 40.0, got
        # Our untagged -10 lifts 'unassigned' by exactly 10; the +3000 income is
        # excluded (a positive amount), so the delta proves both at once.
        assert round(got.get("unassigned", 0) - base_unassigned, 2) == 10.0, got

        # Hiding the luke row removes it from the split entirely.
        with db.get_conn() as conn:
            conn.execute("UPDATE transactions SET hidden = 1 WHERE id = ?", (luke,))
        after = {p["person"]: p["amount"] for p in db.spend_by_person(month)}
        assert "luke" not in after, after
        assert after.get("joint") == 40.0

        # Unknown id -> None, no row created.
        assert db.set_transaction_person("nope-not-real", "luke") is None
    finally:
        _cleanup(acc, *ids)


def test_set_person_none_clears_and_txn_out_surfaces_person():
    acc = _seed_account()
    tid = None
    try:
        tid = _mk_txn(acc, -55.0)
        # Fresh rows expose person=None through _txn_out (via list_transactions).
        row = next(t for t in db.list_transactions(include_hidden=True) if t["id"] == tid)
        assert "person" in row and row["person"] is None

        db.set_transaction_person(tid, "partner")
        row = next(t for t in db.list_transactions(include_hidden=True) if t["id"] == tid)
        assert row["person"] == "partner"

        # Clearing back to None (sentinel path) sets NULL again.
        assert db.set_transaction_person(tid, None)["person"] is None
        assert db.get_transaction(tid)["person"] is None
    finally:
        _cleanup(acc, tid)
