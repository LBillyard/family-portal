"""Password hashing — stdlib only (no bcrypt compat issues)."""

import hashlib
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        _, salt, hexd = stored.split("$", 2)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 100_000)
    return secrets.compare_digest(digest.hex(), hexd)


def authenticate(email: str, password: str) -> dict | None:
    from server import database as db

    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return db.user_public(user)
