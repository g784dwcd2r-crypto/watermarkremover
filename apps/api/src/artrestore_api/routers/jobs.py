"""Cleanup jobs, progress streaming, cancellation and retry."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from ..db import session_scope
from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, JobRateLimit
from ..errors import not_found, validation_error
from ..logging_setup import log_context
from ..models import Mask, ProcessingJob
from ..queue import TASK_CLEANUP
from ..schemas import CleanupJobRequest, JobListOut, JobOut
from ..services import consent as consent_service
from ..services import jobs as job_service
from ..services import projects as project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["jobs"])

#: How often the SSE stream re-reads job state.
STREAM_POLL_SECONDS = 0.5
#: Streams are closed after this long so a forgotten tab cannot hold a worker
#: thread open indefinitely; the client reconnects if it still cares.
STREAM_MAX_SECONDS = 900


@router.post(
    "/cleanup",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CSRFProtected, JobRateLimit],
    summary="Queue a cleanup job",
)
def create_cleanup_job(
    project_id: str, payload: CleanupJobRequest, user: CurrentUser, db: DbSession
) -> JobOut:
    """Queue an authorized cleanup run.

    Requires the project's ownership attestation and an explicitly approved
    mask. Repeating the call with the same ``idempotency_key`` returns the
    original job rather than queueing the work twice.
    """
    project = project_service.get_owned_project(db, project_id, user)
    consent_service.require_ownership_confirmation(db, project)

    version = payload.mask_version
    if version is None:
        latest = project_service.latest_mask(db, project.id)
        if latest is None:
            raise validation_error("Save a mask before running a cleanup.")
        version = latest.version
    else:
        exists = db.execute(
            select(Mask.id).where(Mask.project_id == project.id, Mask.version == version)
        ).first()
        if exists is None:
            raise not_found("That mask version does not exist.")

    if payload.acknowledged_protected_kinds:
        consent_service.record_consent(
            db,
            user=user,
            consent_type="protected_region_attestation",
            project=project,
            context={
                "acknowledged_kinds": payload.acknowledged_protected_kinds,
                "mask_version": version,
            },
        )

    parameters = {
        "mask_version": version,
        "mode": payload.mode,
        "adjustments": payload.adjustments or {},
        "grain_strength": payload.grain_strength,
        "edge_strength": payload.edge_strength,
        "colour_match": payload.colour_match,
        "seed": payload.seed,
        "acknowledged_protected_kinds": payload.acknowledged_protected_kinds,
        "mask_approved": True,
    }

    job, created = job_service.create_job(
        db,
        project=project,
        job_type="cleanup",
        parameters=parameters,
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    if created:
        job_service.dispatch(job, TASK_CLEANUP)
        db.commit()
        # In eager mode the worker has already run and updated the row in its
        # own session; refresh so the response reflects reality either way.
        db.refresh(job)
        logger.info("cleanup queued", extra=log_context(project_id=project.id, job_id=job.id))
    return JobOut.model_validate(job)


@router.get("/jobs", response_model=JobListOut, summary="List jobs for a project")
def list_jobs(
    project_id: str,
    user: CurrentUser,
    db: DbSession,
    job_type: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> JobListOut:
    project = project_service.get_owned_project(db, project_id, user)
    conditions = [ProcessingJob.project_id == project.id]
    if job_type:
        conditions.append(ProcessingJob.job_type == job_type)
    total = db.execute(select(func.count(ProcessingJob.id)).where(*conditions)).scalar_one()
    rows = db.execute(
        select(ProcessingJob)
        .where(*conditions)
        .order_by(ProcessingJob.created_at.desc())
        .limit(limit)
    ).scalars()
    return JobListOut(items=[JobOut.model_validate(row) for row in rows], total=int(total))


@router.get("/jobs/{job_id}", response_model=JobOut, summary="Get job status")
def get_job(project_id: str, job_id: str, user: CurrentUser, db: DbSession) -> JobOut:
    project = project_service.get_owned_project(db, project_id, user)
    return JobOut.model_validate(job_service.get_owned_job(db, job_id, project))


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobOut,
    dependencies=[CSRFProtected],
    summary="Cancel a job",
)
def cancel_job(project_id: str, job_id: str, user: CurrentUser, db: DbSession) -> JobOut:
    """Request cancellation.

    A queued job is cancelled at once. A running job stops at its next stage
    boundary, so no half-written result is stored.
    """
    project = project_service.get_owned_project(db, project_id, user)
    job = job_service.get_owned_job(db, job_id, project)
    job_service.request_cancel(db, job)
    db.commit()
    return JobOut.model_validate(job)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CSRFProtected, JobRateLimit],
    summary="Retry a failed or cancelled job",
)
def retry_job(project_id: str, job_id: str, user: CurrentUser, db: DbSession) -> JobOut:
    from ..queue import (
        TASK_TIMELAPSE_ANALYZE,
        TASK_TIMELAPSE_PREVIEW,
        TASK_TIMELAPSE_RENDER,
    )

    project = project_service.get_owned_project(db, project_id, user)
    job = job_service.get_owned_job(db, job_id, project)
    job_service.prepare_retry(db, job)
    db.commit()

    task_name = {
        "cleanup": TASK_CLEANUP,
        "timelapse_analyze": TASK_TIMELAPSE_ANALYZE,
        "timelapse_preview": TASK_TIMELAPSE_PREVIEW,
        "timelapse_render": TASK_TIMELAPSE_RENDER,
    }.get(job.job_type)
    if task_name is None:
        raise validation_error(f"Jobs of type '{job.job_type}' cannot be retried.")

    job_service.dispatch(job, task_name)
    db.commit()
    db.refresh(job)
    return JobOut.model_validate(job)


def _job_snapshot(job_id: str, project_id: str) -> dict | None:
    """Read job state on a short-lived session (used by the SSE loop)."""
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None or job.project_id != project_id:
            return None
        return {
            "job_id": job.id,
            "status": job.status,
            "progress": round(float(job.progress), 4),
            "message": job.progress_message,
            "result": job.result if job.is_terminal else None,
            "error_code": job.error_code,
            "error_message": job.error_message,
        }


@router.get(
    "/jobs/{job_id}/events",
    dependencies=[DefaultRateLimit],
    summary="Stream job progress (Server-Sent Events)",
    response_class=StreamingResponse,
)
async def stream_job_events(
    project_id: str, job_id: str, request: Request, user: CurrentUser, db: DbSession
) -> StreamingResponse:
    """Server-Sent Events carrying progress until the job reaches a terminal state.

    Each message is a ``JobProgressEvent``. The stream closes as soon as the job
    finishes, when the client disconnects, or after the server-side cap.
    """
    project = project_service.get_owned_project(db, project_id, user)
    job_service.get_owned_job(db, job_id, project)  # authorization only

    async def event_stream():
        elapsed = 0.0
        last_payload: str | None = None
        # Tell EventSource not to reconnect faster than the poll interval.
        yield "retry: 2000\n\n"
        while elapsed < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            snapshot = await run_in_threadpool(_job_snapshot, job_id, project_id)
            if snapshot is None:
                yield f"event: error\ndata: {json.dumps({'code': 'not_found'})}\n\n"
                return
            payload = json.dumps(snapshot)
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if snapshot["status"] in ("succeeded", "failed", "cancelled"):
                yield f"event: done\ndata: {payload}\n\n"
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)
            elapsed += STREAM_POLL_SECONDS
        yield f"event: timeout\ndata: {json.dumps({'job_id': job_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
