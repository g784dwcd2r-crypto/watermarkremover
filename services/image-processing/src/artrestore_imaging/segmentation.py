"""Assisted selection.

Turns a rough gesture (a dragged box or a single click) into a pixel-accurate
mask so users do not have to trace an overlay by hand. GrabCut ships as the
always-available segmenter; an operator can point ``ARS_SEGMENTATION_MODEL_PATH``
at a locally deployed segmentation network for harder subjects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(slots=True)
class SegmentationResult:
    mask: np.ndarray  # uint8 0/255
    method: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "confidence": round(float(self.confidence), 3),
            "selected_pixels": int((self.mask > 0).sum()),
        }


def model_available(settings: dict | None = None) -> bool:
    path = (settings or {}).get("segmentation_model_path") or os.environ.get(
        "ARS_SEGMENTATION_MODEL_PATH", ""
    )
    if not path or not os.path.exists(path):
        return False
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def segment_box(
    rgb: np.ndarray, box: tuple[int, int, int, int], *, iterations: int = 4
) -> SegmentationResult:
    """Refine a dragged rectangle into a tight object mask via GrabCut."""
    height, width = rgb.shape[:2]
    x, y, w, h = (int(v) for v in box)
    x = max(0, min(x, width - 2))
    y = max(0, min(y, height - 2))
    w = max(2, min(w, width - x))
    h = max(2, min(h, height - y))

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros((height, width), np.uint8)
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(
            bgr, mask, (x, y, w, h), background_model, foreground_model, iterations, cv2.GC_INIT_WITH_RECT
        )
    except cv2.error:
        result = np.zeros((height, width), np.uint8)
        result[y : y + h, x : x + w] = 255
        return SegmentationResult(mask=result, method="rect_fallback", confidence=0.3)

    selected = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    area = float((selected > 0).sum())
    box_area = float(w * h) or 1.0
    confidence = float(np.clip(area / box_area, 0.0, 1.0))
    if area < 8:
        selected[y : y + h, x : x + w] = 255
        return SegmentationResult(mask=selected, method="rect_fallback", confidence=0.3)
    return SegmentationResult(mask=selected, method="grabcut", confidence=confidence)


def segment_point(
    rgb: np.ndarray, point: tuple[int, int], *, tolerance: int = 18, max_radius: int = 220
) -> SegmentationResult:
    """Grow a selection outward from a click using a colour-tolerance flood fill."""
    height, width = rgb.shape[:2]
    x = int(np.clip(point[0], 0, width - 1))
    y = int(np.clip(point[1], 0, height - 1))

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).copy()
    flood_mask = np.zeros((height + 2, width + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(
        bgr,
        flood_mask,
        (x, y),
        0,
        (tolerance,) * 3,
        (tolerance,) * 3,
        flags,
    )
    selected = flood_mask[1:-1, 1:-1] * 255

    # Constrain runaway fills to a neighbourhood of the click.
    limiter = np.zeros((height, width), np.uint8)
    cv2.circle(limiter, (x, y), max_radius, 255, -1)
    selected = cv2.bitwise_and(selected, limiter)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    selected = cv2.morphologyEx(selected, cv2.MORPH_CLOSE, kernel)

    area = float((selected > 0).sum())
    confidence = float(np.clip(area / float(height * width) * 40.0, 0.05, 0.95))
    return SegmentationResult(mask=selected, method="flood_fill", confidence=confidence)


def segment_text_overlay(rgb: np.ndarray, box: tuple[int, int, int, int]) -> SegmentationResult:
    """Isolate glyph strokes inside a box instead of selecting the whole rectangle.

    Masking only the strokes leaves far more original pixels intact than
    blanking the bounding box, which produces a markedly better repair.
    """
    height, width = rgb.shape[:2]
    x, y, w, h = (int(v) for v in box)
    x, y = max(0, x), max(0, y)
    w, h = max(1, min(w, width - x)), max(1, min(h, height - y))

    crop = cv2.cvtColor(rgb[y : y + h, x : x + w], cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(crop, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if binary.mean() > 127:
        binary = cv2.bitwise_not(binary)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.dilate(binary, kernel, iterations=1)

    mask = np.zeros((height, width), np.uint8)
    mask[y : y + h, x : x + w] = binary
    coverage = float((binary > 0).mean())
    return SegmentationResult(mask=mask, method="text_strokes", confidence=float(np.clip(coverage * 2, 0.1, 0.95)))
