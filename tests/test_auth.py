"""Password hashing: argon2 preferred, legacy PBKDF2 still verifies + upgrades."""

import hashlib
import secrets

from server import auth


def _legacy_pbkdf2(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2${salt}${digest.hex()}"


def test_hash_and_verify_roundtrip():
    h = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)


def test_legacy_pbkdf2_still_verifies():
    legacy = _legacy_pbkdf2("hunter2")
    assert auth.verify_password("hunter2", legacy)
    assert not auth.verify_password("nope", legacy)


def test_needs_rehash_flags_legacy_when_argon2_available():
    legacy = _legacy_pbkdf2("hunter2")
    if auth._ph is not None:  # argon2 installed
        assert auth.needs_rehash(legacy) is True
        assert auth.needs_rehash(auth.hash_password("x")) is False


def test_verify_rejects_garbage():
    assert not auth.verify_password("x", "")
    assert not auth.verify_password("x", "not-a-hash")


def test_authenticate_upgrades_legacy_hash():
    from server import database as db

    user = db.get_user_by_email("lbillyard@gmail.com")
    db.update_user_password(user["id"], _legacy_pbkdf2("family123"))
    assert auth.authenticate("lbillyard@gmail.com", "family123") is not None
    after = db.get_user_by_email("lbillyard@gmail.com")["password_hash"]
    if auth._ph is not None:
        assert after.startswith("$argon2"), "legacy hash should upgrade to argon2 on login"
