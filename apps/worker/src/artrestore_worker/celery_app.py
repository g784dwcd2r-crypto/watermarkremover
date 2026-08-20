"""Worker entrypoint.

Run with::

    celery -A artrestore_worker.celery_app:app worker --loglevel=info
    celery -A artrestore_worker.celery_app:app beat --loglevel=info
"""

from __future__ import annotations

from artrestore_api.config import get_settings
from artrestore_api.logging_setup import configure_logging
from artrestore_api.queue import get_celery_app

configure_logging(get_settings().log_level)

app = get_celery_app()

# Importing the task package registers every task on ``app``.
from . import tasks  # noqa: E402,F401

__all__ = ["app"]
