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
        with session_scope() as session:
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

            mask_row = session.execute(
                select(Mask).where(
                    Mask.project_id == project.id,
                    Mask.version == int(parameters.get("mask_version", 0)),
                )
            ).scalar_one_or_none()
            if mask_row is None:
                raise ImagingError("The requested mask version no longer exists.")
            source_key = source.storage_key
            editor_state = dict(mask_row.editor_state or {})
            mask_version = mask_row.version

        reporter.report(0.02, "Loading image", force=True)
        raster = load_safe_raster(
            storage.get_bytes(source_key), max_pixels=settings.max_image_pixels
        )

        raw_mask = rasterize_editor_state(editor_state, raster.width, raster.height)
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

        result = run_cleanup(
            raster,
            raw_mask,
            options,
            progress=lambda fraction, message: reporter.report(0.05 + fraction * 0.75, message),
            should_cancel=reporter.should_cancel,
        )

        reporter.report(0.85, "Writing results", force=True)
        payload = _store_results(
            project_id=project.id,
            user_id=project.user_id,
            mask_version=mask_version,
            original=raster,
            result=result,
            storage=storage,
        )

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


def _store_results(*, project_id, user_id, mask_version, original, result, storage) -> dict:
    """Persist the processed image, its previews and the difference map."""
    settings_mime = "image/png"
    processed_bytes = encode_raster(result.raster, mime_type=settings_mime)
    processed_key = build_object_key(
        user_id, project_id, "processed", f"cleanup-v{mask_version}.png"
    )
    storage.put_bytes(processed_key, processed_bytes, settings_mime)

    previews = build_previews(original, result.raster, max_dimension=1200)
    preview_bytes = encode_raster(previews["after"], mime_type="image/webp", quality=84)
    preview_key = build_object_key(
        user_id, project_id, "processed_preview", f"cleanup-v{mask_version}.webp"
    )
    storage.put_bytes(preview_key, preview_bytes, "image/webp")

    difference = difference_map(original, result.raster)
    difference_raster = result.raster.with_rgb(difference)
    difference_raster.alpha = None
    difference_bytes = encode_raster(difference_raster, mime_type="image/webp", quality=70)
    difference_key = build_object_key(
        user_id, project_id, "difference", f"cleanup-v{mask_version}.webp"
    )
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
                    asset_metadata={"mask_version": mask_version, "mode": result.mode},
                )
            )

    return {
        "status": "succeeded",
        "processed_asset_key_written": True,
        "mask_version": mask_version,
        **result.summary(),
    }
