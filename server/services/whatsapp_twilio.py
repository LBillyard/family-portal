"""WhatsApp via Twilio.

Works with the Twilio WhatsApp Sandbox (instant, no Meta account) and with a
production sender. Outbound is the REST Messages API; inbound is a form-encoded
webhook validated with X-Twilio-Signature.

Config (.env):
  TWILIO_ACCOUNT_SID    starts with AC...
  TWILIO_AUTH_TOKEN     account auth token (also used to validate inbound)
  TWILIO_WHATSAPP_FROM  sender, e.g. whatsapp:+14155238886 (sandbox number)
  TWILIO_CONTENT_SID    (optional) approved Content template for the digest ({{1}})
  TWILIO_VALIDATE       set to "false" to skip signature checks during setup
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

API = "https://api.twilio.com/2010-04-01"


def _sid() -> str:
    return os.environ.get("TWILIO_ACCOUNT_SID", "").strip()


def _auth_token() -> str:
    return os.environ.get("TWILIO_AUTH_TOKEN", "").strip()


def _from() -> str:
    f = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
    if f and not f.startswith("whatsapp:"):
        f = "whatsapp:" + f
    return f


def is_configured() -> bool:
    return bool(_sid() and _auth_token() and _from())


def _to_whatsapp(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = "44" + digits[1:]
    return "whatsapp:+" + digits


async def _send(data: dict) -> dict:
    if not is_configured():
        raise RuntimeError("WhatsApp (Twilio) not configured — set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")
    url = f"{API}/Accounts/{_sid()}/Messages.json"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, data=data, auth=(_sid(), _auth_token()))
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("message") or resp.text
            except Exception:
                msg = resp.text
            logger.error("WhatsApp (Twilio) send failed (%s): %s", resp.status_code, msg)
            raise RuntimeError(f"WhatsApp send failed: {msg}"[:300])
        return resp.json()


async def send_text(to: str, body: str) -> dict:
    return await _send({"From": _from(), "To": _to_whatsapp(to), "Body": body[:1600]})


async def send_digest(to: str, text: str) -> dict:
    """Use an approved Content template if configured (needed for the proactive
    7am send outside the 24h window); fall back to free-form if the template
    isn't usable yet (e.g. still pending approval) — that still delivers when
    the recipient has messaged within 24h."""
    content_sid = os.environ.get("TWILIO_CONTENT_SID", "").strip()
    if content_sid:
        try:
            return await _send({
                "From": _from(),
                "To": _to_whatsapp(to),
                "ContentSid": content_sid,
                "ContentVariables": json.dumps({"1": text}),
            })
        except Exception as exc:
            logger.warning("Template digest failed (%s); falling back to free-form", exc)
    return await _send({"From": _from(), "To": _to_whatsapp(to), "Body": text[:1600]})


def parse_inbound(form: dict) -> list[dict]:
    """Twilio inbound is form-encoded: From='whatsapp:+447...', Body, MessageSid."""
    body = (form.get("Body") or "").strip()
    frm = form.get("From", "")
    if not body or not frm.startswith("whatsapp:"):
        return []
    return [
        {
            "from": frm.split(":", 1)[1],  # +447911...
            "id": form.get("MessageSid", ""),
            "text": body,
            "name": form.get("ProfileName"),
        }
    ]


def validate_request(url: str, params: dict, signature: str | None) -> bool:
    """Validate X-Twilio-Signature = base64(HMAC-SHA1(auth_token, url + sorted params))."""
    if os.environ.get("TWILIO_VALIDATE", "true").strip().lower() == "false":
        return True
    token = _auth_token()
    if not token or not signature:
        return False
    payload = url
    for key in sorted(params.keys()):
        payload += key + str(params[key])
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)
