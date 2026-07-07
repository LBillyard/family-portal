#!/usr/bin/env python3
"""Generate a VAPID keypair for Web Push and print the .env lines to paste.

Web Push (browser notifications that work even outside the WhatsApp 24h window)
needs one long-lived EC P-256 keypair, shared by the server and every browser
subscription. Generate it ONCE, store it in .env, and never rotate it casually —
changing the keys invalidates every existing push subscription.

  On the server (inside the app venv so `cryptography` is importable):

    cd /opt/family-portal
    ./venv/bin/python deploy/gen-vapid.py

  Copy the three printed lines into /opt/family-portal/.env, then restart:

    sudo systemctl restart family-portal

Output format (the format pywebpush / the browser expect):
  * VAPID_PUBLIC_KEY  — URL-safe base64 (unpadded) of the uncompressed EC point
                        (65 bytes, 0x04 || X || Y). This is the browser's
                        `applicationServerKey`.
  * VAPID_PRIVATE_KEY — URL-safe base64 (unpadded) of the raw 32-byte private
                        scalar. pywebpush reads this directly.
  * VAPID_SUBJECT     — mailto: contact, required by the push spec.

This uses `cryptography` only, which is a hard dependency of pywebpush and is
already in requirements.txt — so it runs as soon as the venv is set up.
"""

import base64
import sys

SUBJECT = "mailto:lbillyard@gmail.com"


def _b64url(raw: bytes) -> str:
    """URL-safe base64 without padding (what Web Push / VAPID use)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> int:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        sys.stderr.write(
            "ERROR: the 'cryptography' package is not installed.\n"
            "Run this with the app's virtualenv, which has the deps from\n"
            "requirements.txt, e.g. on the server:\n\n"
            "    cd /opt/family-portal && ./venv/bin/python deploy/gen-vapid.py\n\n"
            "Or install it first:  pip install cryptography\n"
        )
        return 1

    private_key = ec.generate_private_key(ec.SECP256R1())

    # Public key as the uncompressed point (65 bytes: 0x04 || X(32) || Y(32)).
    public_point = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    # Private key as the raw 32-byte big-endian scalar.
    private_scalar = private_key.private_numbers().private_value.to_bytes(32, "big")

    print(f"VAPID_PUBLIC_KEY={_b64url(public_point)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(private_scalar)}")
    print(f"VAPID_SUBJECT={SUBJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
