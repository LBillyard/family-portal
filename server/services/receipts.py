"""Receipt scanning — OpenRouter vision to extract expense details."""

from __future__ import annotations

import base64
import json
import logging
import os
import re

import httpx

from server import database as db
from server.services import openrouter

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def parse_receipt(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    if not openrouter.is_configured():
        raise RuntimeError("OpenRouter not configured — required for receipt scanning")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    model = os.environ.get("OPENROUTER_VISION_MODEL", "openai/gpt-4o-mini")
    system = (
        "Extract UK receipt data. Respond with ONLY valid JSON: "
        '{"description":str,"amount":number,"date":"YYYY-MM-DD","category":str,"merchant":str}. '
        "Amount should be positive total paid. Category one of: Groceries, Eating out, Transport, "
        "Shopping, Entertainment, Utilities, Subscriptions, Other."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract expense from this receipt."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            },
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("PUBLIC_URL", "http://localhost:8090"),
        "X-Title": "Family Portal Receipts",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(resp.text[:300])
        content = resp.json()["choices"][0]["message"]["content"]

    parsed = _parse_json(content)
    amount = float(parsed.get("amount") or 0)
    if amount > 0:
        amount = -abs(amount)
    return {
        "description": parsed.get("description") or parsed.get("merchant") or "Receipt expense",
        "amount": round(amount, 2),
        "date": parsed.get("date") or "",
        "category": parsed.get("category") or "Other",
        "merchant": parsed.get("merchant", ""),
        "raw": parsed,
    }


async def scan_and_log_transaction(image_bytes: bytes, mime_type: str, user: dict, account_id: str = "joint") -> dict:
    extracted = await parse_receipt(image_bytes, mime_type)
    txn = db.create_transaction(
        {
            "description": extracted["description"],
            "amount": extracted["amount"],
            "category": extracted["category"],
            "date": extracted["date"] or None,
            "account_id": account_id,
        }
    )
    receipt = db.create_receipt(
        {
            "transaction_id": txn["id"],
            "user_id": user["id"],
            "merchant": extracted.get("merchant", ""),
            "extracted_json": json.dumps(extracted),
        }
    )
    return {"transaction": txn, "receipt": receipt, "extracted": extracted}


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
