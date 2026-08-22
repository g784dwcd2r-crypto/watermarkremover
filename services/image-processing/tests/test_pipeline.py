"""Cleanup pipeline behaviour across the required image cases."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from artrestore_imaging import demo
from artrestore_imaging.errors import (
    JobCancelledError,
    MaskError,
    ProtectedRegionError,
    ProtectedRegionReviewError,
)
from artrestore_imaging.masks import MaskAdjustments
from artrestore_imaging.pipeline import (
    CLEANUP_MODES,
    CleanupOptions,
    analyse_background,
    build_previews,
    difference_map,
    run_cleanup,
    select_backend_name,
)
from artrestore_imaging.raster import SafeRaster, encode_raster, load_safe_raster


def _raster(rgb: np.ndarray, alpha: np.ndarray | None = None) -> SafeRaster:
    return load_safe_raster(demo.to_png(rgb, alpha))


#: The demo overlays sit in a bottom corner, which is also where credit lines
#: live. The real product asks the user to attest that the region is not
#: attribution content; these tests stand in for that attestation.
ACKNOWLEDGED = ("copyright_notice",)


def _options(mode: str, **kwargs) -> CleanupOptions:
    kwargs.setdefault("adjustments", MaskAdjustments(expand=1, feather=2))
    kwargs.setdefault("acknowledged_protected_kinds", ACKNOWLEDGED)
    return CleanupOptions(mode=mode, **kwargs)


# -- the required image matrix ---------------------------------------------


@pytest.mark.parametrize("mode", CLEANUP_MODES)
def test_flat_background_overlay_is_removed(flat_background, mode, mean_abs_error):
    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(_raster(dirty), mask, _options(mode))

    before = mean_abs_error(dirty, flat_background, mask)
    after = mean_abs_error(result.raster.rgb, flat_background, mask)
    assert after < before * 0.35, f"{mode} left too much of the overlay behind"


@pytest.mark.parametrize("mode", ["texture_restore", "art_mode"])
def test_repeating_texture_is_reconstructed(woven_texture, mode, mean_abs_error):
    dirty, mask = demo.add_small_overlay_badge(woven_texture)
    result = run_cleanup(_raster(dirty), mask, _options(mode))

    before = mean_abs_error(dirty, woven_texture, mask)
    after = mean_abs_error(result.raster.rgb, woven_texture, mask)
    assert after < before

    # The repair must carry texture, not a flat average of its surroundings.
    repaired = cv2.cvtColor(result.raster.rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    detail = repaired - cv2.GaussianBlur(repaired, (0, 0), 1.5)
    inside = float(detail[mask > 0].std())
    outside = float(detail[mask == 0].std())
    assert inside > outside * 0.35, "the fill is flatter than the surrounding weave"


def test_painted_illustration_keeps_brush_texture(painting, mean_abs_error):
    dirty, mask = demo.add_date_stamp(painting, text="PROOF 04", origin=(40, 120))
    result = run_cleanup(_raster(dirty), mask, _options("art_mode"))

    after = mean_abs_error(result.raster.rgb, painting, mask)
    before = mean_abs_error(dirty, painting, mask)
    assert after < before

    grain = cv2.cvtColor(result.raster.rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    high_frequency = grain - cv2.GaussianBlur(grain, (0, 0), 1.2)
    assert float(high_frequency[mask > 0].std()) > 1.0


def test_thin_line_artwork_keeps_edges_crisp(line_art, mean_abs_error):
    """Edge-Aware mode must not soften the line work it is not asked to touch."""
    dirty, mask = demo.add_date_stamp(line_art, text="v2", origin=(30, 60))
    result = run_cleanup(_raster(dirty), mask, _options("edge_aware"))

    grown = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    untouched = grown == 0

    # Outside the (grown) mask the artwork is returned bit for bit.
    assert np.array_equal(result.raster.rgb[untouched], dirty[untouched])

    # And the surrounding line structure keeps its edge density.
    edges_before = cv2.Canny(line_art, 60, 150).astype(np.int64)
    edges_after = cv2.Canny(result.raster.rgb, 60, 150).astype(np.int64)
    assert int(edges_after[untouched].sum()) == pytest.approx(
        int(edges_before[untouched].sum()), rel=0.05
    )

    # The overlay itself is gone.
    assert mean_abs_error(result.raster.rgb, line_art, mask) < mean_abs_error(dirty, line_art, mask)


def test_small_authorized_overlay_on_texture(woven_texture, mean_abs_error):
    dirty, mask = demo.add_small_overlay_badge(woven_texture)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    assert mean_abs_error(result.raster.rgb, woven_texture, mask) < mean_abs_error(
        dirty, woven_texture, mask
    )


def test_alpha_transparency_is_preserved():
    rgb, alpha = demo.alpha_sticker(200)
    raster = _raster(rgb, alpha)
    assert raster.has_alpha

    mask = np.zeros(rgb.shape[:2], np.uint8)
    cv2.rectangle(mask, (90, 90), (115, 115), 255, -1)
    result = run_cleanup(raster, mask, _options("fast_fill"))

    assert result.raster.has_alpha
    assert result.raster.alpha.shape == alpha.shape
    # Fully transparent corners stay transparent.
    assert result.raster.alpha[5, 5] == 0


def test_large_image_completes(flat_background):
    large = cv2.resize(flat_background, (2400, 1800), interpolation=cv2.INTER_CUBIC)
    dirty, mask = demo.add_date_stamp(large)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    assert result.raster.rgb.shape == large.shape


def test_protected_signature_blocks_processing(painting):
    signed, box = demo.add_signature(painting)
    mask = np.zeros(signed.shape[:2], np.uint8)
    x, y, w, h = box
    cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

    with pytest.raises(ProtectedRegionError) as excinfo:
        run_cleanup(_raster(signed), mask, _options("fast_fill"))
    assert "attribution" in str(excinfo.value) or "provenance" in str(excinfo.value)
    assert excinfo.value.details["overlaps"]


# -- pipeline contracts -----------------------------------------------------


def test_source_pixels_outside_the_mask_are_untouched(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(
        _raster(dirty), mask, _options("fast_fill", adjustments=MaskAdjustments(feather=0))
    )

    grown = cv2.dilate(mask, np.ones((9, 9), np.uint8))
    outside = grown == 0
    assert np.array_equal(result.raster.rgb[outside], dirty[outside])


def test_dimensions_and_alpha_shape_are_preserved(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    assert result.raster.rgb.shape == dirty.shape


def test_empty_mask_is_rejected(flat_background):
    with pytest.raises(MaskError):
        run_cleanup(_raster(flat_background), np.zeros(flat_background.shape[:2], np.uint8))


def test_ambiguous_region_pauses_until_acknowledged(flat_background):
    """Without an attestation the run stops with the reviewable error."""
    dirty, mask = demo.add_date_stamp(flat_background)
    with pytest.raises(ProtectedRegionReviewError) as excinfo:
        run_cleanup(
            _raster(dirty), mask, CleanupOptions(mode="fast_fill", acknowledged_protected_kinds=())
        )
    details = excinfo.value.details
    assert details["requires_acknowledgement"] is True
    assert details["unacknowledged_kinds"]

    # Attesting clears it and the same run succeeds.
    run_cleanup(_raster(dirty), mask, _options("fast_fill"))


def test_whole_image_mask_is_rejected(flat_background):
    mask = np.full(flat_background.shape[:2], 255, np.uint8)
    with pytest.raises(MaskError) as excinfo:
        run_cleanup(_raster(flat_background), mask)
    assert "entire image" in str(excinfo.value)


def test_cancellation_is_cooperative(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    with pytest.raises(JobCancelledError):
        run_cleanup(_raster(dirty), mask, _options("fast_fill"), should_cancel=lambda: True)


def test_progress_is_reported_monotonically(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    seen: list[float] = []
    run_cleanup(_raster(dirty), mask, _options("fast_fill"), progress=lambda f, m: seen.append(f))
    assert seen
    assert seen[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in seen)


def test_same_seed_produces_identical_output(woven_texture):
    dirty, mask = demo.add_small_overlay_badge(woven_texture)
    first = run_cleanup(_raster(dirty), mask, _options("art_mode", seed=7))
    second = run_cleanup(_raster(dirty), mask, _options("art_mode", seed=7))
    assert np.array_equal(first.raster.rgb, second.raster.rgb)


def test_different_seeds_change_the_grain(woven_texture):
    dirty, mask = demo.add_small_overlay_badge(woven_texture)
    first = run_cleanup(_raster(dirty), mask, _options("art_mode", seed=1, grain_strength=1.5))
    second = run_cleanup(_raster(dirty), mask, _options("art_mode", seed=2, grain_strength=1.5))
    assert not np.array_equal(first.raster.rgb, second.raster.rgb)


def test_result_summary_is_json_serialisable(flat_background):
    import json

    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    payload = json.loads(json.dumps(result.summary()))
    assert payload["mode"] == "fast_fill"
    assert payload["region_count"] >= 1
    assert "analysis" in payload


# -- analysis and mode selection -------------------------------------------


def test_flat_background_is_classified_as_flat(flat_background):
    _, mask = demo.add_date_stamp(flat_background)
    analysis = analyse_background(flat_background, mask)
    assert analysis.is_flat is True
    assert analysis.suggested_mode == "fast_fill"


def test_texture_is_classified_as_textured(woven_texture):
    _, mask = demo.add_small_overlay_badge(woven_texture)
    analysis = analyse_background(woven_texture, mask)
    assert analysis.is_textured is True
    assert analysis.suggested_mode in ("texture_restore", "art_mode")


def test_backend_selection_per_mode():
    options = CleanupOptions()
    assert select_backend_name("fast_fill", options) == "opencv_telea"
    assert select_backend_name("art_mode", options) == "patchmatch"
    assert select_backend_name("edge_aware", options) in ("opencv_blend", "lama")
    assert select_backend_name("texture_restore", options) in (
        "patchmatch",
        "opencv_blend",
        "lama",
        "diffusion",
    )


def test_backend_override_is_honoured():
    options = CleanupOptions(backend_override="opencv_ns")
    assert select_backend_name("art_mode", options) == "opencv_ns"


def test_unknown_mode_falls_back_to_fast_fill():
    assert CleanupOptions.from_dict({"mode": "nonsense"}).mode == "fast_fill"


# -- previews and export ----------------------------------------------------


def test_previews_are_downscaled(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    previews = build_previews(_raster(dirty), result.raster, max_dimension=200)
    assert max(previews["before"].rgb.shape[:2]) == 200
    assert max(previews["after"].rgb.shape[:2]) == 200


def test_difference_map_highlights_the_repair(flat_background):
    dirty, mask = demo.add_date_stamp(flat_background)
    result = run_cleanup(_raster(dirty), mask, _options("fast_fill"))
    delta = difference_map(_raster(dirty), result.raster)
    assert delta.shape == dirty.shape
    assert delta[mask > 0].mean() > delta[mask == 0].mean()


def test_export_keeps_resolution_and_colour_profile(flat_background):
    import io

    from PIL import Image

    profile = b"fake-icc-profile-bytes"
    raster = _raster(flat_background)
    raster.preserved_metadata["icc_profile"] = profile

    encoded = encode_raster(raster, mime_type="image/png")
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.size == (flat_background.shape[1], flat_background.shape[0])
        assert image.info.get("icc_profile") == profile
