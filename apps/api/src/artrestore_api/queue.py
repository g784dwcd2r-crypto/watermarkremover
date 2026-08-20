"""The shared Celery application.

Defined here rather than in the worker so the API can enqueue by task *name*
without importing worker code (and its heavy imaging dependencies). The worker
imports this same app object and registers the task implementations onto it.
"""

from __future__ import annotations

from celery import Celery

from .config import get_settings

TASK_CLEANUP = "artrestore.cleanup.run"
TASK_TIMELAPSE_ANALYZE = "artrestore.timelapse.analyze"
TASK_TIMELAPSE_PREVIEW = "artrestore.timelapse.preview"
TASK_TIMELAPSE_RENDER = "artrestore.timelapse.render"
TASK_RETENTION_SWEEP = "artrestore.retention.sweep"

_app: Celery | None = None


def get_celery_app() -> Celery:
    global _app
    if _app is None:
        settings = get_settings()
        app = Celery("artrestore")
        app.conf.update(
            broker_url=settings.celery_broker_url,
            result_backend=settings.celery_result_backend,
            task_always_eager=settings.celery_task_always_eager,
            task_eager_propagates=True,
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_acks_late=True,
            worker_prefetch_multiplier=1,
            task_track_started=True,
            broker_connection_retry_on_startup=True,
            result_expires=3600,
            beat_schedule={
                "retention-sweep": {
                    "task": TASK_RETENTION_SWEEP,
                    "schedule": max(60, settings.retention_sweep_minutes * 60),
                }
            },
        )
        _app = app
    return _app


def reset_celery_app() -> None:
    global _app
    _app = None
