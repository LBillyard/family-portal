"""Weather for the morning digest and the header forecast widget.

Uses Open-Meteo (https://open-meteo.com) — free, no API key required.
Home location comes from .env:

  WEATHER_LATITUDE    e.g. 53.868682
  WEATHER_LONGITUDE   e.g. -1.46187
  WEATHER_LABEL       (optional) short place name, e.g. "Scarcroft"

Holiday awareness: when the household is on (or about to start) a holiday trip
with a known destination, `resolve_location()` switches the forecast to that
place — so both the digest and the header widget follow you on holiday.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# WMO weather interpretation codes -> (emoji, short description).
# https://open-meteo.com/en/docs (WMO Weather interpretation codes)
_WMO: dict[int, tuple[str, str]] = {
    0: ("☀️", "clear"),
    1: ("🌤️", "mainly clear"),
    2: ("⛅", "partly cloudy"),
    3: ("☁️", "overcast"),
    45: ("🌫️", "fog"),
    48: ("🌫️", "freezing fog"),
    51: ("🌦️", "light drizzle"),
    53: ("🌦️", "drizzle"),
    55: ("🌦️", "heavy drizzle"),
    56: ("🌧️", "freezing drizzle"),
    57: ("🌧️", "freezing drizzle"),
    61: ("🌦️", "light rain"),
    63: ("🌧️", "rain"),
    65: ("🌧️", "heavy rain"),
    66: ("🌧️", "freezing rain"),
    67: ("🌧️", "freezing rain"),
    71: ("🌨️", "light snow"),
    73: ("🌨️", "snow"),
    75: ("❄️", "heavy snow"),
    77: ("🌨️", "snow grains"),
    80: ("🌦️", "light showers"),
    81: ("🌧️", "showers"),
    82: ("⛈️", "heavy showers"),
    85: ("🌨️", "snow showers"),
    86: ("❄️", "heavy snow showers"),
    95: ("⛈️", "thunderstorms"),
    96: ("⛈️", "thunderstorms with hail"),
    99: ("⛈️", "thunderstorms with hail"),
}

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _describe(code) -> tuple[str, str]:
    try:
        return _WMO.get(int(code), ("🌡️", "mixed"))
    except (TypeError, ValueError):
        return ("🌡️", "mixed")


def _home_coords() -> tuple[float, float] | None:
    lat = os.environ.get("WEATHER_LATITUDE", "").strip()
    lon = os.environ.get("WEATHER_LONGITUDE", "").strip()
    if not lat or not lon:
        return None
    try:
        return float(lat), float(lon)
    except ValueError:
        logger.warning("WEATHER_LATITUDE/WEATHER_LONGITUDE are not valid numbers")
        return None


def is_configured() -> bool:
    return _home_coords() is not None


def _title_candidates(title: str) -> list[str]:
    """Best-effort place names from a trip title. For 'Place, Country' the first
    segment is the more specific place ('Algarve, Portugal' -> Algarve); for
    'Trip name — Place' the destination trails ('City break — Prague?' -> Prague)."""
    title = (title or "").strip()
    if not title:
        return []
    cands: list[str] = []
    for sep in (",", "—", "–", "-", ":"):
        if sep in title:
            parts = [p.strip(" ?!.") for p in title.split(sep) if p.strip(" ?!.")]
            if parts:
                if sep == ",":
                    cands += [parts[0], parts[-1]]  # "Algarve" before "Portugal"
                else:
                    cands += [parts[-1], parts[0]]  # "Prague" before "City break"
            break
    cands.append(title.strip(" ?!."))
    seen: set[str] = set()
    return [c for c in cands if c and not (c in seen or seen.add(c))]


async def _geocode(name: str) -> tuple[float, float, str] | None:
    name = (name or "").strip().strip("?").strip()
    if not name:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                GEOCODE_URL,
                params={"name": name, "count": 1, "language": "en", "format": "json"},
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        if not results:
            return None
        g = results[0]
        label = g.get("name")
        country = g.get("country")
        if country and country != label:
            label = f"{label}, {country}"
        return float(g["latitude"]), float(g["longitude"]), label
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        logger.warning("Geocode '%s' failed: %s", name, exc)
        return None


async def _relevant_trip(lookahead_days: int):
    """The trip whose weather should show now: an ongoing one, else the soonest
    starting within `lookahead_days`. Only trips with a usable destination count.
    Returns (trip_dict, candidates:list[str]) or None. Lazy-imports db to avoid coupling."""
    try:
        from server import database as db
    except Exception:  # pragma: no cover
        return None
    today = date.today()
    best = None  # (sort_key, trip, candidates)
    for t in db.list_trips():
        start = t.get("start")
        if not start:
            continue
        try:
            sd = date.fromisoformat(str(start)[:10])
        except (ValueError, TypeError):
            continue
        ed = None
        if t.get("end"):
            try:
                ed = date.fromisoformat(str(t["end"])[:10])
            except (ValueError, TypeError):
                ed = None
        ongoing = sd <= today and (ed is None or today <= ed)
        upcoming = bool(lookahead_days) and (today < sd <= today + timedelta(days=lookahead_days))
        if not (ongoing or upcoming):
            continue
        dest = (t.get("destination") or "").strip()
        candidates = [dest] if dest else _title_candidates(t.get("title", ""))
        if not candidates:
            continue
        key = (0 if ongoing else 1, sd)
        if best is None or key < best[0]:
            best = (key, t, candidates)
    if not best:
        return None
    return best[1], best[2]


async def resolve_location(lookahead_days: int = 0) -> dict | None:
    """Where to show weather for. A holiday destination (ongoing, or upcoming within
    lookahead_days) takes priority over home. Returns {lat, lon, label, holiday, trip}."""
    trip = await _relevant_trip(lookahead_days)
    if trip:
        t, candidates = trip
        for cand in candidates:
            geo = await _geocode(cand)
            if geo:
                lat, lon, glabel = geo
                label = (t.get("destination") or "").strip() or glabel or t.get("title")
                return {"lat": lat, "lon": lon, "label": label, "holiday": True, "trip": t.get("title")}
    home = _home_coords()
    if home:
        return {
            "lat": home[0],
            "lon": home[1],
            "label": os.environ.get("WEATHER_LABEL", "").strip() or None,
            "holiday": False,
            "trip": None,
        }
    return None


async def _fetch(lat: float, lon: float, days: int) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "current": "temperature_2m,weather_code",
        "timezone": "auto",
        "forecast_days": max(1, min(int(days), 16)),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(FORECAST_URL, params=params)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return None


async def forecast(days: int = 7, lookahead_days: int = 14) -> dict | None:
    """Multi-day forecast for the header widget. Follows a holiday if one is
    ongoing or starting within lookahead_days. Returns None if unconfigured/unavailable."""
    loc = await resolve_location(lookahead_days=lookahead_days)
    if not loc:
        return None
    raw = await _fetch(loc["lat"], loc["lon"], days)
    if not raw:
        return None
    daily = raw.get("daily") or {}
    times = daily.get("time") or []
    out_days = []
    for i, dstr in enumerate(times):
        try:
            emoji, desc = _describe(daily["weather_code"][i])
            wd = date.fromisoformat(dstr)
            out_days.append({
                "date": dstr,
                "weekday": "Today" if wd == date.today() else _WEEKDAYS[wd.weekday()],
                "emoji": emoji,
                "desc": desc,
                "tmax": round(daily["temperature_2m_max"][i]),
                "tmin": round(daily["temperature_2m_min"][i]),
                "precip": (daily.get("precipitation_probability_max") or [None] * len(times))[i],
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    cur = raw.get("current") or {}
    cur_emoji, cur_desc = _describe(cur.get("weather_code"))
    cur_temp = cur.get("temperature_2m")
    return {
        "label": loc["label"],
        "holiday": loc["holiday"],
        "trip": loc.get("trip"),
        "current": {
            "temp": round(cur_temp) if cur_temp is not None else None,
            "emoji": cur_emoji,
            "desc": cur_desc,
        },
        "days": out_days,
    }


async def today_line() -> str | None:
    """Compact one-line forecast for today, for the WhatsApp digest ({{1}} variable).
    Switches to the holiday location while a trip is ongoing. None if unavailable."""
    loc = await resolve_location(lookahead_days=0)  # digest: only an ongoing trip changes location
    if not loc:
        return None
    raw = await _fetch(loc["lat"], loc["lon"], 1)
    if not raw:
        return None
    try:
        daily = raw["daily"]
        code = int(daily["weather_code"][0])
        tmax = round(daily["temperature_2m_max"][0])
        tmin = round(daily["temperature_2m_min"][0])
        pop = (daily.get("precipitation_probability_max") or [None])[0]
        now_t = (raw.get("current") or {}).get("temperature_2m")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Weather parse failed: %s", exc)
        return None

    emoji, desc = _describe(code)
    parts = [emoji]
    label = loc.get("label")
    if loc.get("holiday") and label:
        parts.append(f"{label} (holiday):")
    elif label:
        parts.append(f"{label}:")
    parts.append(f"{desc}, {tmin}–{tmax}°C")
    if now_t is not None:
        parts.append(f"(now {round(now_t)}°)")
    if pop is not None and pop >= 30:
        parts.append(f"{int(pop)}% rain")
    return " ".join(parts)
