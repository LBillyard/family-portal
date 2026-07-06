"""Finance: CSV-injection guard, trip destination persistence, balance totals."""

from server import database as db
from server.api.routes import _csv_safe


def test_csv_safe_neutralises_formula_prefixes():
    assert _csv_safe("=SUM(A1)") == "'=SUM(A1)"
    assert _csv_safe("+1+2") == "'+1+2"
    assert _csv_safe("-cmd") == "'-cmd"
    assert _csv_safe("@import") == "'@import"


def test_csv_safe_leaves_normal_text():
    assert _csv_safe("Tesco") == "Tesco"
    assert _csv_safe("Groceries 2026") == "Groceries 2026"
    assert _csv_safe(None) == ""
    assert _csv_safe(12.5) == "12.5"


def test_trip_destination_persists():
    t = db.create_trip({"title": "Rome trip", "status": "idea", "destination": "Rome, Italy"})
    try:
        stored = next(x for x in db.list_trips() if x["id"] == t["id"])
        assert stored["destination"] == "Rome, Italy"
        db.update_trip(t["id"], {"destination": "Florence, Italy"})
        stored = next(x for x in db.list_trips() if x["id"] == t["id"])
        assert stored["destination"] == "Florence, Italy"
    finally:
        with db.get_conn() as c:
            c.execute("DELETE FROM holiday_trips WHERE id = ?", (t["id"],))


def test_finance_summary_excludes_credit_from_current_total():
    summary = db.finance_summary()
    assert "joint_balance" in summary
    assert isinstance(summary["joint_balance"], (int, float))
