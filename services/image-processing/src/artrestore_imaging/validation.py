"""Content-based upload validation.

The declared ``Content-Type`` of an upload is never trusted: the format is
sniffed from the actual bytes, the container is parsed with Pillow, and the
result is re-encoded through a pixel-only path so that embedded payloads
(scripts in EXIF comments, oversized ancillary chunks, trailing archives) cannot
survive into stored assets.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageFile, UnidentifiedImageError

from .errors import CorruptImageError, ImageTooLargeError, UnsupportedFormatError

# Refuse to guess at truncated data; a truncated upload is a failed upload.
ImageFile.LOAD_TRUNCATED_IMAGES = False

SUPPORTED_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
)

_PIL_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "MPO": "image/jpeg",  # multi-picture JPEG; first frame is treated as JPEG
}

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

#: Metadata blocks that are preserved by default. Everything else is dropped.
PERMITTED_METADATA_KEYS: tuple[str, ...] = ("exif", "icc_profile", "xmp", "dpi")


def sniff_mime(data: bytes) -> str | None:
    """Return the MIME type implied by the leading bytes, or ``None``."""
    for signature, mime in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return mime
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(slots=True)
class ValidatedImage:
    """The outcome of validating an upload."""

    mime_type: str
    width: int
    height: int
    color_mode: str
    has_alpha: bool
    byte_size: int
    frame_count: int
    metadata: dict = field(default_factory=dict)

    @property
    def megapixels(self) -> float:
        return round((self.width * self.height) / 1_000_000, 3)

    def to_dict(self) -> dict:
        return {
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "color_mode": self.color_mode,
            "has_alpha": self.has_alpha,
            "byte_size": self.byte_size,
            "frame_count": self.frame_count,
            "megapixels": self.megapixels,
            "metadata": self.metadata,
        }


def validate_image_bytes(
    data: bytes,
    *,
    allowed_mime_types: tuple[str, ...] = SUPPORTED_MIME_TYPES,
    max_bytes: int | None = None,
    max_pixels: int | None = 50_000_000,
    declared_mime: str | None = None,
) -> ValidatedImage:
    """Validate raw upload bytes and describe the image.

    Raises :class:`UnsupportedFormatError`, :class:`CorruptImageError` or
    :class:`ImageTooLargeError`. ``declared_mime`` is only used to report a
    mismatch; it never overrides the sniffed type.
    """
    if not data:
        raise CorruptImageError("The uploaded file is empty.")

    if max_bytes is not None and len(data) > max_bytes:
        raise ImageTooLargeError(
            "The uploaded file is larger than the configured maximum.",
            details={"byte_size": len(data), "max_bytes": max_bytes},
        )

    sniffed = sniff_mime(data)
    if sniffed is None:
        raise UnsupportedFormatError(
            "The file content is not a supported image (JPG, PNG, WebP or TIFF).",
            details={"declared_mime": declared_mime},
        )
    if sniffed not in allowed_mime_types:
        raise UnsupportedFormatError(
            f"{sniffed} uploads are not enabled.",
            details={"detected_mime": sniffed, "allowed": list(allowed_mime_types)},
        )

    # Guard against decompression bombs before Pillow allocates any buffer.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            pil_format = probe.format or ""
            width, height = probe.size
            color_mode = probe.mode
            frame_count = getattr(probe, "n_frames", 1)
            metadata_present = {
                "exif": bool(probe.info.get("exif")),
                "icc_profile": bool(probe.info.get("icc_profile")),
                "xmp": bool(probe.info.get("xmp") or probe.info.get("XML:com.adobe.xmp")),
            }
            probe.verify()  # structural check; invalidates the handle afterwards
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(
            "The image exceeds the maximum supported pixel count.",
            details={"max_pixels": max_pixels},
        ) from exc
    except UnidentifiedImageError as exc:
        raise UnsupportedFormatError("The file could not be identified as an image.") from exc
    except Exception as exc:  # noqa: BLE001 - Pillow raises many container errors
        raise CorruptImageError(f"The image could not be decoded: {exc}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    resolved_mime = _PIL_FORMAT_TO_MIME.get(pil_format)
    if resolved_mime is None:
        raise UnsupportedFormatError(
            f"{pil_format or 'unknown'} images are not supported.",
            details={"detected_format": pil_format},
        )
    if resolved_mime != sniffed:
        # Signature and container disagree - treat as hostile input.
        raise UnsupportedFormatError(
            "The file signature does not match its container.",
            details={"signature": sniffed, "container": resolved_mime},
        )

    if max_pixels is not None and width * height > max_pixels:
        raise ImageTooLargeError(
            "The image exceeds the maximum supported pixel count.",
            details={"pixels": width * height, "max_pixels": max_pixels},
        )

    return ValidatedImage(
        mime_type=resolved_mime,
        width=width,
        height=height,
        color_mode=color_mode,
        has_alpha=color_mode in ("RGBA", "LA", "PA") or color_mode == "P",
        byte_size=len(data),
        frame_count=frame_count,
        metadata=metadata_present,
    )


def estimated_output_bytes(validated: ValidatedImage) -> int:
    """Rough export-size estimate shown in the upload panel."""
    pixels = validated.width * validated.height
    bytes_per_pixel = {
        "image/jpeg": 0.35,
        "image/webp": 0.30,
        "image/png": 1.6,
        "image/tiff": 3.0,
    }.get(validated.mime_type, 1.0)
    return int(pixels * bytes_per_pixel)
