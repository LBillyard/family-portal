"""Wave-17 backend: "Snap-and-sort".

A family member sends a PHOTO to the Hub's WhatsApp number, a vision model
classifies it, and it is routed automatically: receipt -> expense + Vault copy,
document -> filed in the Vault, anything else -> the photo gallery.

Everything external is mocked — NO network is ever touched:
  * the OpenRouter vision POST is replaced with a fake httpx.AsyncClient (group 1),
  * classify_and_extract itself is monkeypatched for the routing tests (group 2),
  * the db / media helpers are stubbed to recorders (or run against the isolated
    test DB) so we assert on calls / rows without side effects.

Covers:
  1. classify_and_extract validation — kind whitelisting, amount>0 demotion,
     bad dates -> null, document-without-name -> "photo", and a thrown error /
     garbage yielding the safe {"kind":"photo"} fallback (never raises).
  2. handle_image routing — receipt (txn + receipt + Vault copy + amount in the
     summary), document (expiry on BOTH columns), photo (gallery save), and a
     receipt with NO connected account falling back to a gallery save.
  3. the snap_sort_enabled pref round-trips through get/update_notification_prefs.
  4. media.save_inbound_media writes a row for an image and returns None for an
     unknown content-type.
"""

import asyncio
import json

import pytest

from server import database as db
from server.services import documents, media, memory, snap_sort


def _run(coro):
    return asyncio.run(coro)


# A tiny but valid-looking JPEG header; contents are irrelevant (vision is mocked).
IMG = b"\xff\xd8\xff\xe0" + b"snap-sort-test-bytes"
USER = {"id": "luke"}


# --------------------------------------------------------------------------- #
# Fake vision transport (used only by group 1)
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, content, status_code=200):
        self._content = content
        self.status_code = status_code
        self.text = content if isinstance(content, str) else str(content)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _make_client(content, status_code=200, raise_exc=None):
    """Build a drop-in for httpx.AsyncClient whose .post returns a canned model
    reply (or raises), so classify_and_extract never touches the network."""

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            if raise_exc is not None:
                raise raise_exc
            return _FakeResp(content, status_code)

    return _FakeClient


def _patch_vision(monkeypatch, *, content=None, status_code=200, raise_exc=None):
    # No real API key needed — _headers() would otherwise raise without one.
    monkeypatch.setattr(memory, "_headers", lambda: {})
    monkeypatch.setattr(
        snap_sort.httpx, "AsyncClient", _make_client(content, status_code, raise_exc)
    )


def _classify(monkeypatch, model_reply: dict, **kw) -> dict:
    _patch_vision(monkeypatch, content=json.dumps(model_reply), **kw)
    return _run(snap_sort.classify_and_extract(IMG, "image/jpeg"))


# ========================================================================== #
# 1. classify_and_extract — untrusted-model-output validation
# ========================================================================== #

def test_classify_receipt_extracts_fields(monkeypatch):
    res = _classify(monkeypatch, {
        "kind": "receipt",
        "receipt": {"merchant": "Tesco", "amount": 12.5, "date": "2026-01-02", "category": "Groceries"},
        "document": None,
        "reason": "a till receipt",
    })
    assert res["kind"] == "receipt"
    assert res["receipt"]["merchant"] == "Tesco"
    assert res["receipt"]["amount"] == 12.5
    assert res["receipt"]["date"] == "2026-01-02"
    assert res["receipt"]["category"] == "Groceries"
    assert res["document"] is None


def test_classify_document_extracts_fields_and_whitelists_doc_type(monkeypatch):
    # doc_type "spaceship" is not in the whitelist → coerced to "other".
    res = _classify(monkeypatch, {
        "kind": "document",
        "receipt": None,
        "document": {"name": "Passport", "doc_type": "spaceship", "expiry_date": "2030-05-05"},
        "reason": "an official document",
    })
    assert res["kind"] == "document"
    assert res["document"]["name"] == "Passport"
    assert res["document"]["doc_type"] == "other"
    assert res["document"]["expiry_date"] == "2030-05-05"
    assert res["receipt"] is None


def test_classify_photo_stays_photo(monkeypatch):
    res = _classify(monkeypatch, {
        "kind": "photo", "receipt": None, "document": None, "reason": "a family selfie",
    })
    assert res["kind"] == "photo"
    assert res["receipt"] is None and res["document"] is None


def test_classify_garbage_falls_back_to_photo(monkeypatch):
    # Non-JSON model output must NOT raise — it degrades to the safe photo fallback.
    _patch_vision(monkeypatch, content="I am not JSON at all {{{ nope")
    res = _run(snap_sort.classify_and_extract(IMG, "image/jpeg"))
    assert res == {"kind": "photo", "receipt": None, "document": None, "reason": "fallback"}


def test_classify_unknown_kind_is_whitelisted_to_photo(monkeypatch):
    # "invoice" is not one of receipt|document|photo → demoted to photo, and the
    # (would-be valid) receipt block is dropped.
    res = _classify(monkeypatch, {
        "kind": "invoice",
        "receipt": {"merchant": "X", "amount": 9.99},
        "document": None,
        "reason": "not a whitelisted kind",
    })
    assert res["kind"] == "photo"
    assert res["receipt"] is None


