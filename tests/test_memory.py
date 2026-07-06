"""Family memory: cosine ranking, dedupe, and the CRUD routes.

Embeddings are mocked (deterministic bag-of-words vectors) so these run offline
and don't call OpenRouter — they exercise our storage + retrieval logic, not the
embedding provider.
"""

import asyncio
import hashlib

import pytest

from server import database as db
from server.services import memory


def _fake_vec(text: str) -> list[float]:
    """Cheap deterministic 'embedding': a 64-dim word-hash bag. Shared wording →
    overlapping dims → higher cosine, which is all the ranking logic needs."""
    vec = [0.0] * 64
    for word in memory._norm(text).split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % 64] += 1.0
    return vec


@pytest.fixture(autouse=True)
def _clean_memory():
    """Isolate memory tests — the session DB is shared across test files."""
    for f in db.list_memory_facts(include_embedding=False):
        db.delete_memory_fact(f["id"])
    yield


@pytest.fixture()
def fake_embed(monkeypatch):
    async def _embed(texts):
        return [_fake_vec(t) for t in texts]
    monkeypatch.setattr(memory, "embed", _embed)
    monkeypatch.setattr(memory, "is_enabled", lambda: True)
    # Test ranking/pinning purely, independent of the tuned similarity floor.
    monkeypatch.setattr(memory, "RETRIEVE_MIN_SIM", 0.0)


def test_search_ranks_by_relevance(client, fake_embed):
    async def go():
        await memory.add_manual("Luke and Laura drive a Tesla Model 3", "possessions", "family", False)
        await memory.add_manual("Laura is vegetarian", "preferences", "partner", False)
        await memory.add_manual("Luke's mum lives in Leeds", "people", "luke", False)
        return await memory.search("what car do they drive", k=1)

    hits = asyncio.run(go())
    assert hits, "search returned nothing"
    assert "Tesla" in hits[0]["text"], f"top hit should be the car fact, got {hits[0]['text']!r}"


def test_exact_repeat_is_deduped(client, fake_embed):
    async def go():
        await memory.add_manual("They have a dog called Bella", "possessions", "family", False)
        await memory.add_manual("they have a DOG called bella.", "possessions", "family", False)

    before = len(db.list_memory_facts())
    asyncio.run(go())
    after = len(db.list_memory_facts())
    assert after == before + 1, "case/punctuation-only repeat should not create a second fact"


def test_pinned_always_returned(client, fake_embed):
    async def go():
        await memory.add_manual("They are saving for a kitchen renovation", "preferences", "family", True)
        return await memory.search("what is the capital of France", k=3)

    hits = asyncio.run(go())
    assert any("kitchen renovation" in h["text"] for h in hits), "pinned fact must always be considered"


def test_memory_routes_crud(client, monkeypatch):
    async def _embed(texts):
        return [_fake_vec(t) for t in texts]
    monkeypatch.setattr(memory, "embed", _embed)
    monkeypatch.setattr(memory, "is_enabled", lambda: True)

    r = client.post("/api/memory", json={"text": "We have a cat called Mochi", "category": "possessions", "subject": "family"})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    listing = client.get("/api/memory").json()
    assert any(f["id"] == fid for f in listing["facts"])
    assert listing["enabled"] is True
    assert set(listing["categories"]) == set(memory.CATEGORIES)

    r = client.patch(f"/api/memory/{fid}", json={"pinned": True})
    assert r.status_code == 200 and r.json()["pinned"] is True

    r = client.patch(f"/api/memory/{fid}", json={"text": "We have two cats, Mochi and Bean"})
    assert r.status_code == 200 and "two cats" in r.json()["text"]

    assert client.delete(f"/api/memory/{fid}").status_code == 200
    assert client.delete(f"/api/memory/{fid}").status_code == 404


def test_memory_requires_auth(client):
    client.post("/api/auth/logout")
    assert client.get("/api/memory").status_code == 401
    assert client.delete("/api/memory/anything").status_code == 401
