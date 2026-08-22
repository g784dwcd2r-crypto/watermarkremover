"""Artwork analysis."""

from __future__ import annotations

import numpy as np

from artrestore_imaging import demo
from artrestore_timelapse import analyse_artwork


def test_summary_is_json_serialisable(analysis):
    import json

    payload = json.loads(json.dumps(analysis.summary()))
    assert payload["width"] > 0
    assert len(payload["palette"]) == len(payload["palette_shares"])


def test_palette_is_ordered_by_share(analysis):
    shares = analysis.palette_shares
    assert list(shares) == sorted(shares, reverse=True)
    assert abs(float(shares.sum()) - 1.0) < 1e-6


def test_layers_have_the_right_shape(analysis, artwork):
    height, width = analysis.rgb.shape[:2]
    for layer in (
        analysis.luminance,
        analysis.detail_map,
        analysis.scale_map,
        analysis.shadows,
        analysis.highlights,
        analysis.saliency,
        analysis.background_mask,
        analysis.subject_mask,
        analysis.orientation,
    ):
        assert layer.shape == (height, width)
    assert analysis.flat_colours.shape == analysis.rgb.shape


def test_masks_are_normalised(analysis):
    for layer in (analysis.shadows, analysis.highlights, analysis.saliency, analysis.detail_map):
        assert float(layer.min()) >= 0.0
        assert float(layer.max()) <= 1.0


def test_shadows_are_darker_than_highlights(analysis):
    luminance = analysis.luminance
    shadow_pixels = luminance[analysis.shadows > 0.5]
    highlight_pixels = luminance[analysis.highlights > 0.5]
    assert shadow_pixels.mean() < highlight_pixels.mean()


def test_pyramid_runs_coarse_to_fine(analysis):
    detail = []
    for level in analysis.pyramid:
        gray = level.mean(axis=2)
        detail.append(float(np.abs(np.diff(gray, axis=1)).mean()))
    assert detail[0] < detail[-1]
    assert np.array_equal(analysis.pyramid[-1], analysis.rgb)


def test_background_is_detected_from_the_frame_edges():
    """A subject on a plain field should read mostly as background."""
    import cv2

    canvas = np.full((240, 320, 3), 235, np.uint8)
    cv2.circle(canvas, (160, 120), 55, (60, 90, 140), -1)
    result = analyse_artwork(canvas, seed=2)
    assert float((result.background_mask > 0.5).mean()) > 0.5
    assert result.background_colour[0] > 200


def test_analysis_is_deterministic(artwork):
    first = analyse_artwork(artwork, seed=99)
    second = analyse_artwork(artwork, seed=99)
    assert np.array_equal(first.flat_colours, second.flat_colours)
    assert np.array_equal(first.palette, second.palette)
    assert first.summary() == second.summary()


def test_large_artwork_is_downscaled_for_analysis():
    big = demo.flat_gradient(2400, 1800)
    result = analyse_artwork(big, seed=1)
    assert max(result.rgb.shape[:2]) <= 900
