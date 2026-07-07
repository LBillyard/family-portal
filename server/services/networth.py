"""Household net worth — cash accounts + tracked assets − liabilities.

Pulls live account balances from the ledger and merges in manually tracked assets
(house, car, investments, etc.). An account counts as a liability if it's a credit
account OR its balance is negative (e.g. an overdrawn current account); everything
else is treated as spendable cash. Liabilities are surfaced as positive amounts and
subtracted from the total.
"""

from __future__ import annotations

from server import database as db

_LIABILITY_TYPES = {"credit"}


def _is_liability(account: dict) -> bool:
    atype = (account.get("type") or "").lower()
    balance = float(account.get("balance") or 0)
    return atype in _LIABILITY_TYPES or balance < 0


def build_networth() -> dict:
    cash_total = 0.0
    liabilities_total = 0.0
    breakdown: list[dict] = []

    for account in db.list_accounts():
        balance = float(account.get("balance") or 0)
        label = account.get("name") or "Account"
        if _is_liability(account):
            amount = abs(balance)
            liabilities_total += amount
            breakdown.append({"label": label, "amount": round(amount, 2), "kind": "liability"})
        else:
            cash_total += balance
            breakdown.append({"label": label, "amount": round(balance, 2), "kind": "cash"})

    assets_total = 0.0
    for asset in db.list_assets():
        value = float(asset.get("value") or 0)
        assets_total += value
        breakdown.append(
            {"label": asset.get("name") or "Asset", "amount": round(value, 2), "kind": "asset"}
        )

    net_worth = cash_total + assets_total - liabilities_total

    # Record today's snapshot so net-worth history accrues every time anyone opens
    # Finances (and whenever the Sunday recap job calls build_networth). One row per
    # date, id-stable. Best-effort: never let snapshotting break the response.
    try:
        from datetime import date

        db.upsert_networth_snapshot(
            date.today().isoformat(),
            round(net_worth, 2),
            round(cash_total, 2),
            round(assets_total, 2),
            round(liabilities_total, 2),
        )
    except Exception:
        pass

    return {
        "net_worth": round(net_worth, 2),
        "cash_total": round(cash_total, 2),
        "assets_total": round(assets_total, 2),
        "liabilities_total": round(liabilities_total, 2),
        "breakdown": breakdown,
    }


def build_networth_trend(limit: int = 30) -> dict:
    """Net-worth history for the trend chart: oldest→newest points plus the latest value.

    Reads persisted daily snapshots (db.list_networth_snapshots returns ASC by date).
    Empty points when there's no history yet.
    """
    snapshots = db.list_networth_snapshots(limit)
    points = [
        {"date": s.get("date"), "net_worth": s.get("net_worth")}
        for s in snapshots
    ]
    current = points[-1]["net_worth"] if points else 0
    return {"points": points, "current": current}
