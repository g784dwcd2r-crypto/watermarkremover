"""Timelapse reconstruction: analysis, the stage timeline, previews and renders."""

from __future__ import annotations

import logging

from artrestore_timelapse import (
    CANVAS_PRESETS,
    EASING_CURVES,
    END_CARD_TEXT,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    MODE_LABELS,
    MODES,
    RECONSTRUCTION_TYPE,
    SPEED_CHOICES,
    SPEED_RANGE,
    STAGE_LABELS,
    SUPPORTED_FPS,
)
from fastapi import APIRouter, status
from sqlalchemy import delete, select

from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, JobRateLimit
from ..errors import validation_error
from ..logging_setup import log_context
from ..models import Asset, TimelapseStage
from ..queue import TASK_TIMELAPSE_ANALYZE, TASK_TIMELAPSE_PREVIEW, TASK_TIMELAPSE_RENDER
from ..schemas import (
    JobOut,
    StageListIn,
    StageListOut,
    StageOut,
    TimelapseAnalyzeRequest,
    TimelapseRenderRequest,
)
from ..services import consent as consent_service
from ..services import jobs as job_service
from ..services import projects as project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}/timelapse", tags=["timelapse"])


@router.get("/options", summary="Modes, presets and limits")
def timelapse_options() -> dict:
    """Everything the timelapse editor needs to render its controls."""
    return {
        "modes": [
            {"key": key, "label": MODE_LABELS[key], "requires_uploads": key == "real_intermediates"}
            for key in MODES
        ],
        "stage_types": [{"key": key, "label": label} for key, label in STAGE_LABELS.items()],
        "presets": [preset.to_dict() for preset in CANVAS_PRESETS.values()],
        "fps_options": list(SUPPORTED_FPS),
        "transition_curves": list(EASING_CURVES),
        "duration_seconds": {"min": MIN_DURATION_SECONDS, "max": MAX_DURATION_SECONDS},
        "speeds": [{"value": value, "label": label} for value, label in SPEED_CHOICES],
        "speed_range": {"min": SPEED_RANGE[0], "max": SPEED_RANGE[1]},
        "disclosure": {
            "reconstruction_type": RECONSTRUCTION_TYPE,
            "end_card_text": END_CARD_TEXT,
            "end_card_default": True,
            "note": (
                "Every export is labelled a reconstruction in its file metadata. That cannot be "
                "turned off. The visible end card is on by default and can be disabled."
            ),
        },
    }


