"""Wave-11 backend: holiday-trip itinerary items.

Covers the db CRUD helpers (create/get/update/delete_itinerary_item) and the
list_itinerary() ordering contract (dated+timed first in day/time order, then
same-day untimed items by insertion order, undated items last), plus the
GET/POST/PATCH/DELETE /api/itinerary routes and the trip validation / blank-title
guards on POST, and the cascade that clears a trip's itinerary when the trip is
deleted.

Rows live on a shared box, so every test creates its own trip and deletes it in a
finally (delete_trip cascades the itinerary rows, so that also cleans up items).
"""

import uuid

from server import database as db


def _make_trip() -> str:
    """A fresh holiday trip; returns its id. Caller must db.delete_trip() it."""
    trip = db.create_trip({"title": f"Wave11 Trip {uuid.uuid4().hex[:6]}", "status": "booked"})
    return trip["id"]


# --- db CRUD ---------------------------------------------------------------

def test_itinerary_db_crud():
    tid = _make_trip()
    try:
        it = db.create_itinerary_item({
            "trip_id": tid, "title": "  Museum visit  ", "kind": "activity",
            "day_date": "2027-06-01", "start_time": "10:30",
            "location": "The Louvre", "notes": "book tickets",
        })
        iid = it["id"]
        assert it["trip_id"] == tid
        assert it["title"] == "Museum visit"          # title is stripped on insert
        assert it["kind"] == "activity"
        assert it["day_date"] == "2027-06-01" and it["start_time"] == "10:30"
        assert it["location"] == "The Louvre" and it["notes"] == "book tickets"

        got = db.get_itinerary_item(iid)
        assert got and got["title"] == "Museum visit" and got["trip_id"] == tid

        # kind defaults to 'activity' and notes to '' when omitted
        bare = db.create_itinerary_item({"trip_id": tid, "title": "Lunch"})
        assert bare["kind"] == "activity" and bare["notes"] == ""
        assert bare["day_date"] is None and bare["start_time"] is None
        db.delete_itinerary_item(bare["id"])

        # partial update touches only the given fields
        upd = db.update_itinerary_item(iid, {"title": "Museum + gift shop", "start_time": "11:00"})
        assert upd["title"] == "Museum + gift shop" and upd["start_time"] == "11:00"
        assert upd["day_date"] == "2027-06-01"        # untouched field preserved
        assert upd["location"] == "The Louvre"

        # nullable fields can be cleared to NULL via presence
        upd2 = db.update_itinerary_item(iid, {"day_date": None, "start_time": None, "location": None})
        assert upd2["day_date"] is None and upd2["start_time"] is None and upd2["location"] is None

        # a blank title is ignored (the required title is never wiped)
        upd3 = db.update_itinerary_item(iid, {"title": "   "})
        assert upd3["title"] == "Museum + gift shop"

        # notes coerces None -> '' (NOT NULL column)
        upd4 = db.update_itinerary_item(iid, {"notes": None})
        assert upd4["notes"] == ""

        # updating a missing item -> None
        assert db.update_itinerary_item("does-not-exist", {"title": "x"}) is None

        assert db.delete_itinerary_item(iid) is True
        assert db.get_itinerary_item(iid) is None
        assert db.delete_itinerary_item(iid) is False   # already gone
    finally:
        db.delete_trip(tid)


# --- list_itinerary ordering ------------------------------------------------

def test_itinerary_ordering(client):
    """dated+timed (by day then time) -> same-day untimed (insertion order) -> undated last."""
    tid = _make_trip()
    try:
        # Insert in a deliberately scrambled order to prove the ORDER BY, not insertion order.
        inserts = [
            {"title": "E-undated"},                                              # no day → last
            {"title": "A-day2", "day_date": "2027-06-02", "start_time": "09:00"},
            {"title": "D-untimed1", "day_date": "2027-06-01"},                   # day1, untimed (1st)
            {"title": "B-1400", "day_date": "2027-06-01", "start_time": "14:00"},
            {"title": "C-0800", "day_date": "2027-06-01", "start_time": "08:00"},
            {"title": "D2-untimed2", "day_date": "2027-06-01"},                  # day1, untimed (2nd)
        ]
        for body in inserts:
            r = client.post("/api/itinerary", json={"trip_id": tid, **body})
            assert r.status_code == 200, r.text

        items = client.get(f"/api/itinerary?trip_id={tid}").json()["items"]
        titles = [i["title"] for i in items]
        assert titles == [
            "C-0800",        # day1, timed 08:00
            "B-1400",        # day1, timed 14:00
            "D-untimed1",    # day1, untimed, inserted before D2
            "D2-untimed2",   # day1, untimed, inserted after D
            "A-day2",        # day2
            "E-undated",     # undated → last
        ], titles
    finally:
        db.delete_trip(tid)


