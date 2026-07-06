"""Send each household member their morning WhatsApp digest.

Run by a systemd timer at ~07:00 Europe/London:
    python -m server.jobs.morning_digest

Sends via an approved WhatsApp template (business-initiated, so it works outside
the 24h window). Members without a phone number are skipped.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import briefing as briefing_svc  # noqa: E402
from server.services import weather as weather_svc  # noqa: E402
from server.services import whatsapp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("morning_digest")


async def run() -> int:
    if not whatsapp.is_configured():
        if whatsapp.provider() == "twilio":
            needed = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM"
        else:
            needed = "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID"
        logger.warning("WhatsApp (%s) not configured — set %s. Skipping.", whatsapp.provider(), needed)
        return 0
    sent = 0
    weather_line = await weather_svc.today_line()  # same location for the whole household
    for u in db.list_users():
        full = db.get_user(u["id"])
        phone = (full or {}).get("phone")
        if not phone:
            logger.info("No phone for %s — skipping", u["name"])
            continue
        line = briefing_svc.whatsapp_digest_line(full, weather=weather_line)
        try:
            res = await whatsapp.send_digest(phone, line)
            # "accepted by Twilio" != "delivered by WhatsApp" — confirm the real status.
            status = await whatsapp.confirm_delivery(res.get("sid") if isinstance(res, dict) else None)
            if status in ("failed", "undelivered"):
                logger.error("Digest to %s (%s) NOT delivered — status=%s. Likely outside the "
                             "24h window with no approved template.", u["name"], phone, status)
            else:
                sent += 1
                logger.info("Digest to %s (%s): %s", u["name"], phone, status)
        except Exception as exc:
            logger.error("Digest failed for %s: %s", u["name"], exc)
    logger.info("Morning digest complete — %d delivered", sent)
    return sent


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Morning digest crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