@router.post(
    "/analyze",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CSRFProtected, JobRateLimit],
    summary="Analyse the artwork and seed a stage timeline",
)
def analyze(
    project_id: str, payload: TimelapseAnalyzeRequest, user: CurrentUser, db: DbSession
) -> JobOut:
    """Break the finished artwork into layers and build an editable timeline."""
    project = project_service.get_owned_project(db, project_id, user)
    consent_service.require_ownership_confirmation(db, project)

    if payload.mode == "real_intermediates":
        count = db.execute(
            select(Asset.id).where(
                Asset.project_id == project.id,
                Asset.type == "intermediate",
                Asset.upload_complete.is_(True),
            )
        ).all()
        if not count:
            raise validation_error(
                "Real Intermediate Frames uses your own progress images. Upload at least one "
                "before choosing this mode.",
                details={"required_asset_type": "intermediate"},
            )

    job, created = job_service.create_job(
        db,
        project=project,
        job_type="timelapse_analyze",
        parameters={
            "asset_id": payload.asset_id,
            "mode": payload.mode,
            "seed": payload.seed,
            "duration_seconds": 12.0,
        },
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    if created:
        job_service.dispatch(job, TASK_TIMELAPSE_ANALYZE)
        db.commit()
        db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/stages", response_model=StageListOut, summary="Get the stage timeline")
def list_stages(project_id: str, user: CurrentUser, db: DbSession) -> StageListOut:
    project = project_service.get_owned_project(db, project_id, user)
    rows = list(
        db.execute(
            select(TimelapseStage)
            .where(TimelapseStage.project_id == project.id)
            .order_by(TimelapseStage.order_index)
        ).scalars()
    )
    return StageListOut(
        items=[StageOut.model_validate(row) for row in rows],
        total_duration=round(sum(row.duration for row in rows if row.enabled), 3),
    )


@router.put(
    "/stages",
    response_model=StageListOut,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Replace the stage timeline",
)
def replace_stages(
    project_id: str, payload: StageListIn, user: CurrentUser, db: DbSession
) -> StageListOut:
    """Save the user's reordering, retiming and per-stage settings.

    The whole timeline is replaced in one call so the saved state always matches
    what the editor is showing.
    """
    project = project_service.get_owned_project(db, project_id, user)
    if not payload.stages:
        raise validation_error("A timeline needs at least one stage.")

    total = sum(stage.duration for stage in payload.stages if stage.enabled)
    if total > MAX_DURATION_SECONDS:
        raise validation_error(
            f"The timeline is {total:.0f}s; the maximum is {MAX_DURATION_SECONDS:.0f}s.",
            details={"total_duration": total, "max": MAX_DURATION_SECONDS},
        )
    if total < MIN_DURATION_SECONDS:
        raise validation_error(
            f"The timeline is {total:.1f}s; the minimum is {MIN_DURATION_SECONDS:.0f}s.",
            details={"total_duration": total, "min": MIN_DURATION_SECONDS},
        )

    db.execute(delete(TimelapseStage).where(TimelapseStage.project_id == project.id))
    for index, stage in enumerate(sorted(payload.stages, key=lambda item: item.order_index)):
        db.add(
            TimelapseStage(
                project_id=project.id,
                stage_type=stage.stage_type,
                label=stage.label or STAGE_LABELS.get(stage.stage_type, stage.stage_type),
                order_index=index,
                duration=stage.duration,
                enabled=stage.enabled,
                settings=stage.settings,
            )
        )
    db.commit()
    return list_stages(project_id, user, db)


@router.post(
    "/preview",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CSRFProtected, JobRateLimit],
    summary="Render a low-resolution preview",
)
def render_preview(
    project_id: str, payload: TimelapseRenderRequest, user: CurrentUser, db: DbSession
) -> JobOut:
    return _queue_render(project_id, payload, user, db, preview=True)


@router.post(
    "/render",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CSRFProtected, JobRateLimit],
    summary="Render the final timelapse",
)
def render_final(
    project_id: str, payload: TimelapseRenderRequest, user: CurrentUser, db: DbSession
) -> JobOut:
    return _queue_render(project_id, payload, user, db, preview=False)


def _queue_render(
    project_id: str, payload: TimelapseRenderRequest, user, db, *, preview: bool
) -> JobOut:
    """Queue a render.

    Requires the ownership attestation, and records the reconstruction
    disclosure acknowledgement on the final render so the user cannot later say
    they were unaware the output is not an original recording.
    """
    project = project_service.get_owned_project(db, project_id, user)
    consent_service.require_ownership_confirmation(db, project)

    for asset_id, expected in (
        (payload.audio_asset_id, "audio"),
        (payload.brand_watermark_asset_id, None),
    ):
        if asset_id is None:
            continue
        asset = db.get(Asset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise validation_error("That asset does not belong to this project.")
        if expected and asset.type != expected:
            raise validation_error(f"Asset {asset_id} is not {expected}.")

    if not preview:
        consent_service.record_consent(
            db,
            user=user,
            consent_type="timelapse_disclosure",
            project=project,
            context={
                "mode": payload.mode,
                "end_card_disclosure": payload.end_card_disclosure,
                "reconstruction_type": RECONSTRUCTION_TYPE,
            },
        )

    parameters = payload.model_dump()
    parameters["preview"] = preview
    if preview:
        # Previews are for judging timing, not for publishing.
        parameters["formats"] = ["mp4"]

    job, created = job_service.create_job(
        db,
        project=project,
        job_type="timelapse_preview" if preview else "timelapse_render",
        parameters=parameters,
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    if created:
        job_service.dispatch(job, TASK_TIMELAPSE_PREVIEW if preview else TASK_TIMELAPSE_RENDER)
        db.commit()
        db.refresh(job)
        logger.info(
            "timelapse render queued",
            extra=log_context(project_id=project.id, job_id=job.id, preview=preview),
        )
    return JobOut.model_validate(job)
