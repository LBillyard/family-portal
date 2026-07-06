"""Email reminders via SMTP (optional)."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

from server import database as db

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(
        os.environ.get("SMTP_HOST", "").strip()
        and os.environ.get("NOTIFY_EMAIL", "").strip()
    )


def _smtp_settings() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "from_addr": os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "")).strip(),
        "to_addr": os.environ.get("NOTIFY_EMAIL", "").strip(),
        "use_tls": os.environ.get("SMTP_TLS", "true").lower() != "false",
    }


def send_email(subject: str, body: str, to_addr: str | None = None) -> dict:
    cfg = _smtp_settings()
    if not cfg["host"] or not (to_addr or cfg["to_addr"]):
        entry = db.create_notification_log(
            {"channel": "email", "subject": subject, "body": body, "status": "queued", "detail": "SMTP not configured"}
        )
        return {"sent": False, "queued": True, "log_id": entry["id"]}

    recipient = to_addr or cfg["to_addr"]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = recipient

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], [recipient], msg.as_string())
        entry = db.create_notification_log(
            {"channel": "email", "subject": subject, "body": body, "status": "sent", "detail": recipient}
        )
        return {"sent": True, "log_id": entry["id"], "to": recipient}
    except Exception as exc:
        logger.exception("Email send failed")
        entry = db.create_notification_log(
            {"channel": "email", "subject": subject, "body": body, "status": "failed", "detail": str(exc)[:200]}
        )
        return {"sent": False, "error": str(exc), "log_id": entry["id"]}


def send_renewal_reminders() -> dict:
    from server.services import renewals as renewals_svc

    cal = renewals_svc.build_renewal_calendar(days_ahead=7)
    urgent = [i for i in cal["items"] if i["days_until"] <= 3]
    if not urgent:
        return {"sent": False, "count": 0, "reason": "nothing due"}

    lines = ["The Hub — upcoming renewals:", ""]
    for item in urgent:
        d = item["days_until"]
        if d < 0:
            when = f"{-d} day(s) overdue"
        elif d == 0:
            when = "today"
        else:
            when = f"in {d} day(s)"
        lines.append(f"• {item['title']} ({item['type']}) — {when} ({item['date']})")
    body = "\n".join(lines)
    result = send_email("The Hub renewals reminder", body)
    result["count"] = len(urgent)
    return result
