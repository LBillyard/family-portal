"""WhatsApp provider dispatcher.

Selects the active provider from WHATSAPP_PROVIDER (default 'meta'):
  - 'twilio' -> server.services.whatsapp_twilio
  - 'meta'   -> server.services.whatsapp_meta (Cloud API)

Sending (send_text for replies, send_digest for the morning digest) goes through
here so callers are provider-agnostic. Inbound webhooks stay provider-specific in
the routes, since Meta and Twilio deliver messages in different formats.
"""

from __future__ import annotations

import os

from server.services import whatsapp_meta, whatsapp_twilio


def provider() -> str:
    return os.environ.get("WHATSAPP_PROVIDER", "twilio").strip().lower()


def _impl():
    return whatsapp_twilio if provider() == "twilio" else whatsapp_meta


def is_configured() -> bool:
    return _impl().is_configured()


async def send_text(to: str, body: str) -> dict:
    return await _impl().send_text(to, body)


async def send_digest(to: str, text: str) -> dict:
    return await _impl().send_digest(to, text)
