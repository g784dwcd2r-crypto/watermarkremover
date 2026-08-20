"""Scheduled retention sweep."""

from __future__ import annotations

import logging

from artrestore_api.db import session_scope
from artrestore_api.queue import TASK_RETENTION_SWEEP, get_celery_app
from artrestore_api.services import retention as retention_service
from artrestore_api.storage import get_storage

logger = logging.getLogger(__name__)

celery_app = get_celery_app()


@celery_app.task(name=TASK_RETENTION_SWEEP)
def sweep_expired() -> dict:
    """Delete projects whose retention window has closed, and their bytes."""
    storage = get_storage()
    with session_scope() as session:
        return retention_service.sweep(session, storage)
