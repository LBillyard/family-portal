"""Smart cross-reference nudges — proactive reminders that connect facts ACROSS
domains, not just within one.

`build_nudges(today)` links things the household tracks separately: a pet's
vaccination lapsing on/before a booked trip, a passport too close to expiry for an
upcoming holiday, or a car's MOT/tax/insurance/service all clustering in one month.
It returns a list of {"key", "body"} dicts for the reminders job to de-dupe (via
db.was_notified/mark_notified) and send.

BEST-EFFORT: every rule runs inside its own try/except, and each row inside a rule
is guarded too, so a failure in one rule (or one bad row) contributes nothing and
never aborts the others — this function must NEVER raise into the reminders run.
De-dupe keys are STABLE: they never embed today's date, so each nudge fires once
(when the situation first arises), not once per day.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from server import database as db

# Only nudge about trips the family is actually committed to — a "booked" or
# "planning" trip is real; an "idea" (wishlist) trip may never happen, so it must
# not trigger passport/vaccination nudges.
_REAL_TRIP_STATUSES = {"booked", "planning"}


def _real_trips() -> list[dict]:
    return [t for t in db.list_trips() if (t.get("status") or "") in _REAL_TRIP_STATUSES]


def _pdate(s):
    """Parse an ISO date (or ISO datetime) string to a date, else None. Never raises."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (ValueError, TypeError):
        return None


def _human_list(items) -> str:
    """['MOT', 'tax', 'insurance'] -> 'MOT, tax and insurance'."""
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def build_nudges(today) -> list[dict]:
    """Return cross-domain nudges [{"key", "body"}, ...] for `today` (a date object).

    Best-effort: never raises. Bodies are single-line (WhatsApp/template safe) and
    keys are stable so the reminders de-dupe fires each nudge exactly once.
    """
    out: list[dict] = []

    # 1) PET JAB vs TRIP: a pet's vaccination lapses on/before a future departure.
    try:
        trips = _real_trips()
        for dep in db.list_dependents():
            try:
                if dep.get("kind") != "pet":
                    continue
                pet_name = dep.get("name") or "Your pet"
                for ci in db.list_care_items(dep.get("id")):
                    if ci.get("category") != "vaccination" or ci.get("done"):
                        continue
                    d_due = _pdate(ci.get("due_date"))
                    if not d_due:
                        continue
                    for trip in trips:
                        d_start = _pdate(trip.get("start"))
                        if not d_start or d_start < today:
                            continue
                        if d_due <= d_start and (d_start - today).days <= 120:
                            where = trip.get("destination") or trip.get("title") or "your trip"
                            body = "🐶 " + pet_name + "'s vaccination is due " + d_due.isoformat() + " — before your trip to " + where + " on " + d_start.isoformat() + ". Kennels/boarding usually need it up to date."
                            out.append({"key": "xref:petjab:" + str(ci.get("id")) + ":" + str(trip.get("id")), "body": body})
            except Exception:
                continue
    except Exception:
        pass

    # 2) PASSPORT vs TRIP: passport expiry inside the 6-month validity buffer for a trip.
    try:
        trips = _real_trips()
        for doc in db.list_documents():
            try:
                name = doc.get("name") or ""
                if doc.get("category") != "passport" and "passport" not in name.lower():
                    continue
                d_exp = _pdate(doc.get("expiry_date") or doc.get("expiry"))
                if not d_exp:
                    continue
                for trip in trips:
                    d_start = _pdate(trip.get("start"))
                    if not d_start or d_start < today:
                        continue
                    if d_exp < d_start + timedelta(days=180):
                        where = trip.get("destination") or trip.get("title") or "your trip"
                        body = "🛂 Your passport (" + name + ") expires " + d_exp.isoformat() + " — many countries need 6 months' validity, and your trip to " + where + " starts " + d_start.isoformat() + ". Check before you travel."
                        out.append({"key": "xref:passport:" + str(doc.get("id")) + ":" + str(trip.get("id")), "body": body})
            except Exception:
                continue
    except Exception:
        pass

    # 3) CLUSTERED CAR RENEWALS: 2+ of MOT/tax/insurance/service (each due within 60
    #    days) landing within a 31-day window of each other — worth sorting together.
    try:
        for v in db.list_vehicles():
            try:
                due = []
                for label, s in (("MOT", v.get("mot_due")), ("tax", v.get("tax_due")), ("insurance", v.get("insurance_due")), ("service", v.get("service_due"))):
                    d = _pdate(s)
                    if d and 0 <= (d - today).days <= 60:
                        due.append((label, d))
                due.sort(key=lambda x: x[1])
                best = []
                for i in range(len(due)):
                    window = [due[i]] + [due[j] for j in range(i + 1, len(due)) if (due[j][1] - due[i][1]).days <= 31]
                    if len(window) > len(best):
                        best = window
                if len(best) >= 2:
                    earliest = best[0][1]
                    reg = v.get("reg")
                    body = "🚗 " + (v.get("name") or "Vehicle") + ((" (" + reg + ")") if reg else "") + " has " + _human_list([lab for lab, _ in best]) + " all due around " + earliest.strftime("%b %Y") + " — worth sorting together."
                    out.append({"key": "xref:carcluster:" + str(v.get("id")) + ":" + earliest.strftime("%Y%m"), "body": body})
            except Exception:
                continue
    except Exception:
        pass

    # De-dupe identical keys, preserving first-seen order.
    seen: set = set()
    unique: list[dict] = []
    for n in out:
        k = n["key"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(n)
    return unique
