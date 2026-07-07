"""Wave-5 backend: net-worth snapshots + trends, spend trend, chores rotation,
and the chore due-nudge folded into run_reminders().
"""

import asyncio
import uuid
from datetime import date, timedelta

from server import database as db
from server.services import chores as chores_svc
from server.services import insights as insights_svc
from server.services import networth as networth_svc
from server.services import reminders as reminders_svc
from server.services import whatsapp


def _record_sends(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake_send_text(to: str, body: str) -> dict:
        calls.append((to, body))
        return {"sid": "test"}

    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    return calls


# --- chores DB + rotation --------------------------------------------------

def test_chore_crud_and_assignee_name():
    c = db.create_chore({"title": "  Bins out  ", "cadence": "weekly", "assignee_id": "luke", "next_due": "2099-02-01"})
    assert c["title"] == "Bins out"
    assert c["assignee_name"] == "Luke"
    assert c["rotate"] is True
    assert any(x["id"] == c["id"] for x in db.list_chores())

    u = db.update_chore(c["id"], {"cadence": "monthly"})
    assert u["cadence"] == "monthly"
    assert u["assignee_id"] == "luke"          # unspecified field preserved
    assert db.delete_chore(c["id"]) is True
    assert db.delete_chore(c["id"]) is False


def test_complete_chore_rotates_and_advances():
    c = db.create_chore({"title": "Hoovering", "cadence": "weekly", "assignee_id": "luke",
                         "rotate": True, "next_due": "2000-01-01"})
    done = chores_svc.complete_chore(c["id"])
    assert done["assignee_id"] == "partner"     # luke -> partner
    assert done["assignee_name"] == "Laura"
    assert done["last_done"] == date.today().isoformat()
    # next_due advanced ~a week out from today
    nd = date.fromisoformat(done["next_due"])
    assert nd == date.today() + timedelta(days=7)

    # non-rotating chore keeps its assignee
    c2 = db.create_chore({"title": "Water plants", "cadence": "weekly", "assignee_id": "luke", "rotate": False,
                          "next_due": "2000-01-01"})
    done2 = chores_svc.complete_chore(c2["id"])
    assert done2["assignee_id"] == "luke"
    db.delete_chore(c["id"]); db.delete_chore(c2["id"])


def test_complete_missing_chore_returns_none():
    assert chores_svc.complete_chore("no-such-id") is None


# --- chores routes ---------------------------------------------------------

def test_chore_routes_and_done(client):
    r = client.post("/api/chores", json={"title": "Change bedding", "cadence": "fortnightly",
                                         "assignee_id": "partner", "next_due": "2000-01-01"})
    assert r.status_code == 200, r.text
    ch = r.json()["chore"]
    assert ch["assignee_name"] == "Laura"

    assert client.post("/api/chores", json={"title": "  "}).status_code == 400

    done = client.post(f"/api/chores/{ch['id']}/done")
    assert done.status_code == 200
    assert done.json()["chore"]["assignee_id"] == "luke"   # rotated partner -> luke

    patched = client.patch(f"/api/chores/{ch['id']}", json={"cadence": "monthly"})
    assert patched.json()["chore"]["cadence"] == "monthly"
    assert client.delete(f"/api/chores/{ch['id']}").json()["ok"] is True
    assert client.post("/api/chores/nope/done").status_code == 404


# --- reminders: chore nudge ------------------------------------------------

def test_due_chore_nudges_assignee_once(monkeypatch):
    calls = _record_sends(monkeypatch)
    db.update_user("luke", {"phone": "+447700900999"})
    db.update_notification_prefs({
        "master_enabled": True,
        "appointment_reminders": False,
        "bill_reminders": False,
        "renewal_reminders": False,
        "document_expiry_reminders": False,
        "large_transaction_alerts": False,
    })
    marker = f"Mow lawn {uuid.uuid4().hex[:5]}"
    c = db.create_chore({"title": marker, "cadence": "weekly", "assignee_id": "luke",
                         "rotate": True, "next_due": date.today().isoformat()})

    asyncio.run(reminders_svc.run_reminders())
    hits = [(to, b) for to, b in calls if marker in b]
    assert len(hits) == 1, calls
    assert hits[0][0] == "+447700900999"       # went to luke's phone

    # dedupes on a second run (same next_due)
    calls.clear()
    asyncio.run(reminders_svc.run_reminders())
    assert not any(marker in b for _to, b in calls)

    db.update_user("luke", {"phone": ""})
    db.delete_chore(c["id"])


# --- finance trends --------------------------------------------------------

def test_networth_trend_accrues_snapshot():
    # Calling build_networth() should upsert today's snapshot.
    networth_svc.build_networth()
    trend = networth_svc.build_networth_trend()
    assert "points" in trend and "current" in trend
    dates = [p["date"] for p in trend["points"]]
    assert date.today().isoformat() in dates


def test_spend_trend_shape():
    t = insights_svc.build_spend_trend(months=6)
    assert "months" in t
    assert len(t["months"]) == 6
    for m in t["months"]:
        assert set(m.keys()) >= {"key", "label", "spend"}
