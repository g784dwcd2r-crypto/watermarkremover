"""A single error contract for the whole API.

Every failure the client can act on is an ``APIError`` with a stable ``code``.
The frontend switches on the code - never on the message - so wording can change
without breaking behaviour.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse


class APIError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message, "details": self.details}},
        )


def unauthorized(message: str = "Sign in to continue.") -> APIError:
    return APIError("unauthorized", message, status_code=status.HTTP_401_UNAUTHORIZED)


def forbidden(message: str = "You do not have access to this resource.") -> APIError:
    return APIError("forbidden", message, status_code=status.HTTP_403_FORBIDDEN)


def not_found(message: str = "Not found.") -> APIError:
    return APIError("not_found", message, status_code=status.HTTP_404_NOT_FOUND)


def conflict(code: str, message: str, details: dict | None = None) -> APIError:
    return APIError(code, message, status_code=status.HTTP_409_CONFLICT, details=details)


def validation_error(message: str, details: dict | None = None) -> APIError:
    return APIError(
        "validation_error",
        message,
        status_code=422,
        details=details,
    )


def rate_limited(message: str, reset_after: int) -> APIError:
    return APIError(
        "rate_limited",
        message,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        details={"reset_after_seconds": reset_after},
    )


def consent_required(message: str, details: dict | None = None) -> APIError:
    """The ownership attestation has not been recorded for this project."""
    return APIError(
        "consent_required",
        message,
        status_code=status.HTTP_403_FORBIDDEN,
        details=details,
    )


def protected_region(message: str, details: dict | None = None) -> APIError:
    """The mask overlaps attribution or provenance content."""
    return APIError(
        "protected_region",
        message,
        status_code=422,
        details=details,
    )


def protected_region_review(message: str, details: dict | None = None) -> APIError:
    """The mask overlaps ambiguous content; an attestation can clear it."""
    return APIError(
        "protected_region_review",
        message,
        status_code=status.HTTP_409_CONFLICT,
        details=details,
    )


async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    return exc.to_response()
