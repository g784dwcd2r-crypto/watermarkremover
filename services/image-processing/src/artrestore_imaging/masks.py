"""Mask construction and normalisation.

The editor sends a declarative ``editor_state`` document plus (optionally) a
rasterised PNG. The server rasterises the declarative document itself so that a
job is reproducible from stored state alone, and so a hand-crafted PNG cannot
smuggle a mask the editor never showed the user.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .errors import MaskError

EDITOR_STATE_VERSION = 1
MAX_REGIONS = 64
MAX_POINTS_PER_REGION = 20_000


@dataclass(slots=True)
class MaskAdjustments:
    """Post-rasterisation mask shaping, mirroring the editor controls."""

    expand: int = 0  # positive grows, negative contracts (pixels)
    feather: float = 2.0  # gaussian softening of the boundary (pixels)
    blur: float = 0.0  # additional blur applied to the mask alpha

    @classmethod
    def from_dict(cls, data: dict | None) -> "MaskAdjustments":
        data = data or {}
        return cls(
            expand=int(_clamp(data.get("expand", 0), -256, 256)),
            feather=float(_clamp(data.get("feather", 2.0), 0, 128)),
            blur=float(_clamp(data.get("blur", 0.0), 0, 128)),
        )

    def to_dict(self) -> dict:
        return {"expand": self.expand, "feather": self.feather, "blur": self.blur}


def _clamp(value, low, high):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return low if low > 0 else 0
    return max(low, min(high, numeric))


def rasterize_editor_state(state: dict, width: int, height: int) -> np.ndarray:
    """Render the declarative editor document into a uint8 mask (0..255).

    Supported region types: ``brush``, ``eraser``, ``rect``, ``polygon``,
    ``lasso``. ``mode`` may be ``add`` (default) or ``subtract``.
    """
    if width <= 0 or height <= 0:
        raise MaskError("Cannot rasterize a mask for a zero-sized image.")

    regions = state.get("regions") or []
    if not isinstance(regions, list):
        raise MaskError("editor_state.regions must be a list.")
    if len(regions) > MAX_REGIONS:
        raise MaskError(f"A mask may contain at most {MAX_REGIONS} regions.")

    canvas = np.zeros((height, width), dtype=np.float32)
    source_size = (state.get("image") or {}).get("width"), (state.get("image") or {}).get("height")
    scale_x = width / float(source_size[0]) if source_size[0] else 1.0
    scale_y = height / float(source_size[1]) if source_size[1] else 1.0

    for region in regions:
        if not isinstance(region, dict):
            continue
        layer = _render_region(region, width, height, scale_x, scale_y)
        if layer is None:
            continue
        opacity = float(_clamp(region.get("opacity", 1.0), 0.0, 1.0))
        subtract = region.get("mode") == "subtract" or region.get("type") == "eraser"
        if subtract:
            canvas = np.clip(canvas - layer * opacity, 0.0, 1.0)
        else:
            canvas = np.clip(canvas + layer * opacity, 0.0, 1.0)

    return (canvas * 255.0).astype(np.uint8)


def _render_region(region: dict, width: int, height: int, sx: float, sy: float) -> np.ndarray | None:
    kind = str(region.get("type", "")).lower()
    layer = np.zeros((height, width), dtype=np.float32)

    if kind in ("brush", "eraser"):
        points = _points(region.get("points"), sx, sy)
        if not points:
            return None
        radius = max(1, int(round(float(_clamp(region.get("size", 24), 1, 4096)) * max(sx, sy) / 2)))
        hardness = float(_clamp(region.get("hardness", 0.8), 0.0, 1.0))
        stroke = np.zeros((height, width), dtype=np.uint8)
        if len(points) == 1:
            cv2.circle(stroke, points[0], radius, 255, -1, lineType=cv2.LINE_AA)
        else:
            cv2.polylines(
                stroke,
                [np.array(points, dtype=np.int32)],
                isClosed=False,
                color=255,
                thickness=radius * 2,
                lineType=cv2.LINE_AA,
            )
            for point in (points[0], points[-1]):
                cv2.circle(stroke, point, radius, 255, -1, lineType=cv2.LINE_AA)
        layer = stroke.astype(np.float32) / 255.0
        if hardness < 1.0:
            softness = max(1, int(round(radius * (1.0 - hardness))))
            kernel = softness * 2 + 1
            layer = cv2.GaussianBlur(layer, (kernel, kernel), 0)
    elif kind in ("rect", "rectangle"):
        x = int(round(float(region.get("x", 0)) * sx))
        y = int(round(float(region.get("y", 0)) * sy))
        w = int(round(float(region.get("width", 0)) * sx))
        h = int(round(float(region.get("height", 0)) * sy))
        if w <= 0 or h <= 0:
            return None
        cv2.rectangle(layer, (x, y), (x + w, y + h), 1.0, -1)
    elif kind in ("polygon", "lasso"):
        points = _points(region.get("points"), sx, sy)
        if len(points) < 3:
            return None
        cv2.fillPoly(layer, [np.array(points, dtype=np.int32)], 1.0, lineType=cv2.LINE_AA)
    else:
        return None

    return np.clip(layer, 0.0, 1.0)


def _points(raw, sx: float, sy: float) -> list[tuple[int, int]]:
    if not isinstance(raw, list):
        return []
    if len(raw) > MAX_POINTS_PER_REGION:
        raise MaskError("A mask region contains too many points.")
    points: list[tuple[int, int]] = []
    for item in raw:
        if isinstance(item, dict):
            x, y = item.get("x"), item.get("y")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x, y = item[0], item[1]
        else:
            continue
        try:
            points.append((int(round(float(x) * sx)), int(round(float(y) * sy))))
        except (TypeError, ValueError):
            continue
    return points


def decode_mask_png(data: bytes, width: int, height: int) -> np.ndarray:
    """Decode an uploaded mask PNG to a single-channel uint8 mask."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode in ("RGBA", "LA"):
                mask = np.array(image.convert("RGBA"), dtype=np.uint8)[:, :, 3]
            else:
                mask = np.array(image.convert("L"), dtype=np.uint8)
    except Exception as exc:  # noqa: BLE001
        raise MaskError(f"The mask image could not be decoded: {exc}") from exc

    if mask.shape[0] != height or mask.shape[1] != width:
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    return mask


