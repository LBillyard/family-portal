"""Send a WhatsApp reminder for any task whose remind time has arrived.

Run by a systemd timer every 15 minutes:
    python -m server.jobs.task_reminders

Best-effort and idempotent: each task is only reminded once per remind_at
value (server.database.mark_task_reminded), and a task without an assignee
phone number is marked reminded anyway so it isn't retried every run.
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
logger = logging.getLogger("task_reminders")


async def run() -> int:
    due = db.list_tasks_due_for_reminder()
    if not due:
        return 0
    if not whatsapp.is_configured():
        logger.warning("WhatsApp not configured — %d reminder(s) skipped.", len(due))
        return 0
    sent = 0
    for task in due:
        assignee_id = task.get("assignee")
        user = db.get_user(assignee_id) if assignee_id else None
        phone = (user or {}).get("phone")
        if not phone:
            logger.info("Task %s has no assignee phone — skipping (won't retry)", task["id"])
            db.mark_task_reminded(task["id"])
            continue
        parts = [f"⏰ Reminder: {task['title']}"]
        if task.get("due"):
            parts.append(f"due {task['due']}")
        try:
            await whatsapp.send_text(phone, " · ".join(parts))
            sent += 1
            logger.info("Reminded %s about task %s", user.get("name"), task["id"])
        except Exception as exc:
            logger.error("Reminder failed for task %s: %s", task["id"], exc)
        db.mark_task_reminded(task["id"])
    logger.info("Task reminders complete — %d/%d sent", sent, len(due))
    return sent


def main() -> None:
    db.init_db()
    try:
        asyncio.run(run())
    except Exception:
        logger.exception("Task reminders crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
