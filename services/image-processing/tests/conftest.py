"""Shared fixtures built from the procedurally generated demo assets."""

from __future__ import annotations

import io

import numpy as np
import pytest
from artrestore_imaging import demo
from PIL import Image


@pytest.fixture(scope="session")
def flat_background() -> np.ndarray:
    return demo.flat_gradient(480, 360)


@pytest.fixture(scope="session")
def woven_texture() -> np.ndarray:
    return demo.woven_texture(480, 360)


@pytest.fixture(scope="session")
def painting() -> np.ndarray:
    return demo.painted_illustration(560, 400)


@pytest.fixture(scope="session")
def line_art() -> np.ndarray:
    return demo.line_artwork(400, 400)


@pytest.fixture
def png_bytes():
    def _encode(rgb: np.ndarray, alpha: np.ndarray | None = None) -> bytes:
        return demo.to_png(rgb, alpha)

    return _encode


@pytest.fixture
def jpeg_bytes():
    def _encode(rgb: np.ndarray, quality: int = 92) -> bytes:
        return demo.to_jpeg(rgb, quality)

    return _encode


def _mean_abs_error(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean absolute pixel error, optionally restricted to a mask."""
    difference = np.abs(a.astype(np.float64) - b.astype(np.float64))
    if mask is not None:
        selection = mask > 0
        if not selection.any():
            return 0.0
        return float(difference[selection].mean())
    return float(difference.mean())


@pytest.fixture(scope="session")
def mean_abs_error():
    """Exposed as a fixture so no test module has to import ``conftest``.

    Importing conftest by name breaks as soon as two suites in the monorepo are
    collected in one run, because both files claim the same module name.
    """
    return _mean_abs_error


def encode(image: Image.Image, fmt: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()
