"""Processing-job lifecycle.

Jobs are rows first and queue messages second. The API creates the row, then
dispatches by task name; the worker updates the same row. That ordering makes
progress readable without the broker, makes cancellation a database write, and
makes idempotency a unique constraint rather than a race.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, not_found
from ..logging_setup import log_context
from ..models import ProcessingJob, Project
from ..queue import get_celery_app

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def get_owned_job(db: Session, job_id: str, project: Project) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.project_id != project.id:
        raise not_found("That job does not exist.")
    return job


def find_by_idempotency_key(
    db: Session, *, project_id: str, key: str | None
) -> ProcessingJob | None:
    if not key:
        return None
    return db.execute(
        select(ProcessingJob).where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.idempotency_key == key,
        )
    ).scalar_one_or_none()


def create_job(
    db: Session,
    *,
    project: Project,
    job_type: str,
    parameters: dict,
    idempotency_key: str | None = None,
    allow_concurrent: bool = False,
) -> tuple[ProcessingJob, bool]:
    """Create a job row. Returns ``(job, created)``.

    Repeating a request with the same idempotency key returns the original job
    instead of queueing the same work twice.
    """
    existing = find_by_idempotency_key(db, project_id=project.id, key=idempotency_key)
    if existing is not None:
        return existing, False

    if not allow_concurrent:
        running = (
            db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.project_id == project.id,
                    ProcessingJob.job_type == job_type,
                    ProcessingJob.status.in_(("queued", "running")),
                )
            )
            .scalars()
            .first()
        )
        if running is not None:
            raise conflict(
                "job_in_progress",
                "This project already has a job of that type running. Wait for it to finish "
                "or cancel it first.",
                details={"job_id": running.id, "status": running.status},
            )

    job = ProcessingJob(
        project_id=project.id,
        job_type=job_type,
        status="queued",
        progress=0.0,
        progress_message="Queued",
        parameters=parameters,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    project.status = "processing"
    db.flush()
    return job, True


def dispatch(job: ProcessingJob, task_name: str) -> None:
    """Hand the job to the queue.

    Called after the surrounding transaction commits so the worker can never
    observe a job id that is not yet visible in the database.

    ``send_task`` addresses the worker by name, which keeps the API free of the
    worker's imaging dependencies - but Celery ignores ``task_always_eager`` for
    name-based dispatch and would try to reach a broker. In eager mode the
    registered task is therefore invoked directly, which is what lets the tests
    and a broker-less development setup run the full pipeline in process.
    """
    app = get_celery_app()
    if app.conf.task_always_eager:
        task = app.tasks.get(task_name)
        if task is None:
            raise RuntimeError(
                f"Task '{task_name}' is not registered. Import artrestore_worker.tasks "
                "before dispatching in eager mode."
            )
        async_result = task.apply(kwargs={"job_id": job.id})
    else:
        async_result = app.send_task(task_name, kwargs={"job_id": job.id})
    job.queue_task_id = getattr(async_result, "id", None)
    logger.info("job dispatched", extra=log_context(job_id=job.id, job_type=job.job_type))


def mark_running(db: Session, job: ProcessingJob) -> None:
    job.status = "running"
    job.started_at = dt.datetime.now(dt.UTC)
    job.progress_message = "Starting"
    db.flush()


def update_progress(db: Session, job: ProcessingJob, progress: float, message: str) -> None:
    job.progress = max(0.0, min(1.0, float(progress)))
    job.progress_message = message[:256]
    db.flush()


def mark_succeeded(db: Session, job: ProcessingJob, result: dict) -> None:
    job.status = "succeeded"
    job.progress = 1.0
    job.progress_message = "Complete"
    job.result = result
    job.completed_at = dt.datetime.now(dt.UTC)
    project = db.get(Project, job.project_id)
    if project is not None:
        project.status = "complete"
    db.flush()


def mark_failed(
    db: Session, job: ProcessingJob, *, code: str, message: str, result: dict | None = None
) -> None:
    job.status = "failed"
    job.error_code = code
    job.error_message = message[:2000]
    if result:
        job.result = result
    job.completed_at = dt.datetime.now(dt.UTC)
    project = db.get(Project, job.project_id)
    if project is not None:
        project.status = "failed"
    db.flush()


def mark_cancelled(db: Session, job: ProcessingJob) -> None:
    job.status = "cancelled"
    job.progress_message = "Cancelled"
    job.completed_at = dt.datetime.now(dt.UTC)
    project = db.get(Project, job.project_id)
    if project is not None:
        project.status = "ready"
    db.flush()


def request_cancel(db: Session, job: ProcessingJob) -> ProcessingJob:
    """Ask a job to stop.

    Queued jobs are cancelled immediately; running jobs get a cooperative flag
    that the pipeline checks between stages, so a partial write can never be
    left behind.
    """
    if job.status in TERMINAL_STATUSES:
        raise conflict(
            "job_not_cancellable",
            f"This job already finished with status '{job.status}'.",
            details={"status": job.status},
        )
    job.cancel_requested = True
    if job.status == "queued":
        mark_cancelled(db, job)
    db.flush()
    return job


def prepare_retry(db: Session, job: ProcessingJob) -> ProcessingJob:
    """Reset a failed or cancelled job so it can run again.

    The same row is reused, keeping the project's history to one entry per
    logical request rather than one per attempt.
    """
    if job.status not in ("failed", "cancelled"):
        raise conflict(
            "job_not_retryable",
            "Only failed or cancelled jobs can be retried.",
            details={"status": job.status},
        )
    job.status = "queued"
    job.progress = 0.0
    job.progress_message = "Queued"
    job.error_code = None
    job.error_message = None
    job.cancel_requested = False
    job.attempt += 1
    job.started_at = None
    job.completed_at = None
    db.flush()
    return job


def should_cancel(db: Session, job_id: str) -> bool:
    """Cooperative cancellation check used from inside the worker."""
    row = db.execute(
        select(ProcessingJob.cancel_requested).where(ProcessingJob.id == job_id)
    ).scalar_one_or_none()
    return bool(row)
