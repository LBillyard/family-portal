"""Daily proactive inbox scan — surface new email suggestions and nudge once.

Run by a systemd timer at ~07:30 Europe/London (the ops agent owns the units):
    python -m server.jobs.inbox_scan

For every household member with a connected Google account this re-scans their
inbox and persists any NEW findings as suggestions (idempotent — dismissed/accepted
items never come back). If the scan turned up anything new AND the household has the
proactive-inbox nudge switched on (and the master notification switch is on), it
sends ONE household nudge — a WhatsApp line to each member's phone plus a web push —
deduplicated to at most once per day. Best-effort: it never crashes the timer.
"""

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from server import database as db  # noqa: E402
from server.services import inbox_actions  # noqa: E402
from server.services import push  # noqa: E402
from server.services import whatsapp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inbox_scan")


def _say(msg: str) -> None:
    """PYTHONIOENCODING-safe log line (drops any non-ASCII so a stray emoji in a
    subject can never blow up the timer's stdout on a locale-limited console)."""
    logger.info(msg.encode("ascii", "replace").decode("ascii"))


async def run() -> int:
    total_new = 0
    for u in db.list_users():
        uid = u["id"]
        if not db.list_google_accounts(uid):
            continue  # nothing to scan for this member
        try:
            res = await inbox_actions.scan_and_store(uid)
            total_new += int(res.get("new") or 0)
        except Exception:
            logger.exception("Inbox scan failed for %s", uid)
    _say(f"Inbox scan complete — {total_new} new suggestion(s)")
    if total_new <= 0:
        return 0

    prefs = db.get_notification_prefs()
    if not (prefs.get("master_enabled") and prefs.get("proactive_inbox")):
        _say("Proactive inbox nudge is off (master/proactive_inbox) — skipping nudge.")
        return total_new

    # One nudge per day, whatever the scan cadence.
    key = f"inboxsug:{date.today().isoformat()}"
    if db.was_notified(key):
        _say("Inbox nudge already sent today — skipping.")
        return total_new

    body = f"🔔 The Hub spotted {total_new} new thing(s) in your email — open the app to review."

    if whatsapp.is_configured():
        for u in db.list_users():
            full = db.get_user(u["id"])
            phone = (full or {}).get("phone")
            if not phone:
                continue
            try:
                await whatsapp.send_text(phone, body)
            except Exception as exc:
                logger.error("Inbox nudge WhatsApp failed for %s: %s", u.get("name"), exc)

    try:
        push.notify("The Hub", body, url="/", badge_count=db.count_pending_suggestions())
    except Exception:
        logger.exception("Inbox nudge push failed")

    db.mark_notified(key)
    _say("Inbox nudge sent.")
    return total_new


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Inbox scan crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
