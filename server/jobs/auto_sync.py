"""Hourly auto-sync — refresh Google Calendars and bank connections.

Run by a systemd timer (see deploy/family-portal-sync.timer):
    python -m server.jobs.auto_sync

Mirrors what the manual "Sync all" buttons do (POST /calendar/sync + /banking/sync),
so the portal data and the header "Synced …" pill stay fresh without user action.
Each source is best-effort: a failure in one (e.g. an expired bank consent needing
re-auth) is logged and does not stop the others.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import google_calendar, open_banking  # noqa: E402
from server.services import subscriptions as sub_svc  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_sync")


async def run() -> None:
    if google_calendar.is_configured():
        try:
            results = google_calendar.sync_all()
            logger.info("Google sync: %s", results)
        except Exception:
            logger.exception("Google sync failed")
    else:
        logger.info("Google Calendar not configured — skipping")

    if open_banking.is_configured():
        for conn in db.list_bank_connections():
            internal = db.get_bank_connection_internal(conn["id"])
            if not internal:
                continue
            try:
                synced = await open_banking.sync_connection(internal, db)
                logger.info("Bank %s: %s", conn["provider_name"], synced)
            except Exception as exc:
                logger.warning("Bank %s sync failed (may need re-auth): %s", conn["provider_name"], exc)
        try:
            sub_svc.refresh_subscriptions()
        except Exception:
            logger.exception("refresh_subscriptions failed")
    else:
        logger.info("Open Banking not configured — skipping")


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("auto_sync crashed")
        sys.exit(1)
    logger.info("Auto-sync complete")


if __name__ == "__main__":
    main()
