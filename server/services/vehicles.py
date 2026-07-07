"""Optional DVLA registration lookup for vehicles.

The DVLA Vehicle Enquiry Service (VES) turns a number plate into the vehicle's
make, year, and tax/MOT expiry dates — handy for auto-filling a new vehicle. It
needs a free API key (register at DVLA) supplied via the DVLA_API_KEY env var.

This whole feature is DORMANT without that key: `is_lookup_configured()` returns
False and the route simply tells the user how to enable it. Nothing here is a hard
dependency of the app — vehicles work fine with everything typed in by hand.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_VES_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"


def _api_key() -> str:
    return os.environ.get("DVLA_API_KEY", "").strip()


def is_lookup_configured() -> bool:
    """True only when a DVLA API key is present — the feature is off otherwise."""
    return bool(_api_key())


async def lookup_reg(reg: str) -> dict:
    """Look up a UK registration via the DVLA VES API.

    Returns {"make", "mot_due", "tax_due", "year"} on success. Raises:
      - RuntimeError if lookup isn't configured or a network/API error occurs.
      - ValueError if the DVLA has no record of the plate (404).
    """
    key = _api_key()
    if not key:
        raise RuntimeError("DVLA lookup not configured")

    plate = (reg or "").upper().replace(" ", "").strip()
    if not plate:
        raise ValueError("Vehicle not found")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _VES_URL,
                headers={"x-api-key": key, "Content-Type": "application/json"},
                json={"registrationNumber": plate},
            )
    except httpx.HTTPError as exc:
        logger.warning("DVLA lookup network error for %s: %s", plate, exc)
        raise RuntimeError("Couldn't reach the DVLA lookup service — try again later") from exc

    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning("DVLA lookup returned invalid JSON for %s", plate)
            raise RuntimeError("DVLA returned an unexpected response") from exc
        return {
            "make": data.get("make"),
            "mot_due": data.get("motExpiryDate"),
            "tax_due": data.get("taxDueDate"),
            "year": data.get("yearOfManufacture"),
        }
    if resp.status_code == 404:
        raise ValueError("Vehicle not found")
    if resp.status_code in (401, 403):
        logger.warning("DVLA lookup auth error (%s) for %s", resp.status_code, plate)
        raise RuntimeError("DVLA rejected the API key — check DVLA_API_KEY")

    logger.warning("DVLA lookup failed (%s) for %s", resp.status_code, plate)
    raise RuntimeError(f"DVLA lookup failed (HTTP {resp.status_code})")
