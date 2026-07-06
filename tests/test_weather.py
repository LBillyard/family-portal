"""Weather helpers: WMO mapping, title→place candidates, holiday resolution."""

import asyncio
from datetime import date, timedelta

from server import database as db
from server.services import weather


def test_describe_known_and_unknown_codes():
    assert weather._describe(0) == ("☀️", "clear")
    assert weather._describe(61)[1] == "light rain"
    assert weather._describe(9999) == ("🌡️", "mixed")  # fallback


def test_title_candidates_place_country_prefers_place():
    # "Place, Country" → the place (first) is tried before the country.
    assert weather._title_candidates("Algarve, Portugal")[0] == "Algarve"


def test_title_candidates_trailing_destination():
    # "Trip — Place?" → trailing segment is the destination.
    assert weather._title_candidates("City break — Prague?")[0] == "Prague"


def test_title_candidates_empty():
    assert weather._title_candidates("") == []


def test_home_coords_from_env(monkeypatch):
    monkeypatch.setenv("WEATHER_LATITUDE", "53.8")
    monkeypatch.setenv("WEATHER_LONGITUDE", "-1.5")
    assert weather.is_configured()
    assert weather._home_coords() == (53.8, -1.5)


def test_home_coords_missing(monkeypatch):
    monkeypatch.delenv("WEATHER_LATITUDE", raising=False)
    monkeypatch.delenv("WEATHER_LONGITUDE", raising=False)
    assert weather._home_coords() is None
    assert not weather.is_configured()


def test_relevant_trip_matches_upcoming_with_destination():
    trip = db.create_trip({
        "title": "Test getaway",
        "status": "booked",
        "start": (date.today() + timedelta(days=3)).isoformat(),
        "end": (date.today() + timedelta(days=10)).isoformat(),
        "budget": 100,
        "destination": "Barcelona, Spain",
    })
    try:
        result = asyncio.run(weather._relevant_trip(lookahead_days=14))
        assert result is not None
        found_trip, candidates = result
        assert found_trip["id"] == trip["id"]
        assert "Barcelona, Spain" in candidates
        # A 0-day lookahead (digest) must NOT match a future trip.
        assert asyncio.run(weather._relevant_trip(lookahead_days=0)) is None
    finally:
        with db.get_conn() as c:
            c.execute("DELETE FROM holiday_trips WHERE id = ?", (trip["id"],))
