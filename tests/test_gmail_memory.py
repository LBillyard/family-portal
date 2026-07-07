"""Gmail → memory: extraction batching, dedupe against known, and the import route.

The Gmail client and the AI extraction call are both mocked so this runs offline.
"""

import asyncio
import hashlib

import pytest

from server import database as db
from server.services import gmail_memory, memory


@pytest.fixture(autouse=True)
def _clean_memory():
    for f in db.list_memory_facts(include_embedding=False):
        db.delete_memory_fact(f["id"])
    yield


def _fake_vec(text: str) -> list[float]:
    """64-dim word-hash bag so distinct facts don't collapse to cosine 1.0."""
    vec = [0.0] * 64
    for word in memory._norm(text).split():
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
    return vec or [1.0]


def test_body_text_prefers_plain_then_html():
    import base64

    def b64(s):
        return base64.urlsafe_b64encode(s.encode()).decode()

    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Your BMW policy AB12 CDE renews in March")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>ignored</p>")}},
    ]}
    assert "BMW policy AB12 CDE" in gmail_memory._body_text(payload)

    html_only = {"mimeType": "text/html", "body": {"data": b64("<div>Broadband is with <b>BT</b></div>")}}
    assert "Broadband is with BT" in gmail_memory._body_text(html_only)


def test_body_text_strips_html_hidden_in_plain_part_and_decodes_entities():
    """Airlines (Ryanair) put a full HTML document into a part labelled text/plain.
    A non-empty plain part must NOT be trusted as clean — tags are always stripped
    and HTML entities decoded, otherwise flight dates drown in markup."""
    import base64

    def b64(s):
        return base64.urlsafe_b64encode(s.encode()).decode()

    sneaky = {"mimeType": "text/plain", "body": {"data": b64(
        "<html><head><style>.x{color:red}</style></head><body>"
        "Flight FR4370 Manchester &rarr; Seville Tue, 16 Jun 26 &nbsp; 07:45 "
        "Total &pound;36.00</body></html>"
    )}}
    out = gmail_memory._body_text(sneaky)
    assert "<" not in out and "style" not in out            # tags + CSS gone
    assert "Flight FR4370 Manchester" in out and "16 Jun 26" in out
    assert "→" in out and "£36.00" in out                    # entities decoded
    assert "&nbsp;" not in out and "&pound;" not in out

    # A genuine plain-text body containing "<" (maths/comparisons) must be left
    # intact — the HTML heuristic keys on real tag names, not a bare "<".
    plainmath = {"mimeType": "text/plain", "body": {"data": b64(
        "Reminder: keep spend < 100 and a<b in the report"
    )}}
    assert gmail_memory._body_text(plainmath) == "Reminder: keep spend < 100 and a<b in the report"


def test_scan_dedupes_and_maps_source(client, monkeypatch):
    # Mock embed so remember()/known lookups don't hit the network.
    async def _embed(texts):
        return [_fake_vec(t) for t in texts]
    monkeypatch.setattr(memory, "embed", _embed)

    # Pre-seed a known fact so the extractor's output that duplicates it is dropped.
    asyncio.run(memory.remember("The car is a blue BMW 3 Series", category="possessions", subject="family"))

    emails = [
        {"n": 1, "subject": "Your renewal", "from": "Aviva <no-reply@aviva.co.uk>", "date": "", "body": "policy renews March"},
        {"n": 2, "subject": "Order", "from": "Amazon", "date": "", "body": "prime"},
    ]

    async def fake_scan_account(acct, known, known_norm, limit):
        # emulate the extractor returning one new + one already-known fact
        raw = [
            {"text": "Car insurance is with Aviva, renews in March", "category": "possessions", "subject": "family", "source": 1},
            {"text": "the car is a BLUE bmw 3 series.", "category": "possessions", "subject": "family", "source": 1},  # dup of known
        ]
        out = []
        by_n = {e["n"]: e for e in emails}
        for f in raw:
            if memory._norm(f["text"]) in known_norm:
                continue
            src = by_n.get(f["source"], {})
            out.append({"text": f["text"], "category": f["category"], "subject": "family",
                        "source_from": src.get("from", ""), "source_subject": src.get("subject", "")})
        return out, len(emails)

    monkeypatch.setattr(gmail_memory, "_scan_account", fake_scan_account)
    monkeypatch.setattr(db, "list_google_accounts", lambda uid=None: [{"id": "g1"}])
    monkeypatch.setattr(db, "get_google_account_internal", lambda gid: {"id": "g1", "token_json": "{}", "email": "x@y.com"})

    res = asyncio.run(gmail_memory.scan_for_facts("luke"))
    texts = [c["text"] for c in res["candidates"]]
    assert "Car insurance is with Aviva, renews in March" in texts
    assert not any("bmw" in t.lower() for t in texts), "known fact should be deduped out"
    assert res["candidates"][0]["source_from"].startswith("Aviva")


def test_import_email_route(client, monkeypatch):
    async def _embed(texts):
        return [_fake_vec(t) for t in texts]
    monkeypatch.setattr(memory, "embed", _embed)
    monkeypatch.setattr(memory, "is_enabled", lambda: True)

    before = len(db.list_memory_facts())
    r = client.post("/api/memory/import-email", json={"facts": [
        {"text": "Car insurance is with Aviva", "category": "possessions", "subject": "family"},
        {"text": "Home broadband is with BT", "category": "possessions", "subject": "family"},
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    assert len(db.list_memory_facts()) == before + 2
    # imported facts are tagged as sourced from email
    assert any(f["source"] == "email" for f in db.list_memory_facts())
