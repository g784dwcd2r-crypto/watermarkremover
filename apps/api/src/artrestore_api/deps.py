"""FastAPI dependencies: authentication, CSRF and rate limiting."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .errors import forbidden, rate_limited, unauthorized
from .models import User, UserSession
from .security.csrf import CSRFError, verify_csrf
from .security.ratelimit import get_rate_limiter
from .security.tokens import as_utc, hash_token, utcnow
from .storage import Storage, get_storage

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_storage_dep() -> Storage:
    return get_storage()


StorageDep = Annotated[Storage, Depends(get_storage_dep)]


def _load_session(db: Session, token: str) -> UserSession | None:
    record = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if record is None:
        return None
    if record.revoked_at is not None:
        return None
    expires = as_utc(record.expires_at)
    if expires is None or expires <= utcnow():
        return None
    return record


def get_optional_user(request: Request, db: DbSession) -> User | None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    record = _load_session(db, token)
    if record is None:
        return None
    user = db.get(User, record.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None

    # Refresh the activity stamp at most once a minute to avoid a write per request.
    now = utcnow()
    last_seen = as_utc(record.last_seen_at)
    if last_seen is None or (now - last_seen) > dt.timedelta(minutes=1):
        record.last_seen_at = now
        db.commit()
    request.state.user_id = user.id
    return user


CurrentUserOptional = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(user: CurrentUserOptional) -> User:
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_csrf(request: Request) -> None:
    """Enforce the double-submit CSRF token on unsafe methods."""
    settings = get_settings()
    try:
        verify_csrf(request, settings.csrf_cookie_name)
    except CSRFError as exc:
        raise forbidden(str(exc)) from exc


CSRFProtected = Depends(require_csrf)


def rate_limit(bucket: str, limit_getter: Callable[[Settings], int]) -> Callable:
    """Build a dependency that rate-limits a route.

    Authenticated callers are limited per user; anonymous callers per client
    address. The client address is used for limiting only and is never logged
    or stored.
    """

    def dependency(request: Request, response: Response) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        identity = getattr(request.state, "user_id", None)
        if not identity:
            token = request.cookies.get(settings.session_cookie_name)
            identity = (
                hash_token(token)[:16]
                if token
                else (request.client.host if request.client else "anonymous")
            )
        limiter = get_rate_limiter()
        result = limiter.check(f"{bucket}:{identity}", limit_getter(settings))
        for header, value in result.headers().items():
            response.headers[header] = value
        if not result.allowed:
            raise rate_limited(
                "Too many requests. Try again shortly.",
                reset_after=result.reset_after,
            )

    return dependency


AuthRateLimit = Depends(rate_limit("auth", lambda s: s.rate_limit_auth_per_minute))
UploadRateLimit = Depends(rate_limit("upload", lambda s: s.rate_limit_upload_per_minute))
JobRateLimit = Depends(rate_limit("job", lambda s: s.rate_limit_job_per_minute))
DefaultRateLimit = Depends(rate_limit("default", lambda s: s.rate_limit_default_per_minute))