@pytest.mark.parametrize("amount", [0, -5, "not-a-number"])
def test_classify_receipt_without_positive_amount_demotes_to_photo(monkeypatch, amount):
    # A "receipt" with a non-positive / unparseable amount is NOT money — it must
    # never be logged as an expense, so it demotes to a plain photo.
    res = _classify(monkeypatch, {
        "kind": "receipt",
        "receipt": {"merchant": "Sketchy", "amount": amount, "date": "2026-01-01", "category": "C"},
        "document": None,
        "reason": "no real total",
    })
    assert res["kind"] == "photo"
    assert res["receipt"] is None


def test_classify_bad_dates_become_null(monkeypatch):
    # Valid amount keeps the receipt, but an unreadable date is nulled out.
    res = _classify(monkeypatch, {
        "kind": "receipt",
        "receipt": {"merchant": "Shop", "amount": 10, "date": "31-31-2026", "category": "C"},
        "document": None,
        "reason": "date unreadable",
    })
    assert res["kind"] == "receipt"
    assert res["receipt"]["date"] is None

    # Same for a document expiry that can't be parsed.
    res2 = _classify(monkeypatch, {
        "kind": "document",
        "receipt": None,
        "document": {"name": "Warranty", "doc_type": "warranty", "expiry_date": "sometime soon"},
        "reason": "expiry unreadable",
    })
    assert res2["kind"] == "document"
    assert res2["document"]["expiry_date"] is None


def test_classify_document_without_name_demotes_to_photo(monkeypatch):
    res = _classify(monkeypatch, {
        "kind": "document",
        "receipt": None,
        "document": {"doc_type": "passport", "expiry_date": "2030-01-01"},  # no name
        "reason": "no name",
    })
    assert res["kind"] == "photo"
    assert res["document"] is None


def test_classify_thrown_error_returns_photo_fallback(monkeypatch):
    # A transport-level exception must be swallowed → safe photo fallback, no raise.
    _patch_vision(monkeypatch, raise_exc=RuntimeError("boom"))
    res = _run(snap_sort.classify_and_extract(IMG, "image/jpeg"))
    assert res == {"kind": "photo", "receipt": None, "document": None, "reason": "fallback"}


def test_classify_http_error_returns_photo_fallback(monkeypatch):
    # A >=400 status from OpenRouter is treated as a failure → photo fallback.
    _patch_vision(monkeypatch, content="upstream exploded", status_code=500)
    res = _run(snap_sort.classify_and_extract(IMG, "image/jpeg"))
    assert res["kind"] == "photo"
    assert res["reason"] == "fallback"


# ========================================================================== #
# 2. handle_image routing (classify_and_extract stubbed — no vision, no network)
# ========================================================================== #

class _Recorder:
    """Collects calls to the stubbed db/media helpers so tests can assert on them."""

    def __init__(self):
        self.transactions = []
        self.receipts = []
        self.documents = []
        self.media = []

    def install(self, monkeypatch, *, account="acc1", tmp_dir=None):
        monkeypatch.setattr(db, "resolve_account_id", lambda preferred=None: account)

        def _create_transaction(data):
            self.transactions.append(data)
            return {"id": "txn1", **data}

        def _create_receipt(data):
            self.receipts.append(data)
            return {"id": "rcpt1"}

        def _create_document(data):
            self.documents.append(data)
            return {"id": data.get("id", "doc1")}

        def _save_media(image_bytes, content_type, user, source="whatsapp"):
            self.media.append({"bytes": image_bytes, "content_type": content_type, "user": user})
            return {"id": "media1"}

        monkeypatch.setattr(db, "create_transaction", _create_transaction)
        monkeypatch.setattr(db, "create_receipt", _create_receipt)
        monkeypatch.setattr(db, "create_document", _create_document)
        monkeypatch.setattr(media, "save_inbound_media", _save_media)
        # Redirect Vault writes to a throwaway dir so _file_to_vault's disk write is harmless.
        if tmp_dir is not None:
            monkeypatch.setattr(documents, "UPLOAD_DIR", tmp_dir)


def _stub_classify(monkeypatch, result: dict):
    async def _fake(image_bytes, mime):
        return result

    monkeypatch.setattr(snap_sort, "classify_and_extract", _fake)


