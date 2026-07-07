"""Completion pass — asserts the real, changed behaviour of this build:

(a) Finance spend basis: insights / spend-trend / by-person EXCLUDE the
    NON_SPEND_CATEGORIES {Income,Transfers,Savings,Crypto} and anchor to the
    CURRENT calendar month; cashflow.current_cash is current-accounts-only and
    the forecast carries a `has_data` flag.
(b) Unified search (search.search_all) covers the newer entities
    (vehicles / occasions / recipes …).
(c) The assistant gained create_occasion / list_vehicle_renewals / list_care_due
    / get_shopping_list / get_meal_plan / add_wishlist_item, execute_tool runs
    them, and build_context surfaces the new sections.
(d) The WhatsApp digest mentions occasions + a money line; the renewal calendar
    includes vehicle (and care) items; an appointment with reminder_days=5 fires
    at 4 days out even though the global lead is 2.

The finance tests run against a THROW-AWAY database (db.DB_PATH is swapped to a
fresh temp file, db.init_db() rebuilds the schema, and DB_PATH is restored in a
finally) so the exact spend figures are immune to whatever the rest of the
shared session DB contains. Everything else seeds into the shared session DB
with unique markers and tears its rows down in a finally. No real network is
touched — the one outbound WhatsApp send in the reminders test is monkeypatched.
"""

import asyncio
import contextlib
import json
import tempfile
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from server import database as db
from server.services import assistant as assistant_svc
from server.services import briefing as briefing_svc
from server.services import cashflow
from server.services import insights as insights_svc
from server.services import renewals as renewals_svc
from server.services import reminders as reminders_svc
from server.services import search as search_svc
from server.services import whatsapp as whatsapp_svc


# ---------------------------------------------------------------------------
# Isolated-DB helper (finance tests only)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _isolated_db():
    """Point database.py at a brand-new empty DB for the duration of the block,
    then restore the real session DB. get_conn()/init_db() read the module-global
    DB_PATH at call time, so every service that goes through `db` follows."""
    original = db.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="familyportal-completion-")) / "iso.db"
    db.DB_PATH = tmp
    try:
        db.init_db()  # full schema (+ two seed users) in the fresh file
        yield
    finally:
        db.DB_PATH = original


def _add_account(name: str, acc_type: str, balance: float) -> str:
    aid = f"acc-cmp-{uuid.uuid4().hex[:8]}"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO accounts (id, name, type, balance, institution) VALUES (?, ?, ?, ?, ?)",
            (aid, name, acc_type, balance, "Test Bank"),
        )
    return aid


# ---------------------------------------------------------------------------
# (a) Finance — non-spend exclusion + current-month anchor + current_cash
# ---------------------------------------------------------------------------

def test_insights_and_spend_by_person_exclude_transfers():
    """A single Groceries -40 plus a Transfers -500/+500 pair in the current
    month: the spend headline is 40 (transfers excluded), the trailing-window
    trend's current month is 40, and spend_by_person shows unassigned=40 with no
    'Transfers' bucket and no +£500 inflation."""
    with _isolated_db():
        current = _add_account("Everyday", "current", 1000.0)
        savings = _add_account("Rainy Day", "savings", 5000.0)

        # Everyday spend this month (a real, counted outgoing).
        db.create_transaction({
            "account_id": current,
            "description": "Tesco groceries",
            "category": "Groceries",
            "amount": -40.0,
            "date": date.today().isoformat(),
        })
        # Internal shuffle: -500 out of current, +500 into savings, both 'Transfers'.
        db.create_transfer(current, savings, 500.0, description="Move to savings")

        ins = insights_svc.build_insights()
        assert ins["has_data"] is True
        # The £500 transfer legs are excluded -> spend is exactly the groceries.
        assert ins["this_month"]["spend"] == 40.0, ins["this_month"]
        # top_categories must not contain a Transfers bucket.
        assert all(c["category"] != "Transfers" for c in ins["top_categories"]), ins["top_categories"]

        # Spend-trend's window ends on the CURRENT calendar month; that month = 40.
        trend = insights_svc.build_spend_trend(months=3)
        current_month_key = date.today().strftime("%Y-%m")
        last = trend["months"][-1]
        assert last["key"] == current_month_key, trend["months"]
        assert last["spend"] == 40.0, trend["months"]

        # Per-person split: only the untagged groceries count -> unassigned 40.
        people = {p["person"]: p["amount"] for p in db.spend_by_person()}
        assert "Transfers" not in people, people
        assert people.get("unassigned") == 40.0, people          # not 40+500
        assert all(amt != 540.0 for amt in people.values()), people


