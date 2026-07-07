"""Wave-1 backend: unified reminders service + notification-prefs & tradespeople routes.

The reminders tests drive the service directly (asyncio.run) with whatsapp.send_text
monkeypatched to record calls; the route tests use the shared authenticated `client`
fixture from conftest.
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import reminders as reminders_svc
from server.services import whatsapp


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    """Patch whatsapp.send_text to record (phone, body) instead of sending."""
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


def test_reminders_respect_master_switch(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_notification_prefs({"master_enabled": False})

    result = asyncio.run(reminders_svc.run_reminders())

    assert result == {"sent": 0, "skipped": "disabled"}
    assert calls == []


def test_appointment_reminder_fires_once_then_dedupes(monkeypatch):
    calls = _record_sends(monkeypatch)

    # Only appointment reminders on, so bills/renewals/docs in the shared test DB
    # can't contribute sends. Lead of 3 days covers a next-day appointment.
    db.update_notification_prefs({
        "master_enabled": True,
        "appointment_reminders": True,
        "bill_reminders": False,
        "renewal_reminders": False,
        "document_expiry_reminders": False,
        "reminder_lead_days": 3,
    })

    # The owner must have a phone for the reminder to reach them.
    db.update_user("luke", {"phone": "+447700900123"})
    title = f"ReminderTest-{uuid.uuid4().hex[:8]}"
    when = (date.today() + timedelta(days=1)).isoformat() + "T10:00"
    appt = db.create_appointment(
        {"title": title, "provider": "Test Clinic", "datetime": when, "user_id": "luke"},
        "luke",
    )
    try:
        # First run: exactly one message for THIS appointment.
        asyncio.run(reminders_svc.run_reminders())
        mine = [b for _to, b in calls if title in b]
        assert len(mine) == 1, f"expected one reminder for {title}, got {mine}"
        assert "+447700900123" == next(to for to, b in calls if title in b)

        # Second run: de-duped — no new message for this appointment.
        asyncio.run(reminders_svc.run_reminders())
        mine = [b for _to, b in calls if title in b]
        assert len(mine) == 1, f"reminder re-sent after dedupe: {mine}"
    finally:
        db.delete_appointment(appt["id"])
        db.update_user("luke", {"phone": ""})


def test_notification_prefs_get_and_patch(client):
    got = client.get("/api/notifications/prefs")
    assert got.status_code == 200, got.text
    prefs = got.json()
    for key in (
        "master_enabled", "morning_digest", "evening_digest",
        "appointment_reminders", "bill_reminders", "renewal_reminders",
        "document_expiry_reminders", "reminder_lead_days",
    ):
        assert key in prefs

    patched = client.patch(
        "/api/notifications/prefs",
        json={"evening_digest": True, "reminder_lead_days": 5},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["evening_digest"] is True
    assert body["reminder_lead_days"] == 5
    # Persisted.
    assert client.get("/api/notifications/prefs").json()["reminder_lead_days"] == 5


def test_tradespeople_crud(client):
    created = client.post(
        "/api/tradespeople",
        json={
            "name": "Bob the Plumber",
            "trade": "Plumber",
            "phone": "01234 567890",
            "email": "bob@example.com",
            "notes": "Reliable, cash only",
        },
    )
    assert created.status_code == 200, created.text
    person = created.json()
    pid = person["id"]
    assert person["name"] == "Bob the Plumber"
    assert person["trade"] == "Plumber"

    listed = client.get("/api/tradespeople")
    assert listed.status_code == 200
    assert any(p["id"] == pid for p in listed.json()["tradespeople"])

    patched = client.patch(f"/api/tradespeople/{pid}", json={"phone": "09999 000000"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["phone"] == "09999 000000"

    assert client.delete(f"/api/tradespeople/{pid}").json() == {"ok": True}
    # Gone now → 404 on further mutations.
    assert client.patch(f"/api/tradespeople/{pid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/tradespeople/{pid}").status_code == 404
