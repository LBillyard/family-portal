"""Trip enhancements — packing lists, timelines, travel documents."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from server import database as db

PACKING_TEMPLATES: dict[str, list[str]] = {
    "default": [
        "Passports / ID",
        "Travel insurance docs",
        "Phone charger",
        "Toiletries",
        "Medications",
        "Comfortable shoes",
    ],
    "beach": [
        "Swimwear",
        "Sun cream",
        "Sunglasses",
        "Beach towels",
        "Flip flops",
        "After-sun",
        "Hat",
    ],
    "city": [
        "Comfortable walking shoes",
        "Light jacket",
        "Day bag",
        "Umbrella",
        "Portable charger",
        "Guidebook / maps",
    ],
    "weekend": [
        "Overnight bag",
        "Change of clothes",
        "Toiletries",
        "Snacks",
    ],
}


def add_packing_list(trip_id: str, template: str = "default") -> list[dict]:
    items = PACKING_TEMPLATES.get(template) or PACKING_TEMPLATES["default"]
    return db.add_packing_items(trip_id, items)


def get_trip_detail(trip_id: str) -> dict | None:
    trip = db.get_trip_detail(trip_id)
    if not trip:
        return None
    media = db.list_media(trip_id)
    trip["media"] = media
    trip["timeline"] = build_trip_timeline(trip, media)
    trip["linked_documents"] = db.list_trip_documents(trip_id)
    trip["packing"] = trip.get("packing") or []
    trip["checklist"] = trip.get("checklist") or []
    return trip


def build_trip_timeline(trip: dict, media: list[dict]) -> list[dict]:
    start_s = trip.get("start") or trip.get("start_date")
    end_s = trip.get("end") or trip.get("end_date")
    days: list[dict] = []

    if start_s and end_s:
        try:
            start = date.fromisoformat(start_s[:10])
            end = date.fromisoformat(end_s[:10])
            current = start
            while current <= end:
                days.append({"date": current.isoformat(), "label": current.strftime("%a %d %b"), "media": []})
                current += timedelta(days=1)
        except ValueError:
            days = []
    elif start_s:
        try:
            d = date.fromisoformat(start_s[:10])
            days = [{"date": d.isoformat(), "label": d.strftime("%a %d %b"), "media": []}]
        except ValueError:
            days = []

    if not days:
        by_date: dict[str, list] = defaultdict(list)
        for m in media:
            key = (m.get("taken_at") or m.get("uploaded_at") or "")[:10] or "unknown"
            by_date[key].append(m)
        return [{"date": k, "label": k, "media": v} for k, v in sorted(by_date.items())]

    day_map = {d["date"]: d for d in days}
    for m in media:
        key = (m.get("taken_at") or m.get("uploaded_at") or start_s or "")[:10]
        if key in day_map:
            day_map[key]["media"].append(m)
        elif days:
            days[0]["media"].append(m)
    return days
