"""Mask rasterisation and normalisation."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from artrestore_imaging.errors import MaskError
from artrestore_imaging.masks import (
    MaskAdjustments,
    decode_mask_png,
    encode_mask_png,
    mask_components,
    mask_coverage,
    normalize_mask,
    rasterize_editor_state,
)


def _rect_state(x=10, y=10, w=40, h=20, width=200, height=120):
    return {
        "version": 1,
        "image": {"width": width, "height": height},
        "regions": [{"id": "r1", "type": "rect", "x": x, "y": y, "width": w, "height": h}],
    }


def test_rasterize_rectangle():
    mask = rasterize_editor_state(_rect_state(), 200, 120)
    assert mask.shape == (120, 200)
    assert mask[20, 30] == 255
    assert mask[100, 180] == 0


def test_rasterize_scales_to_target_resolution():
    """Editor coordinates are in preview space; the server scales them up."""
    mask = rasterize_editor_state(_rect_state(width=100, height=60), 200, 120)
    assert mask[40, 60] == 255  # (20,30) in editor space -> (40,60) at 2x


def test_brush_stroke_and_eraser():
    state = {
        "image": {"width": 100, "height": 100},
        "regions": [
            {"type": "brush", "points": [[10, 50], [90, 50]], "size": 20, "hardness": 1.0},
            {"type": "eraser", "points": [[50, 50]], "size": 10, "hardness": 1.0},
        ],
    }
    mask = rasterize_editor_state(state, 100, 100)
    assert mask[50, 20] > 200
    assert mask[50, 50] < 60


def test_polygon_and_lasso():
    state = {
        "image": {"width": 100, "height": 100},
        "regions": [{"type": "polygon", "points": [[10, 10], [90, 10], [50, 80]]}],
    }
    mask = rasterize_editor_state(state, 100, 100)
    assert mask[20, 50] == 255
    assert mask[90, 10] == 0


def test_subtract_mode():
    state = {
        "image": {"width": 100, "height": 100},
        "regions": [
            {"type": "rect", "x": 0, "y": 0, "width": 100, "height": 100},
            {"type": "rect", "x": 40, "y": 40, "width": 20, "height": 20, "mode": "subtract"},
        ],
    }
    mask = rasterize_editor_state(state, 100, 100)
    assert mask[10, 10] == 255
    assert mask[50, 50] == 0


def test_too_many_regions_rejected():
    state = {"image": {"width": 10, "height": 10}, "regions": [{"type": "rect"}] * 100}
    with pytest.raises(MaskError):
        rasterize_editor_state(state, 10, 10)


def test_normalize_expand_and_contract():
    raw = np.zeros((100, 100), np.uint8)
    raw[40:60, 40:60] = 255

    grown, _ = normalize_mask(raw, MaskAdjustments(expand=5, feather=0))
    shrunk, _ = normalize_mask(raw, MaskAdjustments(expand=-5, feather=0))
    assert (grown > 0).sum() > (raw > 0).sum()
    assert (shrunk > 0).sum() < (raw > 0).sum()


def test_normalize_feather_produces_soft_edge():
    raw = np.zeros((100, 100), np.uint8)
    raw[40:60, 40:60] = 255
    binary, soft = normalize_mask(raw, MaskAdjustments(feather=6))
    edge_values = soft[39, 40:60]
    assert binary[39, 50] == 0
    assert 0 < edge_values.max() < 255


def test_empty_mask_rejected():
    with pytest.raises(MaskError):
        normalize_mask(np.zeros((50, 50), np.uint8))


def test_non_2d_mask_rejected():
    with pytest.raises(MaskError):
        normalize_mask(np.zeros((10, 10, 3), np.uint8))


def test_components_and_coverage():
    raw = np.zeros((100, 100), np.uint8)
    raw[10:20, 10:20] = 255
    raw[60:70, 60:90] = 255
    binary, _ = normalize_mask(raw, MaskAdjustments(feather=0))
    components = mask_components(binary)
    assert len(components) == 2
    assert components[0]["area"] > components[1]["area"]
    assert 0.03 < mask_coverage(binary) < 0.05


def test_mask_png_roundtrip():
    raw = np.zeros((60, 80), np.uint8)
    cv2.circle(raw, (40, 30), 15, 255, -1)
    decoded = decode_mask_png(encode_mask_png(raw), 80, 60)
    assert decoded.shape == (60, 80)
    assert decoded[30, 40] == 255


def test_mask_png_resized_to_image_dimensions():
    raw = np.zeros((30, 40), np.uint8)
    raw[10:20, 10:20] = 255
    decoded = decode_mask_png(encode_mask_png(raw), 80, 60)
    assert decoded.shape == (60, 80)
