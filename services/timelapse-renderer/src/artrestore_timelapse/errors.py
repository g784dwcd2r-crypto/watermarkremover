"""Errors raised by the timelapse renderer."""

from __future__ import annotations


class TimelapseError(Exception):
    code = "timelapse_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidPlanError(TimelapseError):
    """The stage plan is empty, mis-ordered or exceeds the duration limits."""

    code = "invalid_timelapse_plan"


class EncoderUnavailableError(TimelapseError):
    """FFmpeg is not installed or the requested codec is not available."""

    code = "encoder_unavailable"


class EncodingFailedError(TimelapseError):
    """The encoder ran but did not produce a usable file."""

    code = "encoding_failed"


class RenderCancelledError(TimelapseError):
    """Cooperative cancellation was requested mid-render."""

    code = "render_cancelled"
