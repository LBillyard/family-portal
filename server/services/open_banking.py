"""TrueLayer Open Banking — connect Starling, Revolut, Amex, Virgin Money."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

CLIENT_ID = os.environ.get("TRUELAYER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TRUELAYER_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get(
    "TRUELAYER_REDIRECT_URI",
    "http://localhost:8090/api/banking/callback",
)
ENV = os.environ.get("TRUELAYER_ENV", "sandbox").lower()
IS_SANDBOX = ENV in ("sandbox", "test", "dev")

if IS_SANDBOX:
    AUTH_URL = "https://auth.truelayer-sandbox.com/"
    TOKEN_URL = "https://auth.truelayer-sandbox.com/connect/token"
    API_BASE = "https://api.truelayer-sandbox.com/data/v1"
else:
    AUTH_URL = "https://auth.truelayer.com/"
    TOKEN_URL = "https://auth.truelayer.com/connect/token"
    API_BASE = "https://api.truelayer.com/data/v1"

SCOPES = "info accounts balance transactions cards offline_access"

# Household providers — verify IDs in TrueLayer Console → Supported Providers
HOUSEHOLD_PROVIDERS = [
    {
        "id": "ob-starling",
        "name": "Starling Bank",
        "institution": "Starling Bank",
        "type": "current",
        "kind": "account",
    },
    {
        "id": "ob-revolut",
        "name": "Revolut",
        "institution": "Revolut",
        "type": "current",
        "kind": "account",
    },
    {
        "id": "ob-amex",
        "name": "American Express",
        "institution": "American Express",
        "type": "credit",
        "kind": "card",
    },
    {
        "id": "ob-virgin-money",
        "name": "Virgin Money",
        "institution": "Virgin Money",
        "type": "credit",
        "kind": "card",
        "note": "Select your Virgin credit card during consent. 7-digit customer ID required.",
    },
]

SANDBOX_PROVIDER = {
    "id": "uk-cs-mock",
    "name": "Mock Bank (sandbox test)",
    "institution": "TrueLayer Sandbox",
    "type": "current",
    "kind": "account",
}


def is_configured() -> bool:
    return bool(
        CLIENT_ID
        and CLIENT_SECRET
        and CLIENT_SECRET not in ("", "REPLACE_WITH_LIVE_SECRET_FROM_CONSOLE")
    )


def list_providers() -> list[dict]:
    providers = list(HOUSEHOLD_PROVIDERS)
    if IS_SANDBOX:
        providers = [SANDBOX_PROVIDER] + providers
    return providers


def provider_by_id(provider_id: str) -> Optional[dict]:
    for p in list_providers():
        if p["id"] == provider_id:
            return p
    return None


def authorization_url(*, state: str, provider_id: str, user_email: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "provider_id": provider_id,
        "providers": provider_id,
        "country_id": "GB",
        "user_email": user_email,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
        )
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error_description") or body.get("error") or resp.text
            except Exception:
                msg = resp.text or f"HTTP {resp.status_code}"
            logger.error("TrueLayer token exchange failed: %s", msg)
            raise RuntimeError(str(msg)[:200])
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        return resp.json()


def token_expires_at(expires_in: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 0))).isoformat()


async def _api_get(access_token: str, path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
        )
        if resp.status_code == 401:
            raise RuntimeError("Bank connection expired — reconnect in Settings")
        resp.raise_for_status()
        return resp.json()


async def fetch_accounts(access_token: str) -> list[dict]:
    # Card-only providers (e.g. Amex) return 404/501 for /accounts — treat as
    # "no accounts" so the sync continues to /cards instead of aborting.
    try:
        data = await _api_get(access_token, "/accounts")
        return data.get("results", [])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404, 501):
            return []
        raise


async def fetch_cards(access_token: str) -> list[dict]:
    try:
        data = await _api_get(access_token, "/cards")
        return data.get("results", [])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404, 501):
            return []
        raise


async def fetch_account_balance(access_token: str, account_id: str) -> Optional[float]:
    try:
        data = await _api_get(access_token, f"/accounts/{account_id}/balance")
        results = data.get("results", [])
        if not results:
            return None
        row = results[0]
        return float(row.get("current") or row.get("available") or 0)
    except httpx.HTTPStatusError:
        return None


async def fetch_card_balance(access_token: str, card_id: str) -> Optional[float]:
    try:
        data = await _api_get(access_token, f"/cards/{card_id}/balance")
        results = data.get("results", [])
        if not results:
            return None
        row = results[0]
        # TrueLayer already signs a credit card's balance as negative when money
        # is owed (e.g. -83.38), so store it as-is — the portal then shows the
        # amount owed as a negative balance.
        current = row.get("current")
        if current is None:
            current = row.get("available") or 0
        return float(current)
    except httpx.HTTPStatusError:
        return None


async def fetch_account_transactions(
    access_token: str, account_id: str, from_date: str, to_date: str
) -> list[dict]:
    data = await _api_get(
        access_token,
        f"/accounts/{account_id}/transactions",
        {"from": from_date, "to": to_date},
    )
    return data.get("results", [])


async def fetch_card_transactions(
    access_token: str, card_id: str, from_date: str, to_date: str
) -> list[dict]:
    data = await _api_get(
        access_token,
        f"/cards/{card_id}/transactions",
        {"from": from_date, "to": to_date},
    )
    return data.get("results", [])


def _parse_txn(txn: dict, local_account_id: str) -> Optional[dict]:
    ts = txn.get("timestamp") or txn.get("booking_date")
    if not ts:
        return None
    try:
        txn_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None

    amount = float(txn.get("amount", 0))
    desc = (
        txn.get("description")
        or txn.get("merchant_name")
        or (txn.get("meta") or {}).get("provider_merchant_name")
        or "Bank transaction"
    )
    category = (
        txn.get("transaction_category")
        or txn.get("transaction_classification")
        or txn.get("transaction_type")
        or "Bank"
    )
    ext_id = txn.get("transaction_id") or txn.get("normalised_provider_transaction_id")
    if not ext_id:
        ext_id = f"{local_account_id}:{txn_date}:{desc}:{amount}"

    return {
        "external_id": str(ext_id),
        "date": txn_date,
        "description": str(desc)[:200],
        "amount": amount,
        "category": str(category)[:80],
        "account_id": local_account_id,
    }


async def sync_connection(connection: dict, db) -> dict:
    """Sync one bank connection into local accounts + transactions."""
    access_token = connection.get("access_token")
    refresh_token = connection.get("refresh_token")
    expires_at = connection.get("token_expires_at")

    if refresh_token and expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp <= datetime.now(timezone.utc):
                tokens = await refresh_access_token(refresh_token)
                access_token = tokens["access_token"]
                db.update_bank_tokens(
                    connection["id"],
                    access_token,
                    tokens.get("refresh_token", refresh_token),
                    token_expires_at(int(tokens.get("expires_in", 3600))),
                )
        except Exception as exc:
            logger.warning("Token refresh failed for %s: %s", connection["id"], exc)
            raise RuntimeError("Bank session expired — please reconnect") from exc

    if not access_token:
        raise RuntimeError("No access token — reconnect this bank")

    provider = provider_by_id(connection["provider_id"]) or {}
    from_date = (datetime.now(timezone.utc) - timedelta(days=88)).date().isoformat()
    to_date = datetime.now(timezone.utc).date().isoformat()

    synced_accounts = 0
    synced_txns = 0

    accounts = await fetch_accounts(access_token)
    for acct in accounts:
        ext_id = acct.get("account_id")
        if not ext_id:
            continue
        display = acct.get("display_name") or acct.get("account_type") or provider.get("name", "Account")
        local_id = db.upsert_linked_account(
            connection_id=connection["id"],
            external_id=ext_id,
            name=display,
            account_type=provider.get("type", "current"),
            institution=provider.get("institution", connection["provider_name"]),
        )
        balance = await fetch_account_balance(access_token, ext_id)
        if balance is not None:
            db.set_account_balance(local_id, balance)
        txns = await fetch_account_transactions(access_token, ext_id, from_date, to_date)
        rows = [_parse_txn(t, local_id) for t in txns]
        synced_txns += db.import_external_transactions([r for r in rows if r])
        synced_accounts += 1

    cards = await fetch_cards(access_token)
    for card in cards:
        ext_id = card.get("account_id")
        if not ext_id:
            continue
        display = card.get("display_name") or card.get("card_type") or provider.get("name", "Card")
        partial = card.get("partial_card_number", "")
        if partial:
            display = f"{display} ···{partial}"
        local_id = db.upsert_linked_account(
            connection_id=connection["id"],
            external_id=ext_id,
            name=display,
            account_type="credit",
            institution=provider.get("institution", connection["provider_name"]),
        )
        balance = await fetch_card_balance(access_token, ext_id)
        if balance is not None:
            db.set_account_balance(local_id, balance)
        txns = await fetch_card_transactions(access_token, ext_id, from_date, to_date)
        rows = [_parse_txn(t, local_id) for t in txns]
        synced_txns += db.import_external_transactions([r for r in rows if r])
        synced_accounts += 1

    db.mark_connection_synced(connection["id"])
    db.set_setting("banking_last_sync", datetime.now(timezone.utc).isoformat())
    return {"accounts": synced_accounts, "transactions": synced_txns}
