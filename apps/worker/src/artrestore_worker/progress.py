"""Progress reporting from inside a task.

Progress is written to the job row rather than pushed anywhere: the API's SSE
stream reads the same row, so a client that reconnects mid-job immediately sees
current state instead of waiting for the next event.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from artrestore_api.db import session_scope
from artrestore_api.models import ProcessingJob

#: Minimum seconds between database writes. Progress callbacks fire far more
#: often than a user can perceive; throttling keeps a long render from turning
#: into thousands of transactions.
MIN_WRITE_INTERVAL = 0.4


@dataclass
class ProgressReporter:
    """Throttled writer with a cached cancellation flag."""

    job_id: str
    floor: float = 0.0
    ceiling: float = 1.0
    _last_write: float = field(default=0.0, init=False)
    _last_cancel_check: float = field(default=0.0, init=False)
    _cancelled: bool = field(default=False, init=False)

    def scaled(self, fraction: float) -> float:
        span = max(0.0, self.ceiling - self.floor)
        return self.floor + max(0.0, min(1.0, fraction)) * span

    def __call__(self, fraction: float, message: str) -> None:
        self.report(fraction, message)

    def report(self, fraction: float, message: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_write) < MIN_WRITE_INTERVAL:
            return
        self._last_write = now
        value = self.scaled(fraction)
        with session_scope() as session:
            job = session.get(ProcessingJob, self.job_id)
            if job is None or job.is_terminal:
                return
            job.progress = value
            job.progress_message = message[:256]

    def stage(self, floor: float, ceiling: float) -> ProgressReporter:
        """A reporter that maps 0..1 onto a sub-range of the overall job."""
        child = ProgressReporter(self.job_id, floor=floor, ceiling=ceiling)
        return child

    def should_cancel(self) -> bool:
        """Cooperative cancellation, re-read at most once a second."""
        now = time.monotonic()
        if self._cancelled:
            return True
        if (now - self._last_cancel_check) < 1.0:
            return False
        self._last_cancel_check = now
        with session_scope() as session:
            job = session.get(ProcessingJob, self.job_id)
            self._cancelled = bool(job and job.cancel_requested)
        return self._cancelled
