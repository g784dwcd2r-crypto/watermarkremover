"""Job lifecycle: dispatch, terminal states, cancellation, retry and replay."""

from __future__ import annotations

import pytest
from artrestore_api.db import session_scope
from artrestore_api.errors import APIError
from artrestore_api.models import ProcessingJob, Project
from artrestore_api.services import jobs as job_service


def _job(job_id: str) -> ProcessingJob:
    with session_scope() as session:
        row = session.get(ProcessingJob, job_id)
        session.expunge(row)
        return row


def test_create_job_marks_the_project_processing(project):
    project_id, _ = project
    with session_scope() as session:
        created, is_new = job_service.create_job(
            session,
            project=session.get(Project, project_id),
            job_type="cleanup",
            parameters={"mode": "fast_fill"},
        )
        assert is_new is True
        assert created.status == "queued"
        assert session.get(Project, project_id).status == "processing"


def test_a_second_job_of_the_same_type_is_refused(project):
    project_id, _ = project
    with session_scope() as session:
        row = session.get(Project, project_id)
        job_service.create_job(session, project=row, job_type="cleanup", parameters={})
        with pytest.raises(APIError) as excinfo:
            job_service.create_job(session, project=row, job_type="cleanup", parameters={})
    assert excinfo.value.code == "job_in_progress"


def test_the_same_idempotency_key_returns_the_original(project):
    project_id, _ = project
    with session_scope() as session:
        row = session.get(Project, project_id)
        first, first_new = job_service.create_job(
            session, project=row, job_type="cleanup", parameters={}, idempotency_key="abc"
        )
        second, second_new = job_service.create_job(
            session, project=row, job_type="cleanup", parameters={}, idempotency_key="abc"
        )
    assert first.id == second.id
    assert (first_new, second_new) == (True, False)


def test_success_marks_the_project_complete(job, project):
    project_id, _ = project
    with session_scope() as session:
        job_service.mark_succeeded(session, session.get(ProcessingJob, job), {"ok": True})

    assert _job(job).status == "succeeded"
    assert _job(job).progress == pytest.approx(1.0)
    with session_scope() as session:
        assert session.get(Project, project_id).status == "complete"


def test_failure_records_a_code_and_message(job):
    with session_scope() as session:
        job_service.mark_failed(
            session, session.get(ProcessingJob, job), code="protected_region", message="Blocked."
        )
    row = _job(job)
    assert row.status == "failed"
    assert row.error_code == "protected_region"
    assert row.completed_at is not None


def test_a_queued_job_cancels_immediately(job):
    with session_scope() as session:
        job_service.request_cancel(session, session.get(ProcessingJob, job))
    assert _job(job).status == "cancelled"


def test_a_running_job_is_asked_to_stop_rather_than_killed(job):
    """Cancellation is cooperative, so no half-written result is left behind."""
    with session_scope() as session:
        row = session.get(ProcessingJob, job)
        job_service.mark_running(session, row)
        job_service.request_cancel(session, row)

    row = _job(job)
    assert row.status == "running"
    assert row.cancel_requested is True


def test_a_finished_job_cannot_be_cancelled(job):
    with session_scope() as session:
        row = session.get(ProcessingJob, job)
        job_service.mark_succeeded(session, row, {})
        with pytest.raises(APIError) as excinfo:
            job_service.request_cancel(session, row)
    assert excinfo.value.code == "job_not_cancellable"


def test_retry_resets_the_row_and_counts_the_attempt(job):
    with session_scope() as session:
        row = session.get(ProcessingJob, job)
        job_service.mark_failed(session, row, code="internal_error", message="boom")
        job_service.prepare_retry(session, row)

    row = _job(job)
    assert row.status == "queued"
    assert row.attempt == 2
    assert row.error_code is None
    assert row.completed_at is None


def test_only_failed_or_cancelled_jobs_can_be_retried(job):
    with session_scope() as session:
        row = session.get(ProcessingJob, job)
        job_service.mark_running(session, row)
        with pytest.raises(APIError) as excinfo:
            job_service.prepare_retry(session, row)
    assert excinfo.value.code == "job_not_retryable"


def test_a_redelivered_finished_job_is_not_run_again(job):
    """The broker can redeliver; the task must treat that as a no-op."""
    from artrestore_worker.tasks.cleanup import run_cleanup_task

    with session_scope() as session:
        job_service.mark_succeeded(session, session.get(ProcessingJob, job), {"first": True})

    result = run_cleanup_task.run(job_id=job)
    assert result["status"] == "already_complete"
    assert _job(job).result == {"first": True}


def test_a_cancelled_job_is_not_started(job):
    from artrestore_worker.tasks.cleanup import run_cleanup_task

    with session_scope() as session:
        session.get(ProcessingJob, job).cancel_requested = True

    assert run_cleanup_task.run(job_id=job)["status"] == "cancelled"
    assert _job(job).status == "cancelled"


def test_an_unknown_job_id_is_handled(job):
    from artrestore_worker.tasks.cleanup import run_cleanup_task

    assert run_cleanup_task.run(job_id="00000000-0000-4000-8000-000000000000") == {
        "status": "unknown_job"
    }


def test_a_project_without_a_source_fails_cleanly(job):
    from artrestore_worker.tasks.cleanup import run_cleanup_task

    result = run_cleanup_task.run(job_id=job)
    assert result["status"] == "failed"
    assert _job(job).status == "failed"
    assert "source" in (_job(job).error_message or "").lower()
