"""The cleanup task.

Runs the imaging pipeline against a stored source image and a stored mask
version, writes the processed result and its previews as new assets, and never
touches the source object.
"""

from __future__ import annotations

import logging

from artrestore_api.db import session_scope
from artrestore_api.logging_setup import log_context
from artrestore_api.models import Asset, Mask, ProcessingJob, Project
from artrestore_api.queue import TASK_CLEANUP, get_celery_app
from artrestore_api.services import jobs as job_service
from artrestore_api.storage import build_object_key, get_storage
from artrestore_imaging import (
    CleanupOptions,
    MaskAdjustments,
    build_previews,
    difference_map,
    encode_raster,
    load_safe_raster,
    rasterize_editor_state,
    run_cleanup,
)
from artrestore_imaging.errors import ImagingError, JobCancelledError
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from ..progress import ProgressReporter

logger = logging.getLogger(__name__)

celery_app = get_celery_app()


@celery_app.task(name=TASK_CLEANUP, bind=True, acks_late=True)
def run_cleanup_task(self, job_id: str) -> dict:
    """Execute one cleanup job."""
    from artrestore_api.config import get_settings

    settings = get_settings()
    storage = get_storage()
    reporter = ProgressReporter(job_id)

    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.warning("cleanup task for unknown job", extra=log_context(job_id=job_id))
            return {"status": "unknown_job"}
        if job.status == "cancelled" or job.cancel_requested:
            job_service.mark_cancelled(session, job)
            return {"status": "cancelled"}
        if job.status == "succeeded":
            # Idempotent replay: the broker redelivered a finished job.
            return {"status": "already_complete", **(job.result or {})}

        project = session.get(Project, job.project_id)
        parameters = dict(job.parameters or {})
        job_service.mark_running(session, job)

    try:
        asset_ids = [str(value) for value in (parameters.get("asset_ids") or [])]

        with session_scope() as session:
            mask_row = session.execute(
                select(Mask).where(
                    Mask.project_id == project.id,
                    Mask.version == int(parameters.get("mask_version", 0)),
                )
            ).scalar_one_or_none()
            if mask_row is None:
                raise ImagingError("The requested mask version no longer exists.")
            editor_state = dict(mask_row.editor_state or {})
            mask_version = mask_row.version

            if asset_ids:
                rows = session.execute(
                    select(Asset).where(
                        Asset.project_id == project.id,
                        Asset.id.in_(asset_ids),
                        Asset.type == "source",
                        Asset.upload_complete.is_(True),
                    )
                ).scalars()
                by_id = {str(asset.id): asset.storage_key for asset in rows}
                source_keys = [(aid, by_id[aid]) for aid in asset_ids if aid in by_id]
                if not source_keys:
                    raise ImagingError("None of the requested uploads exist any more.")
            else:
                source = session.execute(
                    select(Asset)
                    .where(
                        Asset.project_id == project.id,
                        Asset.type == "source",
                        Asset.upload_complete.is_(True),
                    )
                    .order_by(Asset.created_at.asc())
                    .limit(1)
                ).scalar_one_or_none()
                if source is None:
                    raise ImagingError("This project has no completed source upload.")
                source_keys = [(str(source.id), source.storage_key)]

        adjustments = MaskAdjustments.from_dict(
            parameters.get("adjustments") or editor_state.get("adjustments")
        )
        options = CleanupOptions(
            mode=str(parameters.get("mode", "fast_fill")),
            adjustments=adjustments,
            grain_strength=float(parameters.get("grain_strength", 1.0)),
            edge_strength=float(parameters.get("edge_strength", 0.6)),
            colour_match=bool(parameters.get("colour_match", True)),
            seed=int(parameters.get("seed", 0)),
            protected_enforcement=settings.protected_region_enforcement,
            acknowledged_protected_kinds=tuple(
                parameters.get("acknowledged_protected_kinds") or []
            ),
            backend_settings=settings.backend_settings,
        )

        batch = len(source_keys) > 1
        items: list[dict] = []
        payload: dict = {}
        total = len(source_keys)

        for index, (source_asset_id, source_key) in enumerate(source_keys):
            base = index / float(total)
            span = 1.0 / float(total)
            position = f" ({index + 1}/{total})" if batch else ""
            try:
                reporter.report(base * 0.85 + 0.02, f"Loading image{position}", force=True)
                raster = load_safe_raster(
                    storage.get_bytes(source_key), max_pixels=settings.max_image_pixels
                )
                # The declarative mask scales to each image's dimensions, so
                # one selection covers a whole same-framing shoot.
                raw_mask = rasterize_editor_state(editor_state, raster.width, raster.height)

                result = run_cleanup(
                    raster,
                    raw_mask,
                    options,
                    progress=lambda fraction, message, _b=base, _s=span, _p=position: (
                        reporter.report((_b + fraction * _s * 0.9) * 0.85 + 0.05, message + _p)
                    ),
                    should_cancel=reporter.should_cancel,
                )
                item_payload = _store_results(
                    project_id=project.id,
                    user_id=project.user_id,
                    mask_version=mask_version,
                    original=raster,
                    result=result,
                    storage=storage,
                    source_asset_id=source_asset_id if batch else None,
                )
                items.append(
                    {"asset_id": source_asset_id, "status": "succeeded", **result.summary()}
                )
                payload = item_payload
            except ImagingError as exc:
                # In a batch, one refused or failed image (a protected region,
                # a corrupt file) must not sink the others.
                if not batch:
                    raise
                items.append(
                    {
                        "asset_id": source_asset_id,
                        "status": "failed",
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                )

        reporter.report(0.85, "Writing results", force=True)
        if batch:
            succeeded = [item for item in items if item["status"] == "succeeded"]
            failed = [item for item in items if item["status"] == "failed"]
            if not succeeded:
                first = failed[0]
                error = ImagingError(
                    f"No image in the batch could be processed. First error: {first['message']}",
                    details={"items": items},
                )
                error.code = str(first.get("code") or "batch_all_failed")
                raise error
            payload = {
                "status": "succeeded",
                "batch": True,
                "mask_version": mask_version,
                "items": items,
                "succeeded_count": len(succeeded),
                "failed_count": len(failed),
            }

        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is None:
                return {"status": "unknown_job"}
            if job.cancel_requested:
                job_service.mark_cancelled(session, job)
                return {"status": "cancelled"}
            job_service.mark_succeeded(session, job, payload)
        logger.info("cleanup complete", extra=log_context(job_id=job_id, mode=options.mode))
        return payload

    except SoftTimeLimitExceeded:
        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job_service.mark_failed(
                    session,
                    job,
                    code="timeout",
                    message="The cleanup ran past the time limit and was stopped. "
                    "Try a smaller selection or a faster mode.",
                )
        return {"status": "failed", "code": "timeout"}
    except JobCancelledError:
        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job_service.mark_cancelled(session, job)
        return {"status": "cancelled"}
    except ImagingError as exc:
        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job_service.mark_failed(
                    session,
                    job,
                    code=exc.code,
                    message=exc.message,
                    result={"details": exc.details},
                )
        logger.warning("cleanup rejected", extra=log_context(job_id=job_id, code=exc.code))
        return {"status": "failed", "code": exc.code}
    except Exception as exc:
        logger.exception("cleanup failed", extra=log_context(job_id=job_id))
        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job_service.mark_failed(
                    session,
                    job,
                    code="internal_error",
                    message="The cleanup could not be completed. Try again or adjust the mask.",
                )
        raise exc


def _store_results(
    *, project_id, user_id, mask_version, original, result, storage, source_asset_id=None
) -> dict:
    """Persist the processed image, its previews and the difference map."""
    # Batch items carry their source asset in the object key so results from
    # different images of the same run never overwrite each other.
    stem = f"cleanup-v{mask_version}"
    if source_asset_id:
        stem = f"{stem}-{source_asset_id[:8]}"

    settings_mime = "image/png"
    processed_bytes = encode_raster(result.raster, mime_type=settings_mime)
    processed_key = build_object_key(user_id, project_id, "processed", f"{stem}.png")
    storage.put_bytes(processed_key, processed_bytes, settings_mime)

    previews = build_previews(original, result.raster, max_dimension=1200)
    preview_bytes = encode_raster(previews["after"], mime_type="image/webp", quality=84)
    preview_key = build_object_key(user_id, project_id, "processed_preview", f"{stem}.webp")
    storage.put_bytes(preview_key, preview_bytes, "image/webp")

    difference = difference_map(original, result.raster)
    difference_raster = result.raster.with_rgb(difference)
    difference_raster.alpha = None
    difference_bytes = encode_raster(difference_raster, mime_type="image/webp", quality=70)
    difference_key = build_object_key(user_id, project_id, "difference", f"{stem}.webp")
    storage.put_bytes(difference_key, difference_bytes, "image/webp")

    with session_scope() as session:
        for asset_type, key, mime, data, dimensions in (
            ("processed", processed_key, settings_mime, processed_bytes, result.raster.size),
            ("processed_preview", preview_key, "image/webp", preview_bytes, previews["after"].size),
            ("difference", difference_key, "image/webp", difference_bytes, result.raster.size),
        ):
            session.add(
                Asset(
                    project_id=project_id,
                    type=asset_type,
                    storage_key=key,
                    mime_type=mime,
                    width=dimensions[0],
                    height=dimensions[1],
                    byte_size=len(data),
                    upload_complete=True,
                    asset_metadata={
                        "mask_version": mask_version,
                        "mode": result.mode,
                        **({"source_asset_id": source_asset_id} if source_asset_id else {}),
                    },
                )
            )

    return {
        "status": "succeeded",
        "processed_asset_key_written": True,
        "mask_version": mask_version,
        **result.summary(),
    }
