"""Typed errors raised by the imaging package.

Every error carries a machine-readable ``code`` so the API layer can map it to a
stable error contract without string matching.
"""

from __future__ import annotations


class ImagingError(Exception):
    """Base class for every error raised by this package."""

    code = "imaging_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class UnsupportedFormatError(ImagingError):
    """The uploaded bytes are not one of the supported image formats."""

    code = "unsupported_format"


class CorruptImageError(ImagingError):
    """The bytes claim to be an image but cannot be decoded safely."""

    code = "corrupt_image"


class ImageTooLargeError(ImagingError):
    """The image exceeds the configured byte or pixel budget."""

    code = "image_too_large"


class MaskError(ImagingError):
    """The supplied mask is empty, mis-shaped, or otherwise unusable."""

    code = "invalid_mask"


class ProtectedRegionError(ImagingError):
    """The mask overlaps a region the product refuses to remove.

    Raised for artist signatures, copyright lines, stock-agency watermarks and
    provenance labels. ``details['regions']`` lists the offending detections.
    """

    code = "protected_region"


class ProtectedRegionReviewError(ProtectedRegionError):
    """The mask overlaps content that *may* be attribution.

    Distinct from :class:`ProtectedRegionError` because the user can resolve it:
    a date stamp in a bottom corner has the same geometry as a credit line, so
    the product pauses and asks for an explicit attestation instead of guessing.
    """

    code = "protected_region_review"


class InpaintBackendUnavailableError(ImagingError):
    """A requested inpainting backend is not installed or not configured."""

    code = "inpaint_backend_unavailable"


class JobCancelledError(ImagingError):
    """Cooperative cancellation was requested while a pipeline was running."""

    code = "job_cancelled"
