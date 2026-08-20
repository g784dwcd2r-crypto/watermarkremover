"""Celery task implementations.

Importing this package registers every task on the shared Celery application.
"""

from . import cleanup  # noqa: F401
from . import retention  # noqa: F401

try:  # the timelapse tasks arrive with the renderer service
    from . import timelapse  # noqa: F401
except ImportError:  # pragma: no cover
    pass