# --- routes: full CRUD ------------------------------------------------------

def test_itinerary_route_crud(client):
    tid = _make_trip()
    try:
        r = client.post("/api/itinerary", json={
            "trip_id": tid, "title": "Check in", "kind": "lodging",
            "day_date": "2027-07-10", "start_time": "15:00",
            "location": "Hotel Med", "notes": "late arrival",
        })
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        iid = item["id"]
        assert item["trip_id"] == tid and item["title"] == "Check in"
        assert item["kind"] == "lodging" and item["day_date"] == "2027-07-10"
        assert item["start_time"] == "15:00" and item["location"] == "Hotel Med"

        # GET lists the new item under its trip
        listed = client.get(f"/api/itinerary?trip_id={tid}").json()["items"]
        assert [x["id"] for x in listed] == [iid]

        # PATCH updates only the given fields
        p = client.patch(f"/api/itinerary/{iid}", json={"title": "Check in early", "start_time": "13:00"})
        assert p.status_code == 200, p.text
        pv = p.json()["item"]
        assert pv["title"] == "Check in early" and pv["start_time"] == "13:00"
        assert pv["kind"] == "lodging" and pv["day_date"] == "2027-07-10"   # untouched

        # PATCH can clear a nullable field to null
        p2 = client.patch(f"/api/itinerary/{iid}", json={"day_date": None, "start_time": None})
        assert p2.status_code == 200, p2.text
        assert p2.json()["item"]["day_date"] is None and p2.json()["item"]["start_time"] is None

        # PATCH of a missing id -> 404
        assert client.patch("/api/itinerary/nope", json={"title": "x"}).status_code == 404

        # DELETE removes it; a second DELETE -> 404
        d = client.delete(f"/api/itinerary/{iid}")
        assert d.status_code == 200 and d.json()["ok"] is True
        assert client.delete(f"/api/itinerary/{iid}").status_code == 404
        assert db.get_itinerary_item(iid) is None
        assert client.get(f"/api/itinerary?trip_id={tid}").json()["items"] == []
    finally:
        db.delete_trip(tid)


# --- routes: validation -----------------------------------------------------

def test_itinerary_post_validation(client):
    tid = _make_trip()
    try:
        # unknown trip_id -> 400 (get_trip_detail returns None)
        bad = client.post("/api/itinerary", json={"trip_id": "no-such-trip", "title": "Ghost"})
        assert bad.status_code == 400, bad.text

        # valid trip but blank title -> 400 (checked after trip validation)
        blank = client.post("/api/itinerary", json={"trip_id": tid, "title": "   "})
        assert blank.status_code == 400, blank.text

        # nothing was created for the valid trip
        assert client.get(f"/api/itinerary?trip_id={tid}").json()["items"] == []
    finally:
        db.delete_trip(tid)


def test_itinerary_get_requires_trip_id(client):
    # Missing / blank trip_id on GET -> 400
    assert client.get("/api/itinerary").status_code == 400
    assert client.get("/api/itinerary?trip_id=").status_code == 400
    assert client.get("/api/itinerary?trip_id=%20%20").status_code == 400


# --- cascade on trip delete -------------------------------------------------

def test_itinerary_cascade_on_trip_delete(client):
    tid = _make_trip()
    created = False
    try:
        for i in range(3):
            r = client.post("/api/itinerary", json={
                "trip_id": tid, "title": f"Day plan {i}", "day_date": "2027-08-0%d" % (i + 1),
            })
            assert r.status_code == 200, r.text
        created = True

        assert len(client.get(f"/api/itinerary?trip_id={tid}").json()["items"]) == 3

        # Deleting the trip cascades its itinerary rows away.
        d = client.delete(f"/api/holidays/trips/{tid}")
        assert d.status_code == 200, d.text
        assert db.list_itinerary(tid) == []
        assert client.get(f"/api/itinerary?trip_id={tid}").json()["items"] == []
    finally:
        # Trip is already gone on the happy path; clean up if the delete never ran.
        if not created or db.get_trip_detail(tid):
            db.delete_trip(tid)
