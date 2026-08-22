"""Fixtures for the renderer tests."""

from __future__ import annotations

import math
import struct
import wave

import numpy as np
import pytest

from artrestore_imaging import demo
from artrestore_timelapse import analyse_artwork

@pytest.fixture(scope="session")
def artwork() -> np.ndarray:
    return demo.painted_illustration(420, 320)


@pytest.fixture(scope="session")
def analysis(artwork):
    return analyse_artwork(artwork, seed=1234)


@pytest.fixture(scope="session")
def line_art() -> np.ndarray:
    return demo.line_artwork(320, 320)


@pytest.fixture
def audio_file(tmp_path):
    """A short original tone, so the audio path is exercised with real bytes."""
    path = tmp_path / "tone.wav"
    sample_rate = 22_050
    seconds = 12
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate * seconds):
            value = int(12_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))
    return str(path)
