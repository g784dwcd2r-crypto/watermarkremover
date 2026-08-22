"""Authentication: registration, sign-in, reset and passwordless links.

Sessions live in an HTTP-only cookie holding an opaque token; only the token's
hash is stored. A companion readable CSRF cookie carries the double-submit
token. Sign-in and sign-out always rotate both.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from ..config import get_settings
from ..deps import AuthRateLimit, CSRFProtected, CurrentUser, DbSession
from ..errors import APIError, unauthorized, validation_error
from ..logging_setup import log_context
from ..models import EmailToken, User, UserSession
from ..schemas import (
    LoginRequest,
    MagicLinkConfirm,
    MagicLinkRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    SessionOut,
    UserOut,
)
from ..security.csrf import issue_csrf_token
from ..security.passwords import (
    WeakPasswordError,
    hash_password,
    needs_rehash,
    verify_password,
)
from ..security.tokens import as_utc, expiry, generate_token, hash_token, utcnow
from ..services import consent as consent_service
from ..services.email import send_magic_link, send_password_reset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

RESET_TTL_SECONDS = 3600
MAGIC_LINK_TTL_SECONDS = 900


def _set_auth_cookies(response: Response, *, session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    common = {
        "domain": settings.cookie_domain or None,
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "max_age": settings.session_ttl_seconds,
    }
    response.set_cookie(settings.session_cookie_name, session_token, httponly=True, **common)
    # Readable by the SPA so it can echo the value in the X-CSRF-Token header.
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            name, path="/", domain=settings.cookie_domain or None, samesite=settings.cookie_samesite
        )


def _start_session(db, response: Response, user: User) -> SessionOut:
    settings = get_settings()
    token = generate_token()
    csrf_token = issue_csrf_token()
    expires_at = expiry(settings.session_ttl_seconds)
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    db.commit()
    _set_auth_cookies(response, session_token=token, csrf_token=csrf_token)
    return SessionOut(
        user=UserOut.model_validate(user), csrf_token=csrf_token, expires_at=expires_at
    )


def _find_user(db, email: str) -> User | None:
    return db.execute(
        select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None))
    ).scalar_one_or_none()


@router.post(
    "/register",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AuthRateLimit],
    summary="Create an account",
)
def register(payload: RegisterRequest, response: Response, db: DbSession) -> SessionOut:
    """Create an account and sign in.

    Acceptance of the terms and of the authorized-use policy is recorded as
    consent entries stamped with the policy versions in force.
    """
    email = payload.email.strip().lower()
    if _find_user(db, email) is not None:
        raise APIError(
            "email_in_use",
            "An account with that email already exists. Try signing in instead.",
            status_code=status.HTTP_409_CONFLICT,
        )
    try:
        password_hash = hash_password(payload.password)
    except WeakPasswordError as exc:
        raise validation_error(str(exc)) from exc

    settings = get_settings()
    user = User(
        email=email,
        name=payload.name.strip()[:120],
        password_hash=password_hash,
        retention_preferences={"retention_days": settings.default_retention_days},
    )
    db.add(user)
    db.flush()

    consent_service.record_consent(db, user=user, consent_type="terms")
    consent_service.record_consent(db, user=user, consent_type="privacy")
    consent_service.record_consent(db, user=user, consent_type="authorized_use_policy")

    logger.info("account created", extra=log_context(user_id=user.id))
    return _start_session(db, response, user)


@router.post(
    "/login",
    response_model=SessionOut,
    dependencies=[AuthRateLimit],
    summary="Sign in with email and password",
)
def login(payload: LoginRequest, response: Response, db: DbSession) -> SessionOut:
    user = _find_user(db, payload.email)
    # Always run a verification so a missing account and a wrong password take
    # the same amount of time.
    stored_hash = user.password_hash if user else ""
    if not verify_password(payload.password, stored_hash) or user is None:
        raise unauthorized("That email and password combination is not correct.")
    if not user.is_active:
        raise unauthorized("This account is disabled.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    return _start_session(db, response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
def logout(request: Request, response: Response, db: DbSession) -> Response:
    """Revoke the current session and clear its cookies."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        record = db.execute(
            select(UserSession).where(UserSession.token_hash == hash_token(token))
        ).scalar_one_or_none()
        if record is not None:
            record.revoked_at = utcnow()
            db.commit()
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session", response_model=UserOut, summary="Who am I")
def whoami(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/password-reset",
    dependencies=[AuthRateLimit],
    summary="Request a password reset link",
)
def request_password_reset(payload: PasswordResetRequest, db: DbSession) -> dict:
    """Always reports success so the endpoint cannot enumerate accounts."""
    user = _find_user(db, payload.email)
    debug_token: str | None = None
    if user is not None:
        token = generate_token()
        db.add(
            EmailToken(
                user_id=user.id,
                purpose="reset",
                token_hash=hash_token(token),
                expires_at=expiry(RESET_TTL_SECONDS),
            )
        )
        db.commit()
        debug_token = send_password_reset(user.email, token)

    body: dict = {
        "status": "sent",
        "message": "If that email has an account, a reset link is on its way.",
    }
    if debug_token:
        body["debug_token"] = debug_token
    return body


