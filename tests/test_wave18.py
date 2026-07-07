"""Wave 18: smart cross-reference nudges, document search (db + assistant tool),
and the smart-nudges notification pref.

Everything here runs OFFLINE against the isolated temp DB from conftest.py — no
network. Dates are computed relative to a single `today` that is also passed to
`build_nudges`, so the assertions hold regardless of the real calendar date.
"""

import asyncio
from datetime import date, timedelta

from server import database as db
from server.services import assistant as A
from server.services import cross_ref


TODAY = date.today()


def _iso(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# 1) cross_ref.build_nudges
# ---------------------------------------------------------------------------

def test_petjab_nudge_before_future_trip():
    """A pet with a vaccination care_item due before a seeded FUTURE trip yields a
    petjab nudge whose de-dupe key is STABLE (never embeds today's date)."""
    pet = db.create_dependent({"name": "Bean18", "kind": "pet", "breed": "Collie"})
    care = db.create_care_item({
        "dependent_id": pet["id"],
        "title": "Booster jab",
        "category": "vaccination",
        "due_date": _iso(TODAY + timedelta(days=30)),
        "done": False,
    })
    trip = db.create_trip({
        "title": "Rome half-term 18",
        "status": "booked",
        "start": _iso(TODAY + timedelta(days=60)),
        "end": _iso(TODAY + timedelta(days=67)),
        "destination": "Rome",
    })

    nudges = cross_ref.build_nudges(TODAY)
    key = f"xref:petjab:{care['id']}:{trip['id']}"
    match = next((n for n in nudges if n["key"] == key), None)
    assert match is not None, [n["key"] for n in nudges]
    # STABLE key: it must not contain today's date, so the nudge fires once, not daily.
    assert TODAY.isoformat() not in match["key"]
    assert "Bean18" in match["body"] and "Rome" in match["body"]


def test_idea_trip_does_not_trigger_nudges():
    """A wishlist 'idea' trip (not booked/planning) must NOT fire cross-ref nudges —
    it may never happen, so nudging about a pet jab or passport for it is noise."""
    pet = db.create_dependent({"name": "BeanIdea", "kind": "pet", "breed": "Collie"})
    db.create_care_item({
        "dependent_id": pet["id"], "title": "Booster", "category": "vaccination",
        "due_date": _iso(TODAY + timedelta(days=30)), "done": False,
    })
    idea = db.create_trip({
        "title": "Someday Maldives", "status": "idea",
        "start": _iso(TODAY + timedelta(days=60)), "destination": "Maldives",
    })
    nudges = cross_ref.build_nudges(TODAY)
    # The 'idea' trip must never appear in a nudge (by its id in the key or its
    # unique destination in the body) — other tests' booked trips are irrelevant.
    assert not any(idea["id"] in n["key"] for n in nudges)
    assert not any("Maldives" in n["body"] for n in nudges)


def test_passport_nudge_within_six_months_of_trip():
    """A passport document expiring within 6 months of a future trip yields a
    passport nudge."""
    doc = db.create_document({
        "name": "Passport - Zephyrine18",
        "category": "passport",
        "expiry_date": _iso(TODAY + timedelta(days=150)),  # ~5 months out
        "notes": "quokkatoken18 marker",
    })
    trip = db.create_trip({
        "title": "Lisbon trip 18",
        "status": "booked",
        "start": _iso(TODAY + timedelta(days=60)),
        "end": _iso(TODAY + timedelta(days=64)),
        "destination": "Lisbon",
    })

    nudges = cross_ref.build_nudges(TODAY)
    key = f"xref:passport:{doc['id']}:{trip['id']}"
    match = next((n for n in nudges if n["key"] == key), None)
    assert match is not None, [n["key"] for n in nudges]
    assert TODAY.isoformat() not in match["key"]
    assert "passport" in match["body"].lower() and "Lisbon" in match["body"]


def test_carcluster_nudge_mot_and_tax_same_month():
    """A vehicle with MOT and tax due in the same month yields a carcluster nudge
    keyed by vehicle id + YYYYMM (not today's date)."""
    veh = db.create_vehicle({
        "name": "Blue Golf 18",
        "reg": "GT18 ABC",
        "mot_due": _iso(TODAY + timedelta(days=10)),
        "tax_due": _iso(TODAY + timedelta(days=12)),
    })

    nudges = cross_ref.build_nudges(TODAY)
    match = next(
        (n for n in nudges if n["key"].startswith(f"xref:carcluster:{veh['id']}:")),
        None,
    )
    assert match is not None, [n["key"] for n in nudges]
    assert TODAY.isoformat() not in match["key"]
    body = match["body"]
    assert "MOT" in body and "tax" in body


def test_build_nudges_empty_and_garbage_never_raises(monkeypatch):
    """build_nudges must return [] (never raise) on empty data, on garbage rows
    with missing/invalid dates, and even when an underlying db call blows up."""

    def _boom(*_a, **_k):
        raise RuntimeError("db exploded")

    # (a) Everything empty -> [].
    monkeypatch.setattr(cross_ref.db, "list_trips", lambda: [])
    monkeypatch.setattr(cross_ref.db, "list_dependents", lambda: [])
    monkeypatch.setattr(cross_ref.db, "list_care_items", lambda *_a, **_k: [])
    monkeypatch.setattr(cross_ref.db, "list_documents", lambda *_a, **_k: [])
    monkeypatch.setattr(cross_ref.db, "list_vehicles", lambda: [])
    assert cross_ref.build_nudges(TODAY) == []

    # (b) Garbage rows: no trips, missing/invalid dates everywhere -> [].
    monkeypatch.setattr(cross_ref.db, "list_dependents",
                        lambda: [{"kind": "pet", "name": "G", "id": "g1"}, {"kind": "child"}])
    monkeypatch.setattr(cross_ref.db, "list_care_items", lambda *_a, **_k: [
        {"category": "vaccination", "due_date": None, "done": False, "id": "c1"},
        {"category": "vaccination", "due_date": "not-a-date", "done": False, "id": "c2"},
    ])
    monkeypatch.setattr(cross_ref.db, "list_documents", lambda *_a, **_k: [
        {"category": "passport", "name": None, "expiry_date": None, "id": "d1"},
        {"name": "passport", "expiry_date": "garbage", "id": "d2"},
    ])
    monkeypatch.setattr(cross_ref.db, "list_vehicles", lambda: [
        {"id": "v1", "name": "X", "mot_due": None, "tax_due": "bad"},
        {"id": "v2", "name": "Y"},
    ])
    assert cross_ref.build_nudges(TODAY) == []

    # (c) Robustness: underlying db calls raise -> still [] and no exception escapes.
    monkeypatch.setattr(cross_ref.db, "list_trips", _boom)
    monkeypatch.setattr(cross_ref.db, "list_vehicles", _boom)
    monkeypatch.setattr(cross_ref.db, "list_dependents", _boom)
    monkeypatch.setattr(cross_ref.db, "list_documents", _boom)
    assert cross_ref.build_nudges(TODAY) == []


# ---------------------------------------------------------------------------
# 2) db.search_documents
# ---------------------------------------------------------------------------

def test_search_documents_by_name_notes_category():
    doc = db.create_document({
        "name": "Xylo18 Home Insurance",
        "category": "insurance",
        "notes": "policy grackle18 renewal",
        "expiry_date": _iso(TODAY + timedelta(days=200)),
    })
    doc_id = doc["id"]

    # by name
    by_name = db.search_documents("Xylo18")
    assert any(d["id"] == doc_id for d in by_name)
    # by notes
    by_notes = db.search_documents("grackle18")
    assert any(d["id"] == doc_id for d in by_notes)
    # by category
    by_cat = db.search_documents("insurance")
    assert any(d["id"] == doc_id for d in by_cat)

    # empty / whitespace query -> []
    assert db.search_documents("") == []
    assert db.search_documents("   ") == []


# ---------------------------------------------------------------------------
# 3) search_documents assistant tool
# ---------------------------------------------------------------------------

def test_search_documents_tool_registered_and_dispatches():
    names = {t["function"]["name"] for t in A.TOOLS}
    assert "search_documents" in names

    db.create_document({
        "name": "Warranty Vorpal18 Fridge",
        "category": "warranty",
        "notes": "kitchen appliance",
    })
    out = asyncio.run(A.execute_tool("search_documents", {"query": "Vorpal18"}, db.get_user("luke")))
    assert isinstance(out, dict) and "documents" in out
    docs = out["documents"]
    assert any(d.get("name") == "Warranty Vorpal18 Fridge" for d in docs)
    # trimmed shape carries the expected read-only fields
    assert set(docs[0].keys()) == {"name", "category", "expiry", "expiry_date", "status", "notes"}


# ---------------------------------------------------------------------------
# 4) smart_nudges notification pref round-trip
# ---------------------------------------------------------------------------

def test_smart_nudges_pref_roundtrips():
    db.update_notification_prefs({"smart_nudges": False})
    assert db.get_notification_prefs()["smart_nudges"] is False
    db.update_notification_prefs({"smart_nudges": True})
    assert db.get_notification_prefs()["smart_nudges"] is True
