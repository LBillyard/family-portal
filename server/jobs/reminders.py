"""Send due household reminders (appointments, bills, renewals, document expiries).

Run by a systemd timer (the ops agent owns the .service/.timer units):
    python -m server.jobs.reminders

Reminders go out as free-form WhatsApp messages, so they deliver when the
recipient's 24h WhatsApp window is open. Every item is de-duplicated, so running
this repeatedly (e.g. a few times a day) is safe — each event pings only once.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import reminders as reminders_svc  # noqa: E402
from server.services import whatsapp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reminders")


async def run() -> dict:
    if not whatsapp.is_configured():
        if whatsapp.provider() == "twilio":
            needed = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM"
        else:
            needed = "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID"
        logger.warning("WhatsApp (%s) not configured — set %s. Skipping.", whatsapp.provider(), needed)
        return {"sent": 0, "skipped": "whatsapp_not_configured"}
    result = await reminders_svc.run_reminders()
    if result.get("skipped"):
        logger.info("Reminders skipped — %s", result["skipped"])
    else:
        logger.info("Reminders complete — %d sent, %d checked", result.get("sent", 0), result.get("checked", 0))
    return result


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Reminders job crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
