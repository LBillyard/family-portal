"""Password hashing.

Prefers argon2id (via argon2-cffi) and transparently upgrades legacy PBKDF2
hashes to argon2 on the next successful login. Falls back to PBKDF2 if argon2
is unavailable, so authentication never hard-fails on a missing dependency.
"""

import hashlib
import secrets

try:  # argon2-cffi is optional at runtime; PBKDF2 remains the fallback.
    from argon2 import PasswordHasher

    _ph = PasswordHasher()
except Exception:  # pragma: no cover - only when argon2-cffi isn't installed
    _ph = None


def hash_password(password: str) -> str:
    if _ph is not None:
        return _ph.hash(password)  # "$argon2id$v=19$..."
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2${salt}${digest.hex()}"


def _verify_pbkdf2(plain: str, stored: str) -> bool:
    try:
        _, salt, hexd = stored.split("$", 2)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(digest.hex(), hexd)


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if stored.startswith("$argon2"):
        if _ph is None:
            return False
        try:
            return _ph.verify(stored, plain)
        except Exception:
            return False
    if stored.startswith("pbkdf2$"):
        return _verify_pbkdf2(plain, stored)
    return False


def needs_rehash(stored: str) -> bool:
    """True if the stored hash should be re-hashed (legacy PBKDF2, or argon2
    params changed). Only meaningful when argon2 is available."""
    if _ph is None:
        return False
    if stored.startswith("$argon2"):
        try:
            return _ph.check_needs_rehash(stored)
        except Exception:
            return False
    return True  # legacy PBKDF2 → upgrade to argon2


def authenticate(email: str, password: str) -> dict | None:
    from server import database as db

    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    # Transparently upgrade the stored hash (e.g. PBKDF2 -> argon2) on login.
    try:
        if needs_rehash(user["password_hash"]):
            db.update_user_password(user["id"], hash_password(password))
    except Exception:
        pass
    return db.user_public(user)
