"""Mask versions, assisted selection and pre-flight mask checks."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, status
from sqlalchemy import func, select

from artrestore_imaging import (
    CleanupOptions,
    DetectionConfig,
    MaskAdjustments,
    analyse_background,
    assess_mask,
    detect_overlay_candidates,
    detect_protected_regions,
    encode_mask_png,
    load_safe_raster,
    mask_components,
    mask_coverage,
    normalize_mask,
    rasterize_editor_state,
    segment_box,
    segment_point,
    segment_text_overlay,
)
from artrestore_imaging.errors import ImagingError

from ..config import get_settings
from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, StorageDep
from ..errors import APIError, not_found, validation_error
from ..models import Asset, Mask
from ..schemas import (
    DetectOverlaysOut,
    DetectOverlaysRequest,
    MaskCreateRequest,
    MaskOut,
    MaskPreviewOut,
    SegmentOut,
    SegmentRequest,
)
from ..services import assets as asset_service
from ..services import projects as project_service
from ..storage import build_object_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["masks"])

ASSIST_NOTICE = (
    "Detected regions are suggestions. You approve the mask before anything is processed, and "
    "regions that look like attribution or provenance content are flagged rather than selected."
)


def _load_source(db, project, storage, asset_id: str | None = None):
    """Fetch and decode the project's source image."""
    if asset_id:
        asset = asset_service.get_owned_asset(db, asset_id, project)
    else:
        asset = asset_service.primary_source_asset(db, project.id)
    if asset is None or not asset.upload_complete:
        raise validation_error("Upload an image before working on a mask.")
    settings = get_settings()
    data = storage.get_bytes(asset.storage_key)
    return asset, load_safe_raster(data, max_pixels=settings.max_image_pixels)


@router.get("/masks", response_model=list[MaskOut], summary="List mask versions")
def list_masks(project_id: str, user: CurrentUser, db: DbSession) -> list[MaskOut]:
    project = project_service.get_owned_project(db, project_id, user)
    rows = db.execute(
        select(Mask).where(Mask.project_id == project.id).order_by(Mask.version.desc())
    ).scalars()
    return [MaskOut.model_validate(row) for row in rows]