@router.post(
    "/password-reset/confirm",
    response_model=SessionOut,
    dependencies=[AuthRateLimit],
    summary="Complete a password reset",
)
def confirm_password_reset(
    payload: PasswordResetConfirm, response: Response, db: DbSession
) -> SessionOut:
    record = db.execute(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(payload.token),
            EmailToken.purpose == "reset",
        )
    ).scalar_one_or_none()
    if record is None or record.used_at is not None:
        raise validation_error("That reset link is not valid. Request a new one.")
    expires = as_utc(record.expires_at)
    if expires is None or expires <= utcnow():
        raise validation_error("That reset link has expired. Request a new one.")

    user = db.get(User, record.user_id)
    if user is None or user.deleted_at is not None:
        raise validation_error("That reset link is not valid. Request a new one.")

    try:
        user.password_hash = hash_password(payload.password)
    except WeakPasswordError as exc:
        raise validation_error(str(exc)) from exc

    record.used_at = utcnow()
    # Changing a password invalidates every other session.
    for session_record in user.sessions:
        session_record.revoked_at = utcnow()
    db.commit()
    return _start_session(db, response, user)


@router.post(
    "/magic-link",
    dependencies=[AuthRateLimit],
    summary="Request a passwordless sign-in link",
)
def request_magic_link(payload: MagicLinkRequest, db: DbSession) -> dict:
    user = _find_user(db, payload.email)
    debug_token: str | None = None
    if user is not None:
        token = generate_token()
        db.add(
            EmailToken(
                user_id=user.id,
                purpose="magic_link",
                token_hash=hash_token(token),
                expires_at=expiry(MAGIC_LINK_TTL_SECONDS),
            )
        )
        db.commit()
        debug_token = send_magic_link(user.email, token)

    body: dict = {
        "status": "sent",
        "message": "If that email has an account, a sign-in link is on its way.",
    }
    if debug_token:
        body["debug_token"] = debug_token
    return body


@router.post(
    "/magic-link/confirm",
    response_model=SessionOut,
    dependencies=[AuthRateLimit],
    summary="Sign in with a passwordless link",
)
def confirm_magic_link(payload: MagicLinkConfirm, response: Response, db: DbSession) -> SessionOut:
    record = db.execute(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(payload.token),
            EmailToken.purpose == "magic_link",
        )
    ).scalar_one_or_none()
    if record is None or record.used_at is not None:
        raise validation_error("That sign-in link is not valid. Request a new one.")
    expires = as_utc(record.expires_at)
    if expires is None or expires <= utcnow():
        raise validation_error("That sign-in link has expired. Request a new one.")

    user = db.get(User, record.user_id)
    if user is None or user.deleted_at is not None:
        raise validation_error("That sign-in link is not valid. Request a new one.")

    record.used_at = utcnow()
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    db.commit()
    return _start_session(db, response, user)


@router.post(
    "/sessions/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CSRFProtected],
    summary="Sign out everywhere",
)
def revoke_all_sessions(user: CurrentUser, response: Response, db: DbSession) -> Response:
    for record in user.sessions:
        if record.revoked_at is None:
            record.revoked_at = utcnow()
    db.commit()
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