def test_cashflow_current_cash_is_current_accounts_only_and_has_data():
    with _isolated_db():
        current = _add_account("Everyday", "current", 1200.0)
        _add_account("Rainy Day", "savings", 5000.0)
        db.create_transaction({
            "account_id": current,
            "description": "Coffee",
            "category": "Eating Out",
            "amount": -20.0,
            "date": date.today().isoformat(),
        })

        fc = cashflow.build_forecast()
        assert "has_data" in fc and fc["has_data"] is True

        accounts = db.list_accounts()
        expected_current = round(sum(a["balance"] for a in accounts if a["type"] == "current"), 2)
        total_all = round(sum(a["balance"] for a in accounts), 2)

        # current_cash tracks ONLY the current account(s) (1200 - 20 = 1180)...
        assert fc["current_cash"] == expected_current == 1180.0, (fc["current_cash"], accounts)
        # ...and deliberately leaves the £5000 savings balance out.
        assert fc["current_cash"] != total_all, (fc["current_cash"], total_all)


# ---------------------------------------------------------------------------
# (b) Unified search covers the new entity types
# ---------------------------------------------------------------------------

def test_search_all_covers_vehicles_occasions_recipes():
    marker = f"zqxw{uuid.uuid4().hex[:6]}"  # a token that matches nothing else
    veh = db.create_vehicle({"name": f"{marker} Van", "reg": "CMP123", "make": "Ford"})
    occ = db.create_occasion({"title": f"{marker} Birthday", "kind": "birthday", "date": "1990-05-05"})
    rec = db.create_recipe({"title": f"{marker} Curry", "ingredients": "spice", "tags": "dinner"})
    try:
        results = search_svc.search_all(marker)
        by_type = {r["type"] for r in results}
        assert {"vehicle", "occasion", "recipe"} <= by_type, results
        # Each matched result is the one we seeded.
        assert any(r["type"] == "vehicle" and r["id"] == veh["id"] for r in results), results
        assert any(r["type"] == "occasion" and r["id"] == occ["id"] for r in results), results
        assert any(r["type"] == "recipe" and r["id"] == rec["id"] for r in results), results
        # Uniform result shape the frontend routes on.
        for r in results:
            assert {"type", "title", "subtitle", "tab", "id"} <= set(r), r
    finally:
        db.delete_vehicle(veh["id"])
        db.delete_occasion(occ["id"])
        db.delete_recipe(rec["id"])


# ---------------------------------------------------------------------------
# (c) Assistant — new tools registered, executable, surfaced in context
# ---------------------------------------------------------------------------

_NEW_TOOLS = {
    "create_occasion",
    "list_vehicle_renewals",
    "list_care_due",
    "get_shopping_list",
    "get_meal_plan",
    "add_wishlist_item",
}


def _tool_names() -> set:
    return {t["function"]["name"] for t in assistant_svc.TOOLS}


def test_new_tool_names_registered():
    assert _NEW_TOOLS <= _tool_names(), sorted(_tool_names())


def test_execute_create_occasion_creates_one():
    user = db.get_user_by_email("lbillyard@gmail.com")
    title = f"AnnivCmp {uuid.uuid4().hex[:6]}"
    res = asyncio.run(assistant_svc.execute_tool(
        "create_occasion",
        {"title": title, "kind": "anniversary", "date": "2001-09-09", "person": "Laura"},
        user,
    ))
    occ_id = None
    try:
        assert res.get("ok") is True, res
        occ_id = res["occasion"]["id"]
        # It really landed in the DB.
        assert any(o["id"] == occ_id and o["title"] == title for o in db.list_occasions()), title
    finally:
        if occ_id:
            db.delete_occasion(occ_id)


def test_execute_get_shopping_list_returns_items():
    user = db.get_user_by_email("lbillyard@gmail.com")
    item = db.create_shopping_item(f"CmpMilk {uuid.uuid4().hex[:6]}")
    try:
        res = asyncio.run(assistant_svc.execute_tool("get_shopping_list", {}, user))
        assert "items" in res and isinstance(res["items"], list), res
        assert any(i["id"] == item["id"] for i in res["items"]), res
    finally:
        db.delete_shopping_item(item["id"])


