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

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

import httpx

logger = logging.getLogger(__name__)

API = "https://api.twilio.com/2010-04-01"
CONTENT_API = "https://content.twilio.com/v1"

# Whether the digest Content template is Meta-approved — cached so we don't hit the
# Content API on every send. An approved template delivers outside the 24h window;
# until then we fall back to a free-form message (which delivers inside the window).
_approval = {"ts": 0.0, "approved": False}
_APPROVAL_TTL = 1800.0


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


async def template_approved() -> bool:
    """Is the digest Content template Meta-approved? Cached for _APPROVAL_TTL.

    A pending/rejected template silently FAILS at delivery (Twilio accepts the
    send, then WhatsApp rejects it with 63112) — so we must not use it until it's
    actually approved."""
    content_sid = os.environ.get("TWILIO_CONTENT_SID", "").strip()
    if not content_sid or not is_configured():
        return False
    now = time.time()
    if now - _approval["ts"] < _APPROVAL_TTL:
        return _approval["approved"]
    approved = _approval["approved"]  # keep last-known on error
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{CONTENT_API}/Content/{content_sid}/ApprovalRequests", auth=(_sid(), _auth_token()))
            r.raise_for_status()
            approved = (r.json().get("whatsapp") or {}).get("status", "") == "approved"
    except Exception as exc:
        logger.warning("Could not check template approval: %s", exc)
    _approval.update(ts=now, approved=approved)
    return approved


async def message_status(sid: str) -> dict:
    """Fetch a sent message's current delivery status (queued/sent/delivered/read/failed)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{API}/Accounts/{_sid()}/Messages/{sid}.json", auth=(_sid(), _auth_token()))
        r.raise_for_status()
        return r.json()


async def confirm_delivery(sid: str | None, timeout: float = 12.0) -> str:
    """Poll a message until it reaches a terminal state or timeout. Returns the
    Twilio status ('delivered'/'read'/'failed'/'undelivered'/'sent'/'queued')."""
    if not sid:
        return "unknown"
    status = "queued"
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(2.5)
        waited += 2.5
        try:
            st = await message_status(sid)
        except Exception:
            continue
        status = st.get("status", status)
        if status in ("delivered", "read", "failed", "undelivered"):
            break
    return status


async def send_digest(to: str, text: str) -> dict:
    """Deliver the morning digest. Uses the approved Content template when Meta has
    approved it (works any time, even outside the 24h window); otherwise sends
    free-form, which delivers when the recipient has messaged within the last 24h."""
    if await template_approved():
        content_sid = os.environ.get("TWILIO_CONTENT_SID", "").strip()
        return await _send({
            "From": _from(), "To": _to_whatsapp(to),
            "ContentSid": content_sid, "ContentVariables": json.dumps({"1": text}),
        })
    return await _send({"From": _from(), "To": _to_whatsapp(to), "Body": text[:1600]})


def parse_inbound(form: dict) -> list[dict]:
    """Twilio inbound is form-encoded: From='whatsapp:+447...', Body, MessageSid.

    Media is delivered as NumMedia + MediaUrl{i}/MediaContentType{i}. A message with
    media but no text body is still valid (e.g. a photo with no caption)."""
    body = (form.get("Body") or "").strip()
    frm = form.get("From", "")
    if not frm.startswith("whatsapp:"):
        return []
    try:
        num = int(form.get("NumMedia") or 0)
    except (TypeError, ValueError):
        num = 0
    media = [
        {"url": form.get(f"MediaUrl{i}"), "content_type": form.get(f"MediaContentType{i}")}
        for i in range(num)
        if form.get(f"MediaUrl{i}")
    ]
    if not body and not media:
        return []
    return [
        {
            "from": frm.split(":", 1)[1],  # +447911...
            "id": form.get("MessageSid", ""),
            "text": body,
            "name": form.get("ProfileName"),
            "media": media,
        }
    ]


_MEDIA_DOWNLOAD_CEILING = 25 * 1024 * 1024  # WhatsApp media is <=16MB; hard cap well above it


async def download_media(url: str) -> tuple[bytes, str]:
    """Download a Twilio media URL (basic-auth, follows the redirect to the CDN).
    Streams with a hard ceiling so a misbehaving/huge response can't exhaust RAM
    on the 1GB box. Raises on HTTP error or if the body exceeds the ceiling."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async with client.stream("GET", url, auth=(_sid(), _auth_token())) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            buf = bytearray()
            async for chunk in resp.aiter_bytes(256 * 1024):
                buf += chunk
                if len(buf) > _MEDIA_DOWNLOAD_CEILING:
                    raise ValueError("Media too large to download")
            return bytes(buf), content_type


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
