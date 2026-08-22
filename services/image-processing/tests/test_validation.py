"""Upload validation: format sniffing, limits and hostile inputs."""

from __future__ import annotations

import io

import numpy as np
import pytest
from artrestore_imaging.errors import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedFormatError,
)
from artrestore_imaging.validation import (
    estimated_output_bytes,
    sniff_mime,
    validate_image_bytes,
)
from PIL import Image


def test_accepts_png(flat_background, png_bytes):
    result = validate_image_bytes(png_bytes(flat_background))
    assert result.mime_type == "image/png"
    assert (result.width, result.height) == (480, 360)
    assert result.color_mode == "RGB"
    assert result.has_alpha is False


def test_accepts_jpeg_webp_and_tiff(flat_background):
    image = Image.fromarray(flat_background)
    for fmt, mime in (("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("TIFF", "image/tiff")):
        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        assert validate_image_bytes(buffer.getvalue()).mime_type == mime


def test_detects_alpha_channel(png_bytes):
    from artrestore_imaging import demo

    rgb, alpha = demo.alpha_sticker(120)
    result = validate_image_bytes(png_bytes(rgb, alpha))
    assert result.has_alpha is True


def test_rejects_empty_upload():
    with pytest.raises(CorruptImageError):
        validate_image_bytes(b"")


def test_rejects_non_image_payload():
    with pytest.raises(UnsupportedFormatError):
        validate_image_bytes(b"<?php system($_GET['cmd']); ?>" * 50)


def test_rejects_svg_disguised_as_image():
    payload = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    with pytest.raises(UnsupportedFormatError):
        validate_image_bytes(payload, declared_mime="image/png")


def test_rejects_declared_mime_that_lies(flat_background, png_bytes):
    """A PNG declared as JPEG is still validated as a PNG, never as its claim."""
    result = validate_image_bytes(png_bytes(flat_background), declared_mime="image/jpeg")
    assert result.mime_type == "image/png"


def test_rejects_polyglot_with_forged_signature(flat_background, png_bytes):
    """A JPEG signature glued to PNG data must not pass."""
    body = png_bytes(flat_background)
    forged = b"\xff\xd8\xff" + body[3:]
    with pytest.raises((UnsupportedFormatError, CorruptImageError)):
        validate_image_bytes(forged)


def test_rejects_truncated_image(flat_background, png_bytes):
    body = png_bytes(flat_background)
    with pytest.raises((CorruptImageError, UnsupportedFormatError)):
        validate_image_bytes(body[: len(body) // 3])


def test_rejects_gif(flat_background):
    buffer = io.BytesIO()
    Image.fromarray(flat_background).save(buffer, format="GIF")
    with pytest.raises(UnsupportedFormatError):
        validate_image_bytes(buffer.getvalue())


def test_enforces_byte_budget(flat_background, png_bytes):
    with pytest.raises(ImageTooLargeError):
        validate_image_bytes(png_bytes(flat_background), max_bytes=1024)


def test_enforces_pixel_budget(flat_background, png_bytes):
    with pytest.raises(ImageTooLargeError):
        validate_image_bytes(png_bytes(flat_background), max_pixels=1000)


def test_large_image_within_budget(png_bytes):
    large = np.zeros((2200, 3000, 3), dtype=np.uint8)
    large[:, :, 1] = 90
    result = validate_image_bytes(png_bytes(large), max_pixels=50_000_000)
    assert result.megapixels == pytest.approx(6.6, abs=0.05)


def test_sniff_mime_signatures():
    assert sniff_mime(b"\x89PNG\r\n\x1a\n rest") == "image/png"
    assert sniff_mime(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert sniff_mime(b"RIFF____WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"II*\x00") == "image/tiff"
    assert sniff_mime(b"not-an-image") is None


def test_output_size_estimate_is_positive(flat_background, png_bytes):
    result = validate_image_bytes(png_bytes(flat_background))
    assert estimated_output_bytes(result) > 0
