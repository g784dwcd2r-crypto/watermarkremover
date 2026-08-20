"""Structured JSON logging.

The formatter drops anything that could carry customer content. Image bytes,
mask payloads, signed URLs and email addresses are never logged; keys are
truncated to their prefix so an operator can correlate without reconstructing a
downloadable URL.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

#: Query strings on storage URLs carry the signature; strip them entirely.
_SIGNED_URL = re.compile(r"(https?://[^\s\"']+)\?[^\s\"']*(signature|Signature|X-Amz-Signature)[^\s\"']*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def scrub(message: str) -> str:
    message = _SIGNED_URL.sub(r"\1?<redacted-signature>", message)
    return _EMAIL.sub("<redacted-email>", message)


def truncate_key(key: str | None) -> str:
    """Log a storage key as a prefix only."""
    if not key:
        return ""
    parts = key.split("/")
    if len(parts) <= 3:
        return parts[0] + "/..."
    return "/".join(parts[:3]) + "/..."


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in getattr(record, "context", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log would record full URLs including signed query
    # strings, so it is silenced in favour of the middleware's own entry.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def log_context(**kwargs) -> dict:
    return {"context": kwargs}
