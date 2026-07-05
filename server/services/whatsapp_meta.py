"""WhatsApp via the Meta (Facebook) Cloud API.

Outbound: free-form text (24h window, e.g. replies) and template messages
(business-initiated, e.g. the 7am digest). Inbound: webhook verification +
message parsing + X-Hub-Signature-256 checking.

Config (.env): WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN,
WHATSAPP_APP_SECRET, WHATSAPP_API_VERSION, WHATSAPP_TEMPLATE_NAME, WHATSAPP_TEMPLATE_LANG.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"


def _api_version() -> str:
    return os.environ.get("WHATSAPP_API_VERSION", "v21.0").strip() or "v21.0"


def _token() -> str:
    return os.environ.get("WHATSAPP_TOKEN", "").strip()


def _phone_number_id() -> str:
    return os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()


def verify_token() -> str:
    return os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()


def template_name() -> str:
    return os.environ.get("WHATSAPP_TEMPLATE_NAME", "daily_digest").strip() or "daily_digest"


def template_lang() -> str:
    return os.environ.get("WHATSAPP_TEMPLATE_LANG", "en_GB").strip() or "en_GB"


def is_configured() -> bool:
    return bool(_token() and _phone_number_id())


def normalize_to(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = "44" + digits[1:]
    return digits


def _messages_url() -> str:
    return f"{GRAPH}/{_api_version()}/{_phone_number_id()}/messages"


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


async def send_text(to: str, body: str) -> dict:
    if not is_configured():
        raise RuntimeError("WhatsApp (Meta) not configured — set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalize_to(to),
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    return await _post(payload)


async def send_template(to: str, body_param: str, name: str | None = None, lang: str | None = None) -> dict:
    if not is_configured():
        raise RuntimeError("WhatsApp (Meta) not configured — set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_to(to),
        "type": "template",
        "template": {
            "name": name or template_name(),
            "language": {"code": lang or template_lang()},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": body_param[:1024]}]}],
        },
    }
    return await _post(payload)


async def send_digest(to: str, text: str) -> dict:
    return await send_template(to, text)


async def _post(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_messages_url(), json=payload, headers=_headers())
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message") or resp.text
            except Exception:
                msg = resp.text
            logger.error("WhatsApp (Meta) send failed (%s): %s", resp.status_code, msg)
            raise RuntimeError(f"WhatsApp send failed: {msg}"[:300])
        return resp.json()


def verify_webhook(mode: str, token: str, challenge: str) -> str | None:
    expected = verify_token()
    if mode == "subscribe" and expected and token == expected:
        return challenge
    return None


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    if not app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def parse_inbound(payload: dict) -> list[dict]:
    out: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                frm = msg.get("from", "")
                out.append(
                    {
                        "from": frm,
                        "id": msg.get("id", ""),
                        "text": (msg.get("text") or {}).get("body", ""),
                        "name": contacts.get(frm),
                    }
                )
    return out
