"""Exports: create image exports, list history and mint download links."""

from __future__ import annotations

import logging

from artrestore_imaging import encode_raster, load_safe_raster
from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from ..config import get_settings
from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, StorageDep
from ..errors import not_found, validation_error
from ..logging_setup import log_context
from ..models import Asset, Export
from ..schemas import ExportListOut, ExportRequest, ExportWithUrlOut
from ..services import assets as asset_service
from ..services import projects as project_service
from ..storage import build_object_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}/exports", tags=["exports"])

MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "tiff": "image/tiff",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "gif": "image/gif",
    "zip": "application/zip",
    "json": "application/json",
}

EXTENSION_BY_FORMAT = {**{key: key for key in MIME_BY_FORMAT}, "jpeg": "jpg"}


@router.post(
    "",
    response_model=ExportWithUrlOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Export the cleaned image",
)
def create_export(
    project_id: str,
    payload: ExportRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> ExportWithUrlOut:
    """Write an export of the processed image.

    Resolution is never silently changed and the source colour profile,
    EXIF, XMP, IPTC and C2PA blocks are carried across unmodified.
    """
    settings = get_settings()
    project = project_service.get_owned_project(db, project_id, user)

    processed = db.execute(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.type == "processed")
        .order_by(Asset.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if processed is None:
        raise validation_error("There is no processed image to export yet. Run a cleanup first.")

    source = asset_service.primary_source_asset(db, project.id)
    raster = load_safe_raster(
        storage.get_bytes(processed.storage_key), max_pixels=settings.max_image_pixels
    )
    if source is not None:
        # Carry the *original* metadata blocks, not the intermediate's.
        original = load_safe_raster(
            storage.get_bytes(source.storage_key), max_pixels=settings.max_image_pixels
        )
        raster.preserved_metadata = original.preserved_metadata

    mime = MIME_BY_FORMAT[payload.format]
    data = encode_raster(raster, mime_type=mime, quality=payload.quality)

    extension = EXTENSION_BY_FORMAT[payload.format]
    key = build_object_key(user.id, project.id, "export", f"cleanup-{processed.id}.{extension}")
    storage.put_bytes(key, data, mime)

    disclosure = {
        "processing": "authorized visible-overlay cleanup",
        "provenance_preserved": True,
        "preserved_metadata_blocks": sorted(raster.preserved_metadata.keys()),
        "source_resolution": [raster.width, raster.height],
    }
    export = Export(
        project_id=project.id,
        format=payload.format,
        storage_key=key,
        byte_size=len(data),
        settings={"quality": payload.quality, "mime_type": mime},
        disclosure_metadata=disclosure,
    )
    db.add(export)
    db.commit()

    logger.info(
        "export created",
        extra=log_context(project_id=project.id, format=payload.format, bytes=len(data)),
    )
    item = ExportWithUrlOut.model_validate(export)
    item.download_url = storage.signed_download_url(
        key,
        expires_in=settings.signed_url_ttl_seconds,
        filename=f"{project.name[:60]}.{extension}",
    )
    item.expires_in = settings.signed_url_ttl_seconds
    return item


@router.get("", response_model=ExportListOut, summary="Export history")
def list_exports(
    project_id: str,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
) -> ExportListOut:
    project = project_service.get_owned_project(db, project_id, user)
    total = db.execute(
        select(func.count(Export.id)).where(Export.project_id == project.id)
    ).scalar_one()
    rows = db.execute(
        select(Export)
        .where(Export.project_id == project.id)
        .order_by(Export.created_at.desc())
        .limit(limit)
    ).scalars()
    from ..schemas import ExportOut

    return ExportListOut(items=[ExportOut.model_validate(row) for row in rows], total=int(total))


@router.get(
    "/{export_id}/download",
    response_model=ExportWithUrlOut,
    summary="Get a signed download link",
)
def download_export(
    project_id: str, export_id: str, user: CurrentUser, db: DbSession, storage: StorageDep
) -> ExportWithUrlOut:
    """Mint a short-lived signed URL. The URL is never written to the logs."""
    settings = get_settings()
    project = project_service.get_owned_project(db, project_id, user)
    export = db.get(Export, export_id)
    if export is None or export.project_id != project.id:
        raise not_found("That export does not exist.")

    extension = EXTENSION_BY_FORMAT.get(export.format, export.format)
    item = ExportWithUrlOut.model_validate(export)
    item.download_url = storage.signed_download_url(
        export.storage_key,
        expires_in=settings.signed_url_ttl_seconds,
        filename=f"{project.name[:60]}.{extension}",
    )
    item.expires_in = settings.signed_url_ttl_seconds
    return item


@router.delete(
    "/{export_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CSRFProtected],
    summary="Delete an export",
)
def delete_export(
    project_id: str, export_id: str, user: CurrentUser, db: DbSession, storage: StorageDep
) -> None:
    project = project_service.get_owned_project(db, project_id, user)
    export = db.get(Export, export_id)
    if export is None or export.project_id != project.id:
        raise not_found("That export does not exist.")
    storage.delete(export.storage_key)
    db.delete(export)
    db.commit()
