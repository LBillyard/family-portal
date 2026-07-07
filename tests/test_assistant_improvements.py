"""Assistant improvements: remember_fact tool, date-aware context, new-entity tools."""

import asyncio
import json

from server import database as db
from server.services import assistant as A


def _tool_names():
    return {t["function"]["name"] for t in A.TOOLS}


def test_new_assistant_tools_registered():
    names = _tool_names()
    # completion-wave integration tools + the new remember_fact
    for n in ("create_occasion", "list_vehicle_renewals", "list_care_due",
              "get_shopping_list", "get_meal_plan", "add_wishlist_item", "remember_fact"):
        assert n in names, n
    # every tool name is unique
    all_names = [t["function"]["name"] for t in A.TOOLS]
    assert len(all_names) == len(set(all_names))


def test_build_context_is_date_aware_and_compact():
    ctx = json.loads(A.build_context(db.get_user("luke")))
    # date/time awareness for resolving "today"/"tonight"/"Friday"
    assert ctx["today"] and ctx["today_label"] and ctx["now_time"]
    assert ":" in ctx["now_time"]
    # the new entity context keys are present (wired by the completion pass)
    for k in ("upcoming_occasions", "vehicle_renewals", "care_due", "this_week_meals", "open_shopping"):
        assert k in ctx


def test_remember_fact_degrades_without_memory(monkeypatch):
    # No OPENROUTER key in the test env -> memory disabled -> graceful, no raise.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = asyncio.run(A.execute_tool("remember_fact", {"fact": "Arthur's shoe size is 6"}, db.get_user("luke")))
    assert out["ok"] is False and "error" in out


def test_remember_fact_needs_a_fact():
    out = asyncio.run(A.execute_tool("remember_fact", {"fact": "   "}, db.get_user("luke")))
    assert out["ok"] is False


def test_email_search_tools_registered():
    names = _tool_names()
    assert "search_email" in names and "file_email_attachment" in names


def test_email_search_degrades_without_google(monkeypatch):
    from server.services import email_search
    # No connected Google account in the test DB → friendly error, never raises.
    monkeypatch.setattr(email_search.db, "list_google_accounts", lambda uid: [])
    assert email_search.is_available("luke") is False
    assert email_search.search("luke", "car insurance")["error"]
    assert email_search.search("luke", "")["error"]           # empty query guarded
    r = email_search.file_attachment("luke", "somemsgid", "x.pdf")
    assert r["ok"] is False


def test_email_search_tool_dispatch_is_graceful(monkeypatch):
    from server.services import email_search
    monkeypatch.setattr(email_search.db, "list_google_accounts", lambda uid: [])
    out = asyncio.run(A.execute_tool("search_email", {"query": "vet Bean"}, db.get_user("luke")))
    assert "error" in out and out.get("results") == []


def test_get_shopping_list_tool_reads_back():
    db.create_shopping_item("assistant-test-milk", "luke")
    out = asyncio.run(A.execute_tool("get_shopping_list", {}, db.get_user("luke")))
    items = out.get("items") if isinstance(out, dict) else out
    texts = {i["text"] for i in items}
    assert "assistant-test-milk" in texts
    for i in db.list_shopping_items():
        if i["text"] == "assistant-test-milk":
            db.delete_shopping_item(i["id"])
