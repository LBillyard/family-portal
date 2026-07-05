"""Household activity feed logging."""

from __future__ import annotations

import json
from typing import Any, Optional

from server import database as db


def log(
    user: dict | None,
    action: str,
    entity_type: str,
    summary: str,
    *,
    entity_id: str = "",
    meta: Optional[dict[str, Any]] = None,
) -> dict:
    return db.create_activity(
        {
            "user_id": user["id"] if user else "",
            "user_name": user["name"] if user else "System",
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "summary": summary,
            "meta_json": json.dumps(meta or {}),
        }
    )
