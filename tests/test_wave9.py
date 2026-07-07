"""Wave-9 backend: streamed media uploads (raised caps + chunked-to-disk),
a storage-stats endpoint, and WhatsApp (Twilio) media ingestion from KNOWN
household numbers only.

Pure helpers (ext_for_content_type, storage_stats) are driven directly; the
upload/storage routes use the shared authenticated `client` fixture; the
media-only inbound + known/unknown gate are covered via parse_inbound and the
webhook handler with network calls monkeypatched to recorders. Rows + files
live on a shared box, so every test cleans up the media it creates.
"""

import asyncio
import uuid

from server import database as db
from server.api import routes
from server.services import media as media_files
from server.services import whatsapp as whatsapp_svc
from server.services import whatsapp_twilio


# --- helpers ---------------------------------------------------------------

def _dir_files() -> set[str]:
    """Names of the files currently in MEDIA_DIR (dir is created if missing)."""
    media_files.ensure_media_dir()
    return {e.name for e in media_files.MEDIA_DIR.iterdir() if e.is_file()}


# --- 1. ext_for_content_type mapping ---------------------------------------

def test_ext_for_content_type_mapping():
    assert media_files.ext_for_content_type("image/jpeg") == ".jpg"
    assert media_files.ext_for_content_type("video/mp4") == ".mp4"
    assert media_files.ext_for_content_type("image/png") == ".png"
    # tolerant of a charset/param suffix and casing
    assert media_files.ext_for_content_type("IMAGE/JPEG; charset=binary") == ".jpg"
    # unknown / empty / None → None
    assert media_files.ext_for_content_type("application/pdf") is None
    assert media_files.ext_for_content_type("") is None
    assert media_files.ext_for_content_type(None) is None


# --- 2. storage_stats() shape ----------------------------------------------

def test_storage_stats_shape():
    stats = media_files.storage_stats()
    expected = {
        "disk_total", "disk_used", "disk_free",
        "media_bytes", "media_count", "disk_pct_used", "low",
    }
    assert expected <= set(stats)
    assert isinstance(stats["disk_total"], int) and stats["disk_total"] > 0
    assert isinstance(stats["disk_used"], int)
    assert isinstance(stats["disk_free"], int)
    assert isinstance(stats["media_bytes"], int)
    assert isinstance(stats["media_count"], int)
    assert isinstance(stats["disk_pct_used"], (int, float))
    assert isinstance(stats["low"], bool)


# --- 3. upload route: create (source=upload) → list → delete removes file ----

