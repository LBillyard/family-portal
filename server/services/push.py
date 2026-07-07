"""Web Push notifications (VAPID).

A best-effort *bonus* delivery channel: unlike WhatsApp free-form messages (which
only deliver inside the recipient's 24h window), a web-push notification reaches a
subscribed browser/PWA any time. VAPID keys come from the environment. pywebpush is
imported lazily inside send_push so this module imports fine even before the
dependency is installed (a parallel agent is adding it to requirements).
"""

from __future__ import annotations

import json
import logging
import os

from server import database as db

logger = logging.getLogger(__name__)


def _subject() -> str:
    return os.environ.get("VAPID_SUBJECT", "").strip()


def _private_key() -> str:
    return os.environ.get("VAPID_PRIVATE_KEY", "").strip()


def get_public_key() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def is_configured() -> bool:
    return bool(get_public_key() and _private_key() and _subject())


def send_push(sub: dict, title: str, body: str, url: str = "/") -> bool:
    """Send one push notification. Best-effort: returns True on success, False on
    any failure. Prunes the stored subscription when the endpoint is gone (404/410).
    """
    if not is_configured():
        return False
    endpoint = sub.get("endpoint", "")
    try:
        from pywebpush import WebPushException, webpush
    except Exception:  # dependency not installed yet — push is optional
        logger.warning("pywebpush not installed — web push unavailable")
        return False
    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": sub.get("p256dh", ""), "auth": sub.get("auth", "")},
            },
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=_private_key(),
            vapid_claims={"sub": _subject()},
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):  # subscription expired / unsubscribed — drop it
            db.delete_push_subscription(endpoint)
            logger.info("Pruned gone push subscription %s", (endpoint or "")[:40])
        else:
            logger.warning("Web push failed (%s): %s", status, exc)
        return False
    except Exception:
        logger.exception("Web push send crashed")
        return False


def notify(title: str, body: str, url: str = "/") -> int:
    """Send to every stored subscription. Returns the number sent. No-op (0) when
    push isn't configured."""
    if not is_configured():
        return 0
    sent = 0
    for sub in db.list_push_subscriptions():
        if send_push(sub, title, body, url):
            sent += 1
    return sent
