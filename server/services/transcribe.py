"""Voice-note transcription via OpenRouter's speech-to-text endpoint.

DORMANT by default: costs nothing until an admin sets VOICE_NOTES_ENABLED=1
(and an OPENROUTER_API_KEY is present). When a household member sends a WhatsApp
voice note, the webhook downloads the audio and calls transcribe() here; the
transcript is then fed to the AI assistant as if the member had typed it.

Reuses the existing OPENROUTER_API_KEY. A failed transcription degrades
gracefully (returns None) — it must NEVER raise into the webhook handler.
"""

from __future__ import annotations

import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)

TRANSCRIBE_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

# Maps a WhatsApp/HTTP audio content-type to the "format" hint the endpoint wants.
_FORMAT_MAP = {
    "audio/ogg": "ogg",       # WhatsApp voice notes (opus in ogg)
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/aac": "aac",
    "audio/flac": "flac",
}


def is_enabled() -> bool:
    """True only when explicitly switched on AND an API key is present."""
    flag = os.environ.get("VOICE_NOTES_ENABLED", "").strip().lower()
    return flag in ("1", "true", "yes", "on") and bool(
        os.environ.get("OPENROUTER_API_KEY", "").strip()
    )


def _format_for(content_type: str) -> str:
    """Resolve the audio format hint from a content-type header.

    Strips any ";codecs=..." parameter first (e.g. "audio/ogg; codecs=opus"),
    then looks up the known map, falling back to the subtype after "audio/".
    """
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in _FORMAT_MAP:
        return _FORMAT_MAP[ct]
    if ct.startswith("audio/"):
        sub = ct.split("/", 1)[1].strip()
        if sub:
            return sub
    return "ogg"


async def transcribe(audio_bytes: bytes, content_type: str) -> str | None:
    """Transcribe audio to text via OpenRouter. Returns None on any failure.

    Never raises — a failed transcription must degrade gracefully so the webhook
    can fall back to asking the sender to try again or send text.
    """
    if not is_enabled() or not audio_bytes:
        return None
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("VOICE_TRANSCRIBE_MODEL", "openai/whisper-1").strip() or "openai/whisper-1"
    fmt = _format_for(content_type)
    try:
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "model": model,
            "input_audio": {"data": b64, "format": fmt},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(TRANSCRIBE_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            # Don't log the API key or the audio bytes — just the status/body snippet.
            body = ""
            try:
                body = resp.text[:300]
            except Exception:
                pass
            logger.warning("Voice transcription failed (HTTP %s): %s", resp.status_code, body)
            return None
        text = (resp.json().get("text") or "").strip()
        return text or None
    except Exception as exc:
        logger.warning("Voice transcription error: %s", exc)
        return None