def test_media_upload_list_and_delete(client):
    payload = b"\xff\xd8\xff\xe0" + b"family-portal-test-" + uuid.uuid4().hex.encode()
    r = client.post(
        "/api/media/upload",
        files={"file": ("t.jpg", payload, "image/jpeg")},
        data={"title": "Wave9 upload"},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    mid = item["id"]
    assert item["source"] == "upload"
    assert item["media_type"] == "photo"
    assert item["file_size"] == len(payload) > 0

    stored = item["file_path"]
    disk_path = media_files.MEDIA_DIR / stored
    try:
        # file was actually streamed to disk
        assert disk_path.is_file()
        assert disk_path.stat().st_size == len(payload)

        # GET /api/media lists it
        listed = client.get("/api/media").json()["items"]
        assert any(x["id"] == mid for x in listed)

        # DELETE removes the row AND the file on disk
        d = client.delete(f"/api/media/{mid}")
        assert d.status_code == 200 and d.json()["ok"] is True
        assert not disk_path.exists()
        assert db.get_media(mid) is None
        # second delete → 404 (already gone)
        assert client.delete(f"/api/media/{mid}").status_code == 404
    finally:
        # belt-and-braces cleanup if an assertion above bailed early
        db.delete_media(mid)
        if disk_path.exists():
            disk_path.unlink()


# --- 4. oversized upload rejected, no leftover file ------------------------

def test_media_upload_oversized_rejected_no_leftover(client, monkeypatch):
    monkeypatch.setattr(media_files, "PHOTO_MAX_BYTES", 3)  # tiny cap
    payload = b"\xff\xd8\xff\xe0this-is-way-bigger-than-three-bytes"
    assert len(payload) > 3

    before = _dir_files()
    r = client.post(
        "/api/media/upload",
        files={"file": ("big.jpg", payload, "image/jpeg")},
    )
    assert r.status_code == 400, r.text
    # the partial file must have been cleaned up — no new file lingers
    after = _dir_files()
    assert after == before, f"leftover files: {after - before}"


# --- 5. storage route via client -------------------------------------------

def test_media_storage_route(client):
    r = client.get("/api/media/storage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disk_total"] > 0
    for key in ("disk_used", "disk_free", "media_bytes", "media_count", "disk_pct_used", "low"):
        assert key in body


# --- 6. parse_inbound: media-only (empty Body) is NOT dropped ---------------

def test_parse_inbound_media_only():
    form = {
        "From": "whatsapp:+447700900123",
        "Body": "",                       # media with no caption
        "MessageSid": "SM_wave9_test",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/media/abc",
        "MediaContentType0": "image/jpeg",
        "ProfileName": "Tester",
    }
    msgs = whatsapp_twilio.parse_inbound(form)
    assert len(msgs) == 1
    m = msgs[0]
    assert m["from"] == "+447700900123"
    assert m["text"] == ""
    assert len(m["media"]) == 1
    assert m["media"][0]["url"] == "https://api.twilio.com/media/abc"
    assert m["media"][0]["content_type"] == "image/jpeg"

    # sanity: a truly empty inbound (no body, no media) is still dropped
    assert whatsapp_twilio.parse_inbound(
        {"From": "whatsapp:+447700900123", "Body": "", "NumMedia": "0"}
    ) == []


# --- 7. webhook handler: KNOWN number ingests media; UNKNOWN is ignored -----

def test_whatsapp_media_ingest_known_vs_unknown(monkeypatch):
    known = "+447700900999"
    unknown = "+447700900111"   # different last-9 digits → not a household member

    sends: list[tuple[str, str]] = []
    downloads: list[str] = []

    async def fake_send_text(to: str, body: str) -> dict:
        sends.append((to, body))
        return {"sid": "test"}

    async def fake_download_media(url: str) -> tuple[bytes, str]:
        downloads.append(url)
        return b"\xff\xd8\xff", "image/jpeg"

    monkeypatch.setattr(whatsapp_svc, "send_text", fake_send_text)
    monkeypatch.setattr(whatsapp_twilio, "download_media", fake_download_media)

    db.update_user("luke", {"phone": known})
    before_ids = {x["id"] for x in db.list_media()}
    new_files: set[str] = set()
    try:
        # --- KNOWN number: media is downloaded + stored with source='whatsapp' ---
        files_before = _dir_files()
        known_msg = {
            "from": known,
            "id": "SM_known",
            "text": "",
            "name": "Luke",
            "media": [{"url": "https://twilio/known", "content_type": "image/jpeg"}],
        }
        asyncio.run(routes._handle_whatsapp_message(known_msg))
        new_files = _dir_files() - files_before

        new_ids = {x["id"] for x in db.list_media()} - before_ids
        assert len(new_ids) == 1, new_ids
        created = db.get_media(next(iter(new_ids)))
        assert created["source"] == "whatsapp"
        assert created["media_type"] == "photo"
        assert created["file_size"] == 3
        assert downloads == ["https://twilio/known"]
        # confirmation reply was sent back to the sender (no network — recorded)
        assert any(to == known and "photos" in body.lower() for to, body in sends)

        # --- UNKNOWN number: silently ignored, nothing downloaded or stored ---
        downloads.clear()
        sends.clear()
        ids_before_unknown = {x["id"] for x in db.list_media()}
        unknown_msg = {
            "from": unknown,
            "id": "SM_unknown",
            "text": "",
            "name": "Stranger",
            "media": [{"url": "https://twilio/unknown", "content_type": "image/jpeg"}],
        }
        asyncio.run(routes._handle_whatsapp_message(unknown_msg))
        assert downloads == []          # gated before any download
        assert sends == []              # strangers get no reply
        assert {x["id"] for x in db.list_media()} == ids_before_unknown  # no new row
    finally:
        db.update_user("luke", {"phone": ""})
        for mid in {x["id"] for x in db.list_media()} - before_ids:
            db.delete_media(mid)
        for name in new_files:
            (media_files.MEDIA_DIR / name).unlink(missing_ok=True)
