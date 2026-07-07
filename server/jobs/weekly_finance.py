"""Send each household member a weekly finance recap over WhatsApp.

Run by a systemd timer at 18:00 Europe/London on Sundays (the ops agent owns the
units):
    python -m server.jobs.weekly_finance

Only runs when the household has the weekly finance summary switched on (and the
master notification switch is on). Uses the same approved WhatsApp template as the
digests (business-initiated, so it works outside the 24h window). The recap body is
built once by server.services.weekly_finance and sent to every member with a phone
number; members without a phone are skipped.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import whatsapp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weekly_finance")


async def run() -> int:
    prefs = db.get_notification_prefs()
    if not (prefs.get("master_enabled") and prefs.get("weekly_finance_summary")):
        logger.info("Weekly finance summary is off (master_enabled=%s, weekly_finance_summary=%s) — skipping.",
                    prefs.get("master_enabled"), prefs.get("weekly_finance_summary"))
        return 0
    if not whatsapp.is_configured():
        if whatsapp.provider() == "twilio":
            needed = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM"
        else:
            needed = "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID"
        logger.warning("WhatsApp (%s) not configured — set %s. Skipping.", whatsapp.provider(), needed)
        return 0

    # Import inside run() so a failure building the recap service is logged here
    # rather than crashing module import (the service is owned by another agent).
    from server.services import weekly_finance as weekly_finance_svc  # noqa: E402
    body = weekly_finance_svc.build_weekly_summary()

    sent = 0
    for u in db.list_users():
        full = db.get_user(u["id"])
        phone = (full or {}).get("phone")
        if not phone:
            logger.info("No phone for %s — skipping", u["name"])
            continue
        try:
            res = await whatsapp.send_digest(phone, body)
            status = await whatsapp.confirm_delivery(res.get("sid") if isinstance(res, dict) else None)
            if status in ("failed", "undelivered"):
                logger.error("Weekly finance recap to %s (%s) NOT delivered — status=%s. Likely outside the "
                             "24h window with no approved template.", u["name"], phone, status)
            else:
                sent += 1
                logger.info("Weekly finance recap to %s (%s): %s", u["name"], phone, status)
        except Exception as exc:
            logger.error("Weekly finance recap failed for %s: %s", u["name"], exc)
    logger.info("Weekly finance recap complete — %d delivered", sent)
    return sent


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Weekly finance recap crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