def normalize_mask(
    mask: np.ndarray,
    adjustments: MaskAdjustments | None = None,
    *,
    binarize_threshold: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Shape a raw mask into ``(binary, soft)``.

    ``binary`` (0/255) selects the pixels to reconstruct; ``soft`` (0..255)
    carries the feathered boundary used when compositing the result back so the
    repair blends into untouched pixels instead of leaving a hard seam.
    """
    if mask.ndim != 2:
        raise MaskError("A mask must be single-channel.")
    adjustments = adjustments or MaskAdjustments()

    binary = (mask > binarize_threshold).astype(np.uint8) * 255

    if adjustments.expand:
        size = abs(int(adjustments.expand))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size * 2 + 1, size * 2 + 1))
        binary = cv2.dilate(binary, kernel) if adjustments.expand > 0 else cv2.erode(binary, kernel)

    if not binary.any():
        raise MaskError("The mask is empty. Paint or draw a selection before processing.")

    soft = binary.astype(np.float32) / 255.0
    total_blur = adjustments.feather + adjustments.blur
    if total_blur > 0:
        kernel = int(round(total_blur)) * 2 + 1
        soft = cv2.GaussianBlur(soft, (kernel, kernel), total_blur / 2.0)
    soft = np.clip(soft, 0.0, 1.0)

    return binary, (soft * 255.0).astype(np.uint8)


def mask_components(binary: np.ndarray, *, min_area: int = 4) -> list[dict]:
    """Split a mask into independent cleanup regions with bounding boxes."""
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), connectivity=8
    )
    components: list[dict] = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < min_area:
            continue
        components.append(
            {
                "index": index,
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
                "area": int(area),
                "centroid": [float(centroids[index][0]), float(centroids[index][1])],
                "aspect_ratio": round(float(w) / float(h), 3) if h else 0.0,
                "fill_ratio": round(float(area) / float(max(1, w * h)), 3),
            }
        )
    components.sort(key=lambda item: item["area"], reverse=True)
    return components


def mask_coverage(binary: np.ndarray) -> float:
    """Fraction of the image selected by the mask (0..1)."""
    total = binary.shape[0] * binary.shape[1]
    return float((binary > 0).sum()) / float(total or 1)


def encode_mask_png(mask: np.ndarray) -> bytes:
    """Encode a mask as a greyscale PNG for storage."""
    buffer = io.BytesIO()
    Image.fromarray(mask.astype(np.uint8), mode="L").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
