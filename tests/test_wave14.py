"""Wave-14 backend: WhatsApp voice-note transcription (dormant by default).

Covers the transcribe service gate + format mapping, the /voice-status route,
and the inbound-audio path through _handle_whatsapp_message — disabled, enabled,
and the unknown-number security gate. Everything external (Twilio download,
OpenRouter transcription, the AI assistant, and the outbound send) is
monkeypatched to recorders — NO real network is touched. Env + the seeded user's
phone are reset in teardown.
"""

import asyncio

import pytest

from server import database as db
from server.api import routes
from server.services import assistant as ai_assistant
from server.services import transcribe
from server.services import whatsapp as whatsapp_svc
from server.services import whatsapp_twilio


# --- 1. is_enabled() gate --------------------------------------------------

def test_is_enabled_off_without_env(monkeypatch):
    # Neither switch present → dormant.
    monkeypatch.delenv("VOICE_NOTES_ENABLED", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert transcribe.is_enabled() is False

    # Flag on but no key → still off.
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "true")
    assert transcribe.is_enabled() is False

    # Key present but flag off → still off.
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert transcribe.is_enabled() is False


def test_is_enabled_on_with_both_set(monkeypatch):
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert transcribe.is_enabled() is True


# --- 2. _format_for content-type mapping -----------------------------------

def test_format_for_mapping():
    # ";codecs=..." param is stripped before lookup.
    assert transcribe._format_for("audio/ogg; codecs=opus") == "ogg"
    assert transcribe._format_for("audio/mp4") == "m4a"
    # unknown audio/* falls back to the subtype after "audio/".
    assert transcribe._format_for("audio/xyz") == "xyz"


# --- 3. transcribe() degrades gracefully when disabled ---------------------

def test_transcribe_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("VOICE_NOTES_ENABLED", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Never raises, never hits the network — just None.
    assert asyncio.run(transcribe.transcribe(b"some-bytes", "audio/ogg")) is None


# --- 4. GET /api/whatsapp/voice-status -------------------------------------

def test_voice_status_route(client, monkeypatch):
    monkeypatch.delenv("VOICE_NOTES_ENABLED", raising=False)
    r = client.get("/api/whatsapp/voice-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "enabled" in body and isinstance(body["enabled"], bool)
    assert body["enabled"] is False

    # Flip both switches → route reflects enabled=True.
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert client.get("/api/whatsapp/voice-status").json()["enabled"] is True


# --- webhook audio-path helpers --------------------------------------------

def _audio_msg(frm: str) -> dict:
    return {
        "from": frm,
        "id": "SM_wave14",
        "text": "",   # voice note has no caption
        "name": "Luke",
        "media": [{"url": "https://twilio/voice", "content_type": "audio/ogg"}],
    }


# --- 5a. audio path, voice notes DISABLED → "not switched on", no AI --------

def test_audio_disabled_replies_not_switched_on(monkeypatch):
    monkeypatch.delenv("VOICE_NOTES_ENABLED", raising=False)

    sends: list[tuple[str, str]] = []
    downloads: list[str] = []
    ai_calls: list = []

    async def fake_send_text(to: str, body: str) -> dict:
        sends.append((to, body))
        return {"sid": "test"}

    async def fake_download_media(url: str):
        downloads.append(url)
        return b"x", "audio/ogg"

    async def fake_chat(*a, **kw):
        ai_calls.append((a, kw))
        return {"reply": "should not run"}

    monkeypatch.setattr(whatsapp_svc, "send_text", fake_send_text)
    monkeypatch.setattr(whatsapp_twilio, "download_media", fake_download_media)
    monkeypatch.setattr(ai_assistant, "chat", fake_chat)

    known = "+447700900555"
    db.update_user("luke", {"phone": known})
    try:
        asyncio.run(routes._handle_whatsapp_message(_audio_msg(known)))
        # exactly one reply, back to the sender, saying it's not switched on
        assert len(sends) == 1
        to, body = sends[0]
        assert to == known
        assert "switched on" in body.lower()
        # gated before any download or AI call
        assert downloads == []
        assert ai_calls == []
    finally:
        db.update_user("luke", {"phone": ""})


# --- 5b. audio path, voice notes ENABLED → transcript + AI reply -----------

def test_audio_enabled_transcribes_and_runs_ai(monkeypatch):
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")

    sends: list[tuple[str, str]] = []
    downloads: list[str] = []
    transcribe_args: list[tuple[bytes, str]] = []
    chat_args: list = []

    async def fake_send_text(to: str, body: str) -> dict:
        sends.append((to, body))
        return {"sid": "test"}

    async def fake_download_media(url: str):
        downloads.append(url)
        return b"x", "audio/ogg"

    async def fake_transcribe(data: bytes, content_type: str):
        transcribe_args.append((data, content_type))
        return "buy milk"

    async def fake_chat(user, message, channel=None):
        chat_args.append((user, message, channel))
        return {"reply": "Added milk"}

    monkeypatch.setattr(whatsapp_svc, "send_text", fake_send_text)
    monkeypatch.setattr(whatsapp_twilio, "download_media", fake_download_media)
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    monkeypatch.setattr(ai_assistant, "chat", fake_chat)

    known = "+447700900666"
    db.update_user("luke", {"phone": known})
    try:
        asyncio.run(routes._handle_whatsapp_message(_audio_msg(known)))

        # downloaded the audio, transcribed the downloaded bytes/type
        assert downloads == ["https://twilio/voice"]
        assert transcribe_args == [(b"x", "audio/ogg")]
        # AI ran on the transcript for the matched household user
        assert len(chat_args) == 1
        user_arg, msg_arg, channel_arg = chat_args[0]
        assert msg_arg == "buy milk"
        assert channel_arg == "whatsapp"
        assert user_arg["id"] == "luke"
        # single reply back to the sender containing BOTH transcript and AI reply
        assert len(sends) == 1
        to, body = sends[0]
        assert to == known
        assert "buy milk" in body
        assert "Added milk" in body
    finally:
        db.update_user("luke", {"phone": ""})


# --- 5c. unknown number's voice note is ignored (security gate) -------------

def test_audio_unknown_number_ignored(monkeypatch):
    monkeypatch.setenv("VOICE_NOTES_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")

    sends: list[tuple[str, str]] = []
    downloads: list[str] = []

    async def fake_send_text(to: str, body: str) -> dict:
        sends.append((to, body))
        return {"sid": "test"}

    async def fake_download_media(url: str):
        downloads.append(url)
        return b"x", "audio/ogg"

    async def fake_transcribe(data, content_type):
        return "buy milk"

    async def fake_chat(*a, **kw):
        return {"reply": "nope"}

    monkeypatch.setattr(whatsapp_svc, "send_text", fake_send_text)
    monkeypatch.setattr(whatsapp_twilio, "download_media", fake_download_media)
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    monkeypatch.setattr(ai_assistant, "chat", fake_chat)

    # Make sure luke owns a DIFFERENT number so the unknown one matches nobody.
    db.update_user("luke", {"phone": "+447700900777"})
    unknown = "+447700900222"
    try:
        assert db.get_user_by_phone(unknown) is None   # precondition: truly unknown
        asyncio.run(routes._handle_whatsapp_message(_audio_msg(unknown)))
        # strangers get no reply and trigger no download/transcription
        assert sends == []
        assert downloads == []
    finally:
        db.update_user("luke", {"phone": ""})
