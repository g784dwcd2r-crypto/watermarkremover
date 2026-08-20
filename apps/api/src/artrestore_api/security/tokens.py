"""Opaque token generation, hashing and constant-time comparison.

Session cookies and email links carry a random token; the database only ever
stores its SHA-256 digest.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def expiry(seconds: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Normalise a possibly-naive timestamp read back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def sign_payload(secret: str, payload: str) -> str:
    """HMAC-SHA256 signature used by the local storage backend's signed URLs."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
