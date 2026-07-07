"""Send each household member an evening wind-down digest of TOMORROW's day.

Run by a systemd timer at ~20:00 Europe/London (the ops agent owns the units):
    python -m server.jobs.evening_digest

Only runs when the household has the evening digest switched on (and the master
notification switch is on). Uses the same approved WhatsApp template as the morning
digest (business-initiated, so it works outside the 24h window), but built for
tomorrow and clearly prefixed so it reads as a look-ahead. Members without a phone
number are skipped.
"""

import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import briefing as briefing_svc  # noqa: E402
from server.services import whatsapp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evening_digest")


async def run() -> int:
    prefs = db.get_notification_prefs()
    if not (prefs.get("master_enabled") and prefs.get("evening_digest")):
        logger.info("Evening digest is off (master_enabled=%s, evening_digest=%s) — skipping.",
                    prefs.get("master_enabled"), prefs.get("evening_digest"))
        return 0
    if not whatsapp.is_configured():
        if whatsapp.provider() == "twilio":
            needed = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM"
        else:
            needed = "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID"
        logger.warning("WhatsApp (%s) not configured — set %s. Skipping.", whatsapp.provider(), needed)
        return 0

    tomorrow = date.today() + timedelta(days=1)
    sent = 0
    for u in db.list_users():
        full = db.get_user(u["id"])
        phone = (full or {}).get("phone")
        if not phone:
            logger.info("No phone for %s — skipping", u["name"])
            continue
        # No weather: today_line() only forecasts today, which would mislead a "tomorrow" digest.
        digest = briefing_svc.whatsapp_digest_line(full, for_date=tomorrow)
        line = f"🌙 Tomorrow — {digest}"
        try:
            res = await whatsapp.send_digest(phone, line)
            status = await whatsapp.confirm_delivery(res.get("sid") if isinstance(res, dict) else None)
            if status in ("failed", "undelivered"):
                logger.error("Evening digest to %s (%s) NOT delivered — status=%s. Likely outside the "
                             "24h window with no approved template.", u["name"], phone, status)
            else:
                sent += 1
                logger.info("Evening digest to %s (%s): %s", u["name"], phone, status)
        except Exception as exc:
            logger.error("Evening digest failed for %s: %s", u["name"], exc)
    logger.info("Evening digest complete — %d delivered", sent)
    return sent


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Evening digest crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
