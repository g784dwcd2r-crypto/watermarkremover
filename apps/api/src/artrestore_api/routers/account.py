"""Account settings, storage usage, data export and deletion."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, StorageDep
from ..errors import forbidden
from ..schemas import (
    ConsentOut,
    DeleteAccountRequest,
    StorageUsageOut,
    UpdateAccountRequest,
    UserOut,
)
from ..security.passwords import verify_password
from ..services import consent as consent_service
from ..services import projects as project_service
from ..services import retention as retention_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/account", tags=["account"])


@router.get("", response_model=UserOut, summary="Get account details")
def get_account(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch(
    "",
    response_model=UserOut,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Update account settings",
)
def update_account(payload: UpdateAccountRequest, user: CurrentUser, db: DbSession) -> UserOut:
    """Change the display name or the retention window.

    Changing retention re-dates every existing project, so shortening it takes
    effect on work already uploaded rather than only on new work.
    """
    if payload.name is not None:
        user.name = payload.name.strip()[:120]
    if payload.retention_days is not None:
        retention_service.apply_retention_preference(db, user, payload.retention_days)
    db.commit()
    return UserOut.model_validate(user)


@router.get("/usage", response_model=StorageUsageOut, summary="Storage usage")
def storage_usage(user: CurrentUser, db: DbSession) -> StorageUsageOut:
    return StorageUsageOut(**project_service.storage_usage(db, user.id))


@router.get("/consents", response_model=list[ConsentOut], summary="List attestations")
def list_consents(user: CurrentUser, db: DbSession) -> list[ConsentOut]:
    return [
        ConsentOut.model_validate(record) for record in consent_service.list_consents(db, user.id)
    ]


@router.get("/export", summary="Export all account data as JSON")
def export_account(user: CurrentUser, db: DbSession) -> dict:
    """A portable JSON copy of the account, its projects and its attestations.

    Image bytes are referenced by asset id; download them through the asset
    endpoints, which is what keeps this response small and free of content.
    """
    return retention_service.export_account_data(db, user)


@router.post(
    "/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Delete the account and all of its data",
)
def delete_account(
    payload: DeleteAccountRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
    response: Response,
) -> Response:
    """Erase everything: objects, projects, consent records and the account row.

    Accounts with a password must confirm it. Immediate and irreversible.
    """
    from ..config import get_settings
    from ..routers.auth import _clear_auth_cookies

    if user.password_hash and not (
        payload.password and verify_password(payload.password, user.password_hash)
    ):
        raise forbidden("Confirm your password to delete the account.")

    summary = retention_service.delete_account(db, user, storage)
    db.commit()
    _clear_auth_cookies(response)
    logger.info("account deletion completed", extra={"context": summary})
    response.status_code = status.HTTP_204_NO_CONTENT
    _ = get_settings()
    return response