@router.post(
    "/masks",
    response_model=MaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Save a mask version",
)
def create_mask(
    project_id: str,
    payload: MaskCreateRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> MaskOut:
    """Store a new immutable mask version.

    Versions are never overwritten, which is what makes editor autosave safe and
    lets a user retry a cleanup with an earlier selection.
    """
    project = project_service.get_owned_project(db, project_id, user)
    next_version = int(
        db.execute(
            select(func.coalesce(func.max(Mask.version), 0)).where(Mask.project_id == project.id)
        ).scalar_one()
    ) + 1

    mask = Mask(project_id=project.id, version=next_version, editor_state=payload.editor_state)
    db.add(mask)
    db.flush()

    if payload.mask_png_base64:
        try:
            raw = base64.b64decode(payload.mask_png_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise validation_error("mask_png_base64 is not valid base64.") from exc
        if len(raw) > get_settings().max_upload_bytes:
            raise validation_error("That mask image is too large.")
        key = build_object_key(user.id, project.id, "mask", f"v{next_version}.png")
        storage.put_bytes(key, raw, "image/png")
        mask.storage_key = key

    db.commit()
    return MaskOut.model_validate(mask)


@router.get("/masks/{version}", response_model=MaskOut, summary="Get one mask version")
def get_mask(project_id: str, version: int, user: CurrentUser, db: DbSession) -> MaskOut:
    project = project_service.get_owned_project(db, project_id, user)
    mask = db.execute(
        select(Mask).where(Mask.project_id == project.id, Mask.version == version)
    ).scalar_one_or_none()
    if mask is None:
        raise not_found("That mask version does not exist.")
    return MaskOut.model_validate(mask)


@router.post(
    "/masks/{version}/preview",
    response_model=MaskPreviewOut,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Check a mask before processing",
)
def preview_mask(
    project_id: str, version: int, user: CurrentUser, db: DbSession, storage: StorageDep
) -> MaskPreviewOut:
    """Report coverage, regions, the suggested mode and any protected findings.

    This is the call behind the editor's warning banner: the user sees exactly
    what would block or pause a run before spending a job on it.
    """
    project = project_service.get_owned_project(db, project_id, user)
    mask_row = db.execute(
        select(Mask).where(Mask.project_id == project.id, Mask.version == version)
    ).scalar_one_or_none()
    if mask_row is None:
        raise not_found("That mask version does not exist.")

    _, raster = _load_source(db, project, storage)
    settings = get_settings()

    try:
        raw = rasterize_editor_state(mask_row.editor_state or {}, raster.width, raster.height)
        adjustments = MaskAdjustments.from_dict((mask_row.editor_state or {}).get("adjustments"))
        binary, _ = normalize_mask(raw, adjustments)
    except ImagingError as exc:
        raise APIError(exc.code, exc.message, status_code=422, details=exc.details) from exc

    components = mask_components(binary)
    boxes = [(item["x"], item["y"], item["width"], item["height"]) for item in components]
    detected = detect_protected_regions(
        raster.rgb,
        provenance=(raster.metadata_summary or {}).get("provenance"),
        candidate_boxes=boxes,
    )
    assessment = assess_mask(
        binary, detected, enforcement=settings.protected_region_enforcement
    )
    analysis = analyse_background(raster.rgb, binary)

    return MaskPreviewOut(
        version=version,
        coverage=round(mask_coverage(binary), 5),
        region_count=len(components),
        regions=components,
        protection=assessment.to_dict(),
        suggested_mode=analysis.suggested_mode,
        analysis=analysis.to_dict(),
    )


@router.post(
    "/detect-overlays",
    response_model=DetectOverlaysOut,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="AI-assisted overlay detection",
)
def detect_overlays(
    project_id: str,
    payload: DetectOverlaysRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> DetectOverlaysOut:
    """Propose text and overlay regions, and flag protected content.

    Suggestions only: nothing is selected or processed on the user's behalf.
    """
    project = project_service.get_owned_project(db, project_id, user)
    _, raster = _load_source(db, project, storage, payload.asset_id)

    candidates = detect_overlay_candidates(raster.rgb, DetectionConfig(), limit=payload.limit)
    protected = detect_protected_regions(
        raster.rgb, provenance=(raster.metadata_summary or {}).get("provenance")
    )
    return DetectOverlaysOut(
        candidates=[region.to_dict() for region in candidates],
        protected_regions=[region.to_dict() for region in protected],
        notice=ASSIST_NOTICE,
    )


@router.post(
    "/segment",
    response_model=SegmentOut,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Assisted selection",
)
def segment(
    project_id: str,
    payload: SegmentRequest,
    user: CurrentUser,
    db: DbSession,
    storage: StorageDep,
) -> SegmentOut:
    """Turn a dragged box or a click into a pixel-accurate selection."""
    project = project_service.get_owned_project(db, project_id, user)
    _, raster = _load_source(db, project, storage, payload.asset_id)

    if payload.mode in ("box", "text"):
        if not payload.box:
            raise validation_error("A box is required for this selection mode.")
        box = (payload.box[0], payload.box[1], payload.box[2], payload.box[3])
        result = segment_text_overlay(raster.rgb, box) if payload.mode == "text" else segment_box(
            raster.rgb, box
        )
    else:
        if not payload.point:
            raise validation_error("A point is required for point selection.")
        result = segment_point(raster.rgb, (payload.point[0], payload.point[1]))

    return SegmentOut(
        mask_png_base64=base64.b64encode(encode_mask_png(result.mask)).decode("ascii"),
        method=result.method,
        confidence=result.confidence,
        selected_pixels=int((result.mask > 0).sum()),
    )
