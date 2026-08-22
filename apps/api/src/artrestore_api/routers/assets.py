"""Uploads, asset listings, previews and the local storage gateway."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..config import get_settings
from ..deps import (
    CSRFProtected,
    CurrentUser,
    DbSession,
    DefaultRateLimit,
    StorageDep,
    UploadRateLimit,
)
from ..errors import APIError, not_found, validation_error
from ..logging_setup import log_context, truncate_key
from ..models import Asset
from ..schemas import (
    AssetAnalysisOut,
    AssetWithUrlOut,
    UploadCompleteRequest,
    UploadInitOut,
    UploadInitRequest,
)
from ..services import assets as asset_service
from ..services import consent as consent_service
from ..services import projects as project_service
from ..storage import LocalStorage, ObjectNotFoundError, build_object_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}/assets", tags=["assets"])
storage_router = APIRouter(prefix="/v1/storage", tags=["assets"])

RETENTION_NOTICE = (
    "Uploads are private to your account, are never used to train models, and are deleted "
    "automatically after your retention window."
)


@router.post(
    "/uploads",
    response_model=UploadInitOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected, UploadRateLimit],
    summary="Start an upload",
)
def start_upload(
    project_id: str,
    payload: UploadInitRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> UploadInitOut:
    """Reserve an asset row and mint a short-lived signed upload URL.

    The declared content type and size are used only to size the grant. What is
    actually stored is re-validated from the bytes on completion.
    """
    settings = get_settings()
    project = project_service.get_owned_project(db, project_id, user)

    max_bytes = (
        settings.max_audio_bytes if payload.asset_type == "audio" else settings.max_upload_bytes
    )
    if payload.byte_size > max_bytes:
        raise validation_error(
            "That file is larger than the maximum upload size.",
            details={"max_bytes": max_bytes, "byte_size": payload.byte_size},
        )

    allowed = (
        settings.allowed_audio_mime_tuple
        if payload.asset_type == "audio"
        else settings.allowed_upload_mime_tuple
    )
    if payload.content_type not in allowed:
        raise validation_error(
            "That file type is not supported.",
            details={"allowed": list(allowed), "content_type": payload.content_type},
        )

    order_index = int(
        db.execute(
            select(Asset.id).where(Asset.project_id == project.id, Asset.type == payload.asset_type)
        )
        .scalars()
        .all()
        .__len__()
    )

    asset = Asset(
        project_id=project.id,
        type=payload.asset_type,
        storage_key="",
        mime_type=payload.content_type,
        byte_size=0,
        order_index=order_index,
        upload_complete=False,
    )
    db.add(asset)
    db.flush()

    asset.storage_key = build_object_key(
        user.id, project.id, payload.asset_type, f"{asset.id}-{payload.filename}"
    )
    upload = storage.signed_upload(
        asset.storage_key,
        content_type=payload.content_type,
        expires_in=settings.signed_url_ttl_seconds,
        max_bytes=max_bytes,
    )
    db.commit()

    logger.info(
        "upload started",
        extra=log_context(
            project_id=project.id,
            asset_type=payload.asset_type,
            storage_key_prefix=truncate_key(asset.storage_key),
        ),
    )
    return UploadInitOut(
        asset_id=asset.id,
        storage_key=asset.storage_key,
        upload=upload.to_dict(),
        max_bytes=max_bytes,
        retention_days=project.retention_days,
        retention_notice=RETENTION_NOTICE,
    )


@router.post(
    "/uploads/complete",
    response_model=AssetAnalysisOut,
    dependencies=[CSRFProtected, UploadRateLimit],
    summary="Finish an upload",
)
def complete_upload(
    project_id: str,
    payload: UploadCompleteRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> AssetAnalysisOut:
    """Validate the stored bytes and record the ownership attestation.

    ``ownership_confirmed`` must be true. Without it the upload is not completed
    and nothing can be processed.
    """
    project = project_service.get_owned_project(db, project_id, user)
    asset = asset_service.get_owned_asset(db, payload.asset_id, project)
    if asset.upload_complete:
        return AssetAnalysisOut(**asset_service.analysis_payload(asset))

    asset = asset_service.finalise_upload(db, project=project, asset=asset, storage=storage)

    if not consent_service.has_consent(
        db, user_id=user.id, consent_type="ownership_confirmation", project_id=project.id
    ):
        consent_service.record_consent(
            db,
            user=user,
            consent_type="ownership_confirmation",
            project=project,
            context={"asset_id": asset.id, "filename_hash": asset.checksum},
        )
    if project.status == "draft":
        project.status = "ready"
    db.commit()
    return AssetAnalysisOut(**asset_service.analysis_payload(asset))


@router.get("", response_model=list[AssetWithUrlOut], summary="List project assets")
def list_assets(
    project_id: str,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
    asset_type: str | None = Query(None),
    include_urls: bool = Query(True),
) -> list[AssetWithUrlOut]:
    """List assets with short-lived signed download URLs."""
    settings = get_settings()
    project = project_service.get_owned_project(db, project_id, user)
    conditions = [Asset.project_id == project.id]
    if asset_type:
        conditions.append(Asset.type == asset_type)
    rows = db.execute(
        select(Asset).where(*conditions).order_by(Asset.type, Asset.order_index, Asset.created_at)
    ).scalars()

    results: list[AssetWithUrlOut] = []
    for asset in rows:
        item = AssetWithUrlOut.model_validate(asset)
        if include_urls and asset.upload_complete and asset.storage_key:
            item.download_url = storage.signed_download_url(
                asset.storage_key, expires_in=settings.signed_url_ttl_seconds
            )
            item.expires_in = settings.signed_url_ttl_seconds
        results.append(item)
    return results


@router.get("/{asset_id}", response_model=AssetWithUrlOut, summary="Get one asset")
def get_asset(
    project_id: str, asset_id: str, user: CurrentUser, db: DbSession, storage: StorageDep
) -> AssetWithUrlOut:
    settings = get_settings()
    project = project_service.get_owned_project(db, project_id, user)
    asset = asset_service.get_owned_asset(db, asset_id, project)
    item = AssetWithUrlOut.model_validate(asset)
    if asset.upload_complete and asset.storage_key:
        item.download_url = storage.signed_download_url(
            asset.storage_key, expires_in=settings.signed_url_ttl_seconds
        )
        item.expires_in = settings.signed_url_ttl_seconds
    return item


@router.get("/{asset_id}/analysis", response_model=AssetAnalysisOut, summary="Asset analysis")
def get_asset_analysis(
    project_id: str, asset_id: str, user: CurrentUser, db: DbSession
) -> AssetAnalysisOut:
    """Dimensions, colour mode, provenance findings and the export-size estimate."""
    project = project_service.get_owned_project(db, project_id, user)
    asset = asset_service.get_owned_asset(db, asset_id, project)
    if not asset.upload_complete:
        raise validation_error("That upload has not finished yet.")
    return AssetAnalysisOut(**asset_service.analysis_payload(asset))


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CSRFProtected],
    summary="Delete an asset",
)
def delete_asset(
    project_id: str, asset_id: str, user: CurrentUser, db: DbSession, storage: StorageDep
) -> None:
    project = project_service.get_owned_project(db, project_id, user)
    asset = asset_service.get_owned_asset(db, asset_id, project)
    if asset.storage_key:
        storage.delete(asset.storage_key)
    db.delete(asset)
    db.commit()


# ---------------------------------------------------------------------------
# Local storage gateway
# ---------------------------------------------------------------------------


@storage_router.api_route(
    "/{storage_key:path}",
    methods=["GET", "PUT"],
    dependencies=[DefaultRateLimit],
    summary="Signed object gateway (local storage backend only)",
    include_in_schema=False,
)
async def storage_gateway(
    storage_key: str,
    request: Request,
    storage: StorageDep,
    expires: int = Query(...),
    signature: str = Query(...),
    filename: str | None = Query(None),
) -> Response:
    """Serve and accept objects for the filesystem backend.

    Authorization is the signature alone - exactly like S3 presigned URLs - so
    the development path exercises the same expiry and scope semantics as
    production. Not registered when an S3-compatible backend is configured.
    """
    if not isinstance(storage, LocalStorage):
        raise not_found("Signed object gateway is only available with the local storage backend.")

    if not storage.verify_signature(storage_key, expires, signature, request.method):
        raise APIError(
            "invalid_signature",
            "This link has expired or is not valid.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if expires < int(time.time()):
        raise APIError(
            "invalid_signature",
            "This link has expired.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "PUT":
        settings = get_settings()
        body = await request.body()
        if len(body) > max(settings.max_upload_bytes, settings.max_audio_bytes):
            raise validation_error("That file is larger than the maximum upload size.")
        storage.put_bytes(
            storage_key, body, request.headers.get("content-type", "application/octet-stream")
        )
        return Response(status_code=status.HTTP_200_OK)

    try:
        data = storage.get_bytes(storage_key)
    except ObjectNotFoundError as exc:
        raise not_found("That object does not exist.") from exc

    headers = {"Cache-Control": "private, max-age=60"}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(
        iter((data,)), media_type=storage.content_type(storage_key), headers=headers
    )
