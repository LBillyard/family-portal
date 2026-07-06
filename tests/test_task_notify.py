"""Task edit 'Notify owner on WhatsApp' is opt-in per save: it sends only when
ticked, and it sends whether or not the owner changed."""

from server.services import assistant as ai_assistant


def test_notify_is_opt_in_per_edit(client, monkeypatch):
    # A task owned by the other household member (Laura = 'partner').
    tid = client.post("/api/tasks", json={"title": "Notify test", "assignee_id": "partner"}).json()["id"]

    calls = []

    async def spy(task, sender, verb="added a task for you"):
        calls.append(verb)

    monkeypatch.setattr(ai_assistant, "notify_task_assignee", spy)

    # 1) Edit a field with notify UNticked -> no WhatsApp.
    client.patch(f"/api/tasks/{tid}", json={"title": "v2", "notify": False})
    assert calls == []

    # 2) Edit a non-owner field with notify TICKED (no reassignment) -> sends.
    client.patch(f"/api/tasks/{tid}", json={"title": "v3", "notify": True})
    assert calls == ["updated a task for you"]

    # 3) Reassign with notify ticked -> sends with the reassigned verb.
    client.patch(f"/api/tasks/{tid}", json={"assignee_id": "luke", "notify": True})
    assert calls == ["updated a task for you", "reassigned a task to you"]

    # 4) Omitting notify entirely -> no send (default is off).
    client.patch(f"/api/tasks/{tid}", json={"title": "v4"})
    assert len(calls) == 2

    client.delete(f"/api/tasks/{tid}")
