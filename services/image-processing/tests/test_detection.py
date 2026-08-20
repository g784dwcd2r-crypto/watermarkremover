"""Protected-region safeguards.

These are the tests that keep the product honest: attribution and provenance
content must be detected and refused, while ordinary authorized cleanup of a
date stamp or an obsolete badge must go through.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from artrestore_imaging import demo
from artrestore_imaging.detection import (
    PROTECTED_KINDS,
    DetectionConfig,
    Region,
    assess_mask,
    detect_overlay_candidates,
    detect_protected_regions,
    stroke_statistics,
    subtract_protected,
)


def _box_mask(shape, box):
    mask = np.zeros(shape, np.uint8)
    x, y, w, h = box
    cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    return mask


def _kinds(regions):
    return {region.kind for region in regions}


# -- signatures -------------------------------------------------------------


def test_signature_is_detected(painting):
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assert "signature" in _kinds(regions)


def test_mask_over_signature_is_blocked(painting):
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assessment = assess_mask(_box_mask(signed.shape[:2], box), regions)
    assert assessment.blocked is True
    assert "signature" in assessment.explanation or "attribution" in assessment.explanation


def test_signature_block_explains_the_refusal(painting):
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assessment = assess_mask(_box_mask(signed.shape[:2], box), regions)
    assert "authorized cleanup" in assessment.explanation
    assert "provenance" in assessment.explanation


def test_warn_only_enforcement_reports_without_blocking(painting):
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assessment = assess_mask(_box_mask(signed.shape[:2], box), regions, enforcement="warn")
    assert assessment.blocked is False
    assert assessment.overlaps


# -- copyright lines --------------------------------------------------------


def test_copyright_line_geometry_is_detected(painting):
    credited, box = demo.add_copyright_line(painting)
    regions = detect_protected_regions(credited, candidate_boxes=[box])
    assert _kinds(regions) & {"copyright_notice", "signature"}


def test_mask_over_copyright_line_stops_processing(painting):
    credited, box = demo.add_copyright_line(painting)
    regions = detect_protected_regions(credited, candidate_boxes=[box])
    assessment = assess_mask(_box_mask(credited.shape[:2], box), regions)
    assert assessment.blocked is True
    assert assessment.overlaps


# -- stock watermarks -------------------------------------------------------


def test_tiled_stock_watermark_is_detected(painting):
    watermarked = demo.add_stock_watermark(painting)
    regions = detect_protected_regions(watermarked)
    assert "stock_watermark" in _kinds(regions)


def test_stock_watermark_blocks_any_mask(painting):
    watermarked = demo.add_stock_watermark(painting)
    regions = detect_protected_regions(watermarked)
    mask = _box_mask(watermarked.shape[:2], (60, 60, 120, 60))
    assert assess_mask(mask, regions).blocked is True


def test_large_overlay_selection_is_treated_as_agency_mark(flat_background):
    height, width = flat_background.shape[:2]
    box = (0, int(height * 0.3), width, int(height * 0.35))
    regions = detect_protected_regions(flat_background, candidate_boxes=[box])
    assert "stock_watermark" in _kinds(regions)


# -- false-positive guards --------------------------------------------------


def test_clean_gradient_has_no_protected_regions(flat_background):
    assert detect_protected_regions(flat_background) == []


def test_clean_texture_is_not_mistaken_for_a_tiled_watermark(woven_texture):
    regions = detect_protected_regions(woven_texture)
    assert "stock_watermark" not in _kinds(regions)


def test_clean_painting_is_not_flagged(painting):
    regions = detect_protected_regions(painting)
    assert "stock_watermark" not in _kinds(regions)


def test_date_stamp_needs_acknowledgement_then_proceeds(flat_background):
    """A corner date stamp and a credit line are the same shape.

    The product refuses to guess: it pauses for an explicit attestation rather
    than either blocking authorized cleanup or silently erasing a credit line.
    """
    stamped, mask = demo.add_date_stamp(flat_background)
    regions = detect_protected_regions(stamped)

    paused = assess_mask(mask, regions)
    if paused.overlaps:
        assert paused.requires_acknowledgement is True
        assert paused.blocking_overlaps == []
        cleared = assess_mask(mask, regions, acknowledged_kinds=paused.unacknowledged_kinds)
        assert cleared.blocked is False
    else:
        assert paused.blocked is False


def test_acknowledgement_cannot_clear_a_signature(painting):
    """Block severity has no override, even with every kind acknowledged."""
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assessment = assess_mask(
        _box_mask(signed.shape[:2], box), regions, acknowledged_kinds=list(PROTECTED_KINDS)
    )
    assert assessment.blocked is True


def test_centre_frame_overlay_is_not_flagged_as_signature(flat_background):
    """Placement matters: a badge in the middle of the frame is not a signature."""
    image = flat_background.copy()
    cv2.putText(image, "DRAFT", (180, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    regions = detect_protected_regions(image, candidate_boxes=[(175, 125, 110, 35)])
    assert "signature" not in _kinds(regions)


# -- provenance metadata ----------------------------------------------------


def test_provenance_metadata_is_reported_but_does_not_block(flat_background):
    provenance = {"has_any": True, "has_c2pa": True, "exif_rights": {}}
    regions = detect_protected_regions(flat_background, provenance=provenance)
    assert "provenance_label" in _kinds(regions)

    mask = _box_mask(flat_background.shape[:2], (10, 10, 40, 20))
    assessment = assess_mask(mask, regions)
    assert assessment.blocked is False, "metadata provenance is preserved, not a cleanup blocker"


# -- assistive detection ----------------------------------------------------


def test_overlay_candidates_find_a_date_stamp(flat_background):
    stamped, mask = demo.add_date_stamp(flat_background)
    candidates = detect_overlay_candidates(stamped)
    assert candidates
    ys, xs = np.nonzero(mask)
    stamp_box = (xs.min(), ys.min(), xs.max(), ys.max())
    hit = any(
        candidate.x < stamp_box[2]
        and candidate.x + candidate.width > stamp_box[0]
        and candidate.y < stamp_box[3]
        and candidate.y + candidate.height > stamp_box[1]
        for candidate in candidates
    )
    assert hit


def test_overlay_candidates_respect_limit(painting):
    assert len(detect_overlay_candidates(painting, limit=3)) <= 3


# -- helpers ----------------------------------------------------------------


def test_stroke_statistics_on_empty_crop():
    stats = stroke_statistics(np.zeros((10, 10), np.uint8))
    assert stats["ink_ratio"] == 0.0
    assert stats["component_count"] == 0


def test_subtract_protected_removes_the_region():
    mask = np.full((100, 100), 255, np.uint8)
    region = Region(kind="signature", x=10, y=10, width=20, height=20, confidence=0.9, reason="test")
    result = subtract_protected(mask, [region])
    assert result[15, 15] == 0
    assert result[80, 80] == 255


def test_assess_mask_with_empty_mask_is_not_blocked(painting):
    signed, box = demo.add_signature(painting)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assert assess_mask(np.zeros(signed.shape[:2], np.uint8), regions).blocked is False


def test_detection_config_is_tunable(painting):
    signed, box = demo.add_signature(painting)
    strict = DetectionConfig(signature_max_ink_ratio=0.0)
    regions = detect_protected_regions(signed, config=strict, candidate_boxes=[box])
    assert "signature" not in _kinds(regions)


# -- trace metrics ----------------------------------------------------------


def test_trace_statistics_separates_handwriting_from_print(painting, flat_background):
    from artrestore_imaging.detection import _to_gray, trace_statistics

    signed, box = demo.add_signature(painting)
    x, y, w, h = box
    handwriting = trace_statistics(_to_gray(signed)[y : y + h, x : x + w])

    credited, cbox = demo.add_copyright_line(painting)
    cx, cy, cw, ch = cbox
    printed = trace_statistics(_to_gray(credited)[cy : cy + ch, cx : cx + cw])

    assert handwriting["trace_span_ratio"] > printed["trace_span_ratio"]
    assert handwriting["longest_trace_ratio"] > printed["longest_trace_ratio"]
    assert handwriting["contour_count"] < printed["contour_count"]


def test_trace_statistics_on_tiny_crop():
    from artrestore_imaging.detection import trace_statistics

    stats = trace_statistics(np.zeros((2, 2), np.uint8))
    assert stats["contour_count"] == 0


def test_signature_on_flat_background_is_detected(flat_background):
    signed, box = demo.add_signature(flat_background)
    regions = detect_protected_regions(signed, candidate_boxes=[box])
    assert "signature" in _kinds(regions)


def test_empty_corner_is_not_a_signature(painting):
    """The same box on the unsigned painting must not trip the detector."""
    _, box = demo.add_signature(painting)
    regions = detect_protected_regions(painting, candidate_boxes=[box])
    assert "signature" not in _kinds(regions)


# -- graded watermark evidence ---------------------------------------------


@pytest.mark.parametrize("size", [(300, 220), (360, 260), (560, 400), (900, 640)])
def test_tiled_watermark_is_caught_at_every_size(size):
    """Fewer tiles in frame weakens the lattice signal but must not hide it."""
    width, height = size
    watermarked = demo.add_stock_watermark(demo.painted_illustration(width, height))
    regions = detect_protected_regions(watermarked)
    stock = [region for region in regions if region.kind == "stock_watermark"]
    assert stock, f"missed the watermark at {size}"

    mask = _box_mask(watermarked.shape[:2], (30, 30, 80, 40))
    assessment = assess_mask(mask, regions)
    assert assessment.blocked is True


@pytest.mark.parametrize(
    "generator",
    [
        lambda w, h: demo.painted_illustration(w, h),
        lambda w, h: demo.woven_texture(w, h),
        lambda w, h: demo.flat_gradient(w, h),
        lambda w, h: demo.line_artwork(min(w, h), min(w, h)),
    ],
)
@pytest.mark.parametrize("size", [(300, 220), (560, 400)])
def test_clean_artwork_is_never_flagged_as_a_watermark(generator, size):
    """Periodic weave and hatched line work must not read as a licensing overlay."""
    image = generator(*size)
    regions = detect_protected_regions(image)
    assert "stock_watermark" not in _kinds(regions)


def test_strong_evidence_blocks_and_moderate_evidence_asks(painting):
    """A clear lattice is refused outright; a marginal one pauses for a check."""
    from artrestore_imaging.detection import SEVERITY_BLOCK, SEVERITY_REVIEW

    large = demo.add_stock_watermark(demo.painted_illustration(900, 640))
    small = demo.add_stock_watermark(demo.painted_illustration(300, 220))

    strong = [r for r in detect_protected_regions(large) if r.kind == "stock_watermark"]
    moderate = [r for r in detect_protected_regions(small) if r.kind == "stock_watermark"]
    assert strong and strong[0].severity == SEVERITY_BLOCK
    assert moderate and moderate[0].severity == SEVERITY_REVIEW

    mask = _box_mask(small.shape[:2], (20, 20, 60, 30))
    paused = assess_mask(mask, moderate)
    assert paused.requires_acknowledgement is True
    cleared = assess_mask(mask, moderate, acknowledged_kinds=["stock_watermark"])
    assert cleared.blocked is False

    big_mask = _box_mask(large.shape[:2], (20, 20, 60, 30))
    assert assess_mask(big_mask, strong, acknowledged_kinds=["stock_watermark"]).blocked is True
