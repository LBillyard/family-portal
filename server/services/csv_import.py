"""CSV transaction import — Monzo/Starling/generic formats."""

import csv
import io
import re
from datetime import datetime


def parse_csv(content: str, default_account: str = "joint") -> list[dict]:
    """Parse bank CSV export into transaction dicts."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    fields = {_normalize(h) for h in reader.fieldnames}
    rows = []

    for raw in reader:
        row = {_normalize(k): (v or "").strip() for k, v in raw.items() if k}
        txn = _parse_row(row, default_account)
        if txn:
            rows.append(txn)

    if not rows:
        raise ValueError("No valid transactions found — check CSV format")
    return rows


def _normalize(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


def _parse_row(row: dict, default_account: str) -> dict | None:
    date_val = (
        row.get("date")
        or row.get("transaction date")
        or row.get("started date")
        or row.get("time")
    )
    desc = (
        row.get("description")
        or row.get("name")
        or row.get("merchant")
        or row.get("reference")
        or "Imported transaction"
    )
    amount_raw = row.get("amount") or row.get("value") or row.get("(gbp) amount") or row.get("amount (gbp)")

    if not date_val or not amount_raw:
        return None

    amount = _parse_amount(amount_raw)
    if amount is None:
        return None

    category = row.get("category") or row.get("type") or "Imported"
    parsed_date = _parse_date(date_val)
    if not parsed_date:
        return None

    return {
        "date": parsed_date,
        "description": desc[:200],
        "amount": amount,
        "category": category[:80],
        "account_id": default_account,
    }


def _parse_amount(raw: str) -> float | None:
    cleaned = raw.replace("£", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw: str) -> str | None:
    raw = raw.strip()[:19]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).date().isoformat()
    except ValueError:
        return None
