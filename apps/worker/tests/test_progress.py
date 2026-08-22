"""Progress reporting and cooperative cancellation."""

from __future__ import annotations

import time

import pytest
from artrestore_api.db import session_scope
from artrestore_api.models import ProcessingJob
from artrestore_worker.progress import MIN_WRITE_INTERVAL, ProgressReporter


def _read(job_id: str) -> ProcessingJob:
    with session_scope() as session:
        row = session.get(ProcessingJob, job_id)
        session.expunge(row)
        return row


def test_forced_report_writes_immediately(job):
    ProgressReporter(job).report(0.4, "Halfway", force=True)
    row = _read(job)
    assert row.progress == pytest.approx(0.4)
    assert row.progress_message == "Halfway"


def test_writes_are_throttled(job):
    """Progress callbacks fire far more often than a user can perceive."""
    reporter = ProgressReporter(job)
    reporter.report(0.1, "First", force=True)
    reporter.report(0.9, "Second")  # inside the throttle window

    assert _read(job).progress == pytest.approx(0.1)

    time.sleep(MIN_WRITE_INTERVAL + 0.05)
    reporter.report(0.9, "Second")
    assert _read(job).progress == pytest.approx(0.9)


def test_progress_is_clamped(job):
    reporter = ProgressReporter(job)
    reporter.report(5.0, "Over", force=True)
    assert _read(job).progress == pytest.approx(1.0)

    time.sleep(MIN_WRITE_INTERVAL + 0.05)
    reporter.report(-2.0, "Under", force=True)
    assert _read(job).progress == pytest.approx(0.0)


def test_message_is_truncated(job):
    ProgressReporter(job).report(0.5, "x" * 400, force=True)
    assert len(_read(job).progress_message) <= 256


def test_a_stage_reporter_maps_onto_a_sub_range(job):
    """A sub-reporter turns 0..1 of one stage into a slice of the whole job."""
    reporter = ProgressReporter(job).stage(0.4, 0.8)
    reporter.report(0.5, "Halfway through the stage", force=True)
    assert _read(job).progress == pytest.approx(0.6)


def test_terminal_jobs_are_not_written_to(job):
    """A finished job must not be dragged back to 'running' by a late callback."""
    with session_scope() as session:
        row = session.get(ProcessingJob, job)
        row.status = "succeeded"
        row.progress = 1.0

    ProgressReporter(job).report(0.2, "Late callback", force=True)
    assert _read(job).progress == pytest.approx(1.0)


def test_cancellation_is_observed(job):
    reporter = ProgressReporter(job)
    assert reporter.should_cancel() is False

    with session_scope() as session:
        session.get(ProcessingJob, job).cancel_requested = True

    # The flag is cached briefly to keep the check cheap inside a tight loop.
    time.sleep(1.05)
    assert reporter.should_cancel() is True


def test_cancellation_stays_latched(job):
    reporter = ProgressReporter(job)
    with session_scope() as session:
        session.get(ProcessingJob, job).cancel_requested = True
    time.sleep(1.05)
    assert reporter.should_cancel() is True

    with session_scope() as session:
        session.get(ProcessingJob, job).cancel_requested = False
    assert reporter.should_cancel() is True, "a cancelled run must not resume"


def test_reporting_on_a_missing_job_is_harmless(job):
    with session_scope() as session:
        session.delete(session.get(ProcessingJob, job))
    ProgressReporter(job).report(0.5, "Gone", force=True)