def test_handle_image_receipt_logs_expense_files_vault_and_reports_amount(monkeypatch, tmp_path):
    rec = _Recorder()
    rec.install(monkeypatch, account="acc1", tmp_dir=tmp_path)
    _stub_classify(monkeypatch, {
        "kind": "receipt",
        "receipt": {"merchant": "Tesco", "amount": 12.5, "date": "2026-01-02", "category": "Groceries"},
        "document": None,
        "reason": "receipt",
    })

    res = _run(snap_sort.handle_image(IMG, "image/jpeg", USER))

    assert res["kind"] == "receipt"

    # An expense transaction was created — stored as a NEGATIVE amount.
    assert len(rec.transactions) == 1
    txn = rec.transactions[0]
    assert txn["amount"] == -12.5
    assert txn["description"] == "Tesco"
    assert txn["category"] == "Groceries"
    assert txn["date"] == "2026-01-02"
    assert txn["account_id"] == "acc1"

    # A receipt row linked to that transaction was created.
    assert len(rec.receipts) == 1
    assert rec.receipts[0]["transaction_id"] == "txn1"
    assert rec.receipts[0]["user_id"] == "luke"

    # The image itself was ALSO filed into the Vault (financial category, no expiry).
    assert len(rec.documents) == 1
    filed = rec.documents[0]
    assert filed["category"] == "financial"
    assert filed["expiry"] is None
    assert "Receipt" in filed["name"]

    # The reply mentions the amount (and merchant).
    assert "12.50" in res["summary"]
    assert "Tesco" in res["summary"]


def test_handle_image_document_files_vault_with_expiry_on_both_columns(monkeypatch, tmp_path):
    rec = _Recorder()
    rec.install(monkeypatch, account="acc1", tmp_dir=tmp_path)
    _stub_classify(monkeypatch, {
        "kind": "document",
        "receipt": None,
        "document": {"name": "Car insurance", "doc_type": "insurance", "expiry_date": "2030-05-05"},
        "reason": "document",
    })

    res = _run(snap_sort.handle_image(IMG, "image/jpeg", USER))

    assert res["kind"] == "document"
    # Filed once; NO transaction for a document.
    assert len(rec.documents) == 1
    assert rec.transactions == []
    filed = rec.documents[0]
    assert filed["name"] == "Car insurance"
    # Expiry is written to BOTH columns (Vault badge + renewal reminder).
    assert filed["expiry"] == "2030-05-05"
    assert filed["expiry_date"] == "2030-05-05"
    assert "Car insurance" in res["summary"]
    assert "2030-05-05" in res["summary"]


def test_handle_image_photo_saves_to_gallery(monkeypatch):
    rec = _Recorder()
    rec.install(monkeypatch)
    _stub_classify(monkeypatch, {
        "kind": "photo", "receipt": None, "document": None, "reason": "family photo",
    })

    res = _run(snap_sort.handle_image(IMG, "image/jpeg", USER))

    assert res["kind"] == "photo"
    # Exactly one gallery save, with the untouched bytes; no ledger/Vault writes.
    assert len(rec.media) == 1
    assert rec.media[0]["bytes"] == IMG
    assert rec.media[0]["content_type"] == "image/jpeg"
    assert rec.transactions == []
    assert rec.documents == []


def test_handle_image_receipt_without_account_falls_back_to_gallery(monkeypatch):
    rec = _Recorder()
    # No connected account → can't log an expense.
    rec.install(monkeypatch, account=None)
    _stub_classify(monkeypatch, {
        "kind": "receipt",
        "receipt": {"merchant": "Tesco", "amount": 12.5, "date": "2026-01-02", "category": "Groceries"},
        "document": None,
        "reason": "receipt but no bank",
    })

    res = _run(snap_sort.handle_image(IMG, "image/jpeg", USER))

    # Falls back to a gallery save — the photo is kept, NO transaction logged.
    assert res["kind"] == "photo"
    assert rec.transactions == []
    assert rec.receipts == []
    assert len(rec.media) == 1
    assert rec.media[0]["bytes"] == IMG


# ========================================================================== #
# 3. snap_sort_enabled preference round-trip
# ========================================================================== #

def test_snap_sort_enabled_pref_round_trips():
    original = db.get_notification_prefs()["snap_sort_enabled"]
    try:
        # Defaults ON.
        assert original is True

        off = db.update_notification_prefs({"snap_sort_enabled": False})
        assert off["snap_sort_enabled"] is False
        assert db.get_notification_prefs()["snap_sort_enabled"] is False

        on = db.update_notification_prefs({"snap_sort_enabled": True})
        assert on["snap_sort_enabled"] is True
        assert db.get_notification_prefs()["snap_sort_enabled"] is True
    finally:
        db.update_notification_prefs({"snap_sort_enabled": original})


# ========================================================================== #
# 4. media.save_inbound_media — real writes against the isolated test DB
# ========================================================================== #

def test_save_inbound_media_writes_row_for_image(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path / "media")
    row = media.save_inbound_media(IMG, "image/jpeg", USER)
    assert row is not None
    assert row["media_type"] == "photo"
    # The row is actually persisted and fetchable.
    stored = db.get_media(row["id"])
    assert stored is not None
    assert stored["source"] == "whatsapp"
    # The bytes really landed on disk.
    assert (tmp_path / "media" / stored["file_name"]).exists()


def test_save_inbound_media_unknown_content_type_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path / "media")
    # application/pdf is not a gallery media type → no row, no raise, just None.
    assert media.save_inbound_media(IMG, "application/pdf", USER) is None
