"""Asset ingestion: validation, orientation, previews and provenance."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from artrestore_imaging import (
    ImagingError,
    describe_metadata,
    downscale,
    encode_raster,
    estimated_output_bytes,
    load_safe_raster,
    validate_image_bytes,
)

from ..config import get_settings
from ..errors import APIError, not_found, validation_error
from ..logging_setup import log_context, truncate_key
from ..models import Asset, Project
from ..storage import Storage, build_object_key

logger = logging.getLogger(__name__)

AUDIO_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"RIFF", "audio/wav"),
    (b"OggS", "audio/ogg"),
)


def get_owned_asset(db: Session, asset_id: str, project: Project) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or asset.project_id != project.id:
        raise not_found("That asset does not exist.")
    return asset


def primary_source_asset(db: Session, project_id: str) -> Asset | None:
    return db.execute(
        select(Asset)
        .where(
            Asset.project_id == project_id,
            Asset.type == "source",
            Asset.upload_complete.is_(True),
        )
        .order_by(Asset.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def sniff_audio_mime(data: bytes) -> str | None:
    for signature, mime in AUDIO_SIGNATURES:
        if data.startswith(signature):
            if signature == b"RIFF" and data[8:12] != b"WAVE":
                continue
            return mime
    return None


def finalise_upload(db: Session, *, project: Project, asset: Asset, storage: Storage) -> Asset:
    """Validate uploaded bytes and record what was actually received.

    Runs *after* the browser has PUT to the signed URL. The declared content
    type from the upload request is not trusted; the stored bytes are sniffed
    and parsed, and the asset is only marked complete if they hold up.
    """
    settings = get_settings()
    try:
        data = storage.get_bytes(asset.storage_key)
    except Exception as exc:  # noqa: BLE001
        raise validation_error(
            "The upload did not arrive. Try uploading the file again.",
            details={"asset_id": asset.id},
        ) from exc

    if asset.type == "audio":
        return _finalise_audio(db, asset=asset, data=data, settings=settings, storage=storage)

    try:
        validated = validate_image_bytes(
            data,
            allowed_mime_types=settings.allowed_upload_mime_tuple,
            max_bytes=settings.max_upload_bytes,
            max_pixels=settings.max_image_pixels,
            declared_mime=asset.mime_type,
        )
    except ImagingError as exc:
        # Commit the cleanup before raising: the request's session is rolled
        # back on the way out, which would otherwise resurrect the asset row
        # that the rejected bytes belong to.
        storage.delete(asset.storage_key)
        db.delete(asset)
        db.commit()
        raise APIError(
            exc.code,
            exc.message,
            status_code=422,
            details=exc.details,
        ) from exc

    raster = load_safe_raster(data, max_pixels=settings.max_image_pixels)
    orientation = describe_metadata(data).get("orientation", 1)

    asset.mime_type = validated.mime_type
    asset.width = raster.width
    asset.height = raster.height
    asset.byte_size = len(data)
    asset.checksum = hashlib.sha256(data).hexdigest()
    asset.upload_complete = True
    asset.asset_metadata = {
        **raster.metadata_summary,
        "color_mode": validated.color_mode,
        "has_alpha": raster.has_alpha,
        "megapixels": validated.megapixels,
        "orientation_corrected": orientation != 1,
        "source_width": validated.width,
        "source_height": validated.height,
        "estimated_output_bytes": estimated_output_bytes(validated),
    }

    preview = downscale(raster, settings.preview_max_dimension)
    preview_key = build_object_key(
        project.user_id, project.id, "source_preview", f"{asset.id}.webp"
    )
    preview_bytes = encode_raster(preview, mime_type="image/webp", quality=82)
    storage.put_bytes(preview_key, preview_bytes, "image/webp")
    db.add(
        Asset(
            project_id=project.id,
            type="source_preview",
            storage_key=preview_key,
            mime_type="image/webp",
            width=preview.width,
            height=preview.height,
            byte_size=len(preview_bytes),
            upload_complete=True,
            asset_metadata={"derived_from": asset.id},
        )
    )

    db.flush()
    logger.info(
        "asset finalised",
        extra=log_context(
            asset_type=asset.type,
            storage_key_prefix=truncate_key(asset.storage_key),
            width=asset.width,
            height=asset.height,
        ),
    )
    return asset


def _finalise_audio(db: Session, *, asset: Asset, data: bytes, settings, storage: Storage) -> Asset:
    if len(data) > settings.max_audio_bytes:
        storage.delete(asset.storage_key)
        db.delete(asset)
        db.commit()
        raise validation_error(
            "That audio file is larger than the configured maximum.",
            details={"max_bytes": settings.max_audio_bytes},
        )
    mime = sniff_audio_mime(data)
    if mime is None or mime not in settings.allowed_audio_mime_tuple:
        storage.delete(asset.storage_key)
        db.delete(asset)
        db.commit()
        raise validation_error(
            "That file is not a supported audio format (MP3, WAV or Ogg).",
            details={"allowed": list(settings.allowed_audio_mime_tuple)},
        )
    asset.mime_type = mime
    asset.byte_size = len(data)
    asset.checksum = hashlib.sha256(data).hexdigest()
    asset.upload_complete = True
    asset.asset_metadata = {"kind": "audio"}
    db.flush()
    return asset


def analysis_payload(asset: Asset) -> dict:
    """The pre-processing summary shown in the upload panel."""
    metadata = asset.asset_metadata or {}
    provenance = (metadata.get("provenance") or {}) if isinstance(metadata, dict) else {}
    warnings: list[str] = []
    if provenance.get("has_c2pa"):
        warnings.append(
            "This image carries Content Credentials. They are preserved on export and cannot be "
            "removed here."
        )
    if provenance.get("exif_rights"):
        warnings.append(
            "Authorship metadata is present in EXIF. It travels with every export."
        )
    if metadata.get("orientation_corrected"):
        warnings.append("EXIF orientation was applied so the preview matches the exported result.")
    if metadata.get("has_alpha"):
        warnings.append("Transparency detected; the alpha channel is preserved through cleanup.")

    return {
        "width": asset.width or 0,
        "height": asset.height or 0,
        "color_mode": metadata.get("color_mode", "RGB"),
        "has_alpha": bool(metadata.get("has_alpha")),
        "megapixels": float(metadata.get("megapixels", 0.0)),
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
        "estimated_output_bytes": int(metadata.get("estimated_output_bytes", asset.byte_size)),
        "orientation_corrected": bool(metadata.get("orientation_corrected")),
        "provenance": provenance,
        "warnings": warnings,
    }