def test_build_context_surfaces_new_sections():
    user = db.get_user_by_email("lbillyard@gmail.com")
    ctx = json.loads(assistant_svc.build_context(user))
    for key in ("upcoming_occasions", "vehicle_renewals", "care_due", "this_week_meals", "open_shopping"):
        assert key in ctx, list(ctx.keys())


# ---------------------------------------------------------------------------
# (d) Digest, renewal calendar, per-appointment reminder lead
# ---------------------------------------------------------------------------

def test_whatsapp_digest_mentions_occasions_and_money():
    user = db.get_user_by_email("lbillyard@gmail.com")
    occ_title = f"CmpParty {uuid.uuid4().hex[:6]}"
    soon = (date.today() + timedelta(days=3))
    occ = db.create_occasion({"title": occ_title, "kind": "birthday", "date": soon.isoformat()})
    bill = db.create_bill({"name": f"CmpBill {uuid.uuid4().hex[:6]}", "amount": 42.0,
                           "due_day": min(date.today().day, 28), "category": "Utilities"})
    try:
        line = briefing_svc.whatsapp_digest_line(user)
        assert isinstance(line, str) and line, line
        assert "\n" not in line and "\t" not in line   # single-line WhatsApp template var
        # Occasions section (🎂) names our occasion.
        assert "🎂" in line, line
        assert occ_title in line, line
        # A money line (💷) is present (unpaid bill guarantees the money snapshot).
        assert "💷" in line, line
    finally:
        db.delete_occasion(occ["id"])
        db.delete_bill(bill["id"])


def test_renewal_calendar_includes_vehicle_and_care():
    due = (date.today() + timedelta(days=10)).isoformat()
    veh = db.create_vehicle({"name": f"CmpCar {uuid.uuid4().hex[:6]}", "reg": "MOT99X", "mot_due": due})
    dep = db.create_dependent({"name": f"CmpKid {uuid.uuid4().hex[:6]}", "kind": "child"})
    care = db.create_care_item({"dependent_id": dep["id"], "title": "CmpJab", "category": "health", "due_date": due})
    try:
        cal = renewals_svc.build_renewal_calendar(days_ahead=14)
        items = cal["items"]
        assert any(i["type"] == "vehicle" and i["source_id"] == veh["id"] for i in items), items
        assert any(i["type"] == "care" and i["source_id"] == care["id"] for i in items), items
    finally:
        db.delete_vehicle(veh["id"])
        db.delete_dependent(dep["id"])   # cascades the care item


def test_appointment_reminder_days_overrides_global_lead(monkeypatch):
    """Global lead is 2, but an appointment carrying reminder_days=5 must still
    fire when it's only 4 days out. Only appointment reminders are enabled and
    the outbound WhatsApp send is captured, never sent."""
    sent: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        sent.append((to, body))
        return {"sid": "cmp-test"}

    monkeypatch.setattr(whatsapp_svc, "send_text", fake_send_text)

    original_prefs = db.get_notification_prefs()
    phone = "+447700900314"
    appt = None
    try:
        db.update_user("luke", {"phone": phone})
        db.update_notification_prefs({
            "master_enabled": True,
            "appointment_reminders": True,
            "bill_reminders": False,
            "renewal_reminders": False,       # keeps the vehicle/renewal blocks quiet
            "document_expiry_reminders": False,
            "large_transaction_alerts": False,
            "budget_alerts": False,
            "reminder_lead_days": 2,          # global lead = 2 (< the appt's 5)
        })

        when = (datetime.now() + timedelta(days=4)).replace(microsecond=0)
        appt = db.create_appointment({
            "title": "Dentist checkup CMPXYZ",
            "provider": "Smile Clinic",
            "datetime": when.strftime("%Y-%m-%dT09:00"),
            "category": "health",
            "reminder_days": 5,
        }, default_user="luke")

        result = asyncio.run(reminders_svc.run_reminders())
        assert result.get("sent", 0) >= 1, result
        # The appointment reminder went to luke's phone despite being 4 days out.
        assert any(to == phone and "Dentist checkup CMPXYZ" in body for to, body in sent), sent
    finally:
        if appt:
            db.delete_appointment(appt["id"])
            with db.get_conn() as conn:
                conn.execute("DELETE FROM sent_notifications WHERE key = ?", (f"appt:{appt['id']}",))
        db.update_user("luke", {"phone": ""})
        db.update_notification_prefs(original_prefs)
