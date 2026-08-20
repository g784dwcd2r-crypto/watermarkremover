"""Password hashing.

Argon2id with the reference parameters from ``argon2-cffi``. Verification
transparently re-hashes when the parameters change so an upgrade does not
require a password reset.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


class WeakPasswordError(ValueError):
    """The supplied password does not meet the minimum policy."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. A passphrase of a few words is ideal."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError("That password is too long.")
    if password.strip() == "":
        raise WeakPasswordError("A password cannot be only whitespace.")
    lowered = password.lower()
    if lowered in {"password1234", "artrestorestudio", "123456789012", "qwertyuiopas"}:
        raise WeakPasswordError("That password is too common.")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True
