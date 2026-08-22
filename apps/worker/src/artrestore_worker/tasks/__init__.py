"""Celery task implementations.

Importing this package registers every task on the shared Celery application.
"""

import contextlib

from . import (
    cleanup,  # noqa: F401
    retention,  # noqa: F401
)

with contextlib.suppress(ImportError):  # the renderer service is optional
    from . import timelapse  # noqa: F401
