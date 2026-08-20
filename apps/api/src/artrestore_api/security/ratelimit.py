"""Fixed-window rate limiting.

Redis-backed when a Redis URL is reachable so limits hold across API replicas;
otherwise an in-process fallback keeps single-node development and the test
suite working. The fallback is intentionally not silent: it is reported by the
readiness probe.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    reset_after: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_after),
        }


class RateLimiter:
    """Counts requests per key per fixed window."""

    def __init__(self, redis_url: str | None = None, *, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._local: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()
        self._redis = None
        self.backend = "memory"
        if redis_url:
            try:  # pragma: no cover - exercised only with a live Redis
                import redis

                client = redis.Redis.from_url(redis_url, socket_connect_timeout=0.5)
                client.ping()
                self._redis = client
                self.backend = "redis"
            except Exception:  # noqa: BLE001
                self._redis = None

    def check(self, key: str, limit: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=True, remaining=limit, limit=limit, reset_after=0)

        window = int(time.time()) // self.window_seconds
        bucket = f"ratelimit:{key}:{window}"
        reset_after = self.window_seconds - int(time.time()) % self.window_seconds

        if self._redis is not None:  # pragma: no cover - requires Redis
            try:
                pipeline = self._redis.pipeline()
                pipeline.incr(bucket, 1)
                pipeline.expire(bucket, self.window_seconds + 1)
                count = int(pipeline.execute()[0])
            except Exception:  # noqa: BLE001 - fall back rather than fail open loudly
                count = self._increment_local(bucket)
        else:
            count = self._increment_local(bucket)

        return RateLimitResult(
            allowed=count <= limit,
            remaining=limit - count,
            limit=limit,
            reset_after=reset_after,
        )

    def _increment_local(self, bucket: str) -> int:
        now = time.time()
        with self._lock:
            self._prune(now)
            count, _ = self._local.get(bucket, (0, now + self.window_seconds))
            count += 1
            self._local[bucket] = (count, now + self.window_seconds)
            return count

    def _prune(self, now: float) -> None:
        expired = [key for key, (_, deadline) in self._local.items() if deadline < now]
        for key in expired:
            self._local.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._local.clear()


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        from ..config import get_settings

        settings = get_settings()
        _limiter = RateLimiter(settings.redis_url if settings.rate_limit_enabled else None)
    return _limiter


def reset_rate_limiter() -> None:
    global _limiter
    if _limiter is not None:
        _limiter.reset()
    _limiter = None
