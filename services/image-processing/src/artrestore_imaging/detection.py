"""Overlay detection and protected-region safeguards.

Two very different jobs live here.

``detect_overlay_candidates`` is a *convenience* feature: it proposes text and
overlay regions so the user does not have to paint every date stamp by hand. Its
output is only ever a suggestion - the user still approves the mask.

``detect_protected_regions`` is a *safeguard*: it looks for artist signatures,
copyright lines, stock-agency watermarks and provenance labels. When a mask
overlaps one of those, processing stops. These heuristics are deliberately
conservative in the direction of refusing work: a false positive costs the user
an explanation and an appeal, a false negative would make this product a tool
for erasing attribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import cv2
import numpy as np

# Keywords that mark a region as attribution or licensing content. Used only
# when an OCR engine is available; the geometric heuristics stand on their own.
RIGHTS_KEYWORDS: tuple[str, ...] = (
    "copyright",
    "(c)",
    "©",
    "all rights reserved",
    "tous droits",
    "getty",
    "gettyimages",
    "shutterstock",
    "adobe stock",
    "istock",
    "istockphoto",
    "alamy",
    "depositphotos",
    "dreamstime",
    "123rf",
    "unsplash+",
    "sample",
    "preview only",
    "licensed",
    "watermark",
    "content credentials",
    "c2pa",
    "do not copy",
    "proof",
)

PROTECTED_KINDS: tuple[str, ...] = (
    "signature",
    "copyright_notice",
    "stock_watermark",
    "agency_mark",
    "provenance_label",
)


@dataclass(slots=True)
class DetectionConfig:
    """Tunable thresholds. Defaults are the shipped, tested values."""

    min_region_area: int = 40
    corner_fraction: float = 0.28
    bottom_band_fraction: float = 0.22
    signature_max_ink_ratio: float = 0.32
    signature_min_stroke_variation: float = 0.22
    signature_max_area_fraction: float = 0.08
    #: A handwritten trace wanders across most of its box...
    signature_min_span_ratio: float = 0.60
    #: ...and is far longer than the box diagonal...
    signature_min_trace_ratio: float = 1.50
    #: ...while printed text breaks into many separate glyph outlines.
    signature_max_contours: int = 12
    #: Rectilinear traces are frames and badges, not handwriting.
    signature_max_axis_alignment: float = 0.55
    stock_area_fraction: float = 0.18
    stock_span_fraction: float = 0.55
    repeated_pattern_peaks: int = 3
    text_min_height: int = 6
    ocr_enabled: bool = True


#: Severity tiers.
#:
#: ``block``  - high-confidence attribution or licensing content. There is no
#:              override: the product does not remove it, full stop.
#: ``review`` - geometry that *may* be a credit line but is genuinely ambiguous
#:              without reading the text (a date stamp in a bottom corner has
#:              the same shape as a copyright line). Processing stops and the
#:              user must explicitly attest that the region is not attribution
#:              content before it proceeds. That attestation is recorded.
SEVERITY_BLOCK = "block"
SEVERITY_REVIEW = "review"


@dataclass(slots=True)
class Region:
    """A detected rectangle with a reason, a confidence and a severity."""

    kind: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    reason: str
    severity: str = SEVERITY_BLOCK
    evidence: dict = field(default_factory=dict)

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "severity": self.severity,
            "evidence": self.evidence,
        }

    def to_mask(self, shape: tuple[int, int]) -> np.ndarray:
        mask = np.zeros(shape, dtype=np.uint8)
        cv2.rectangle(mask, (self.x, self.y), (self.x + self.width, self.y + self.height), 255, -1)
        return mask


# ---------------------------------------------------------------------------
# Low-level primitives
# ---------------------------------------------------------------------------


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _ink_mask(gray_crop: np.ndarray) -> np.ndarray:
    """Binarise a crop so that 'ink' (the drawn marks) is foreground.

    Global thresholding fails on painted and photographic backgrounds, where the
    background itself spans the full tonal range. Marks laid *on top* of a
    surface are instead separated by local contrast: a mark is a thin run of
    pixels that departs from the locally-estimated background. Both polarities
    are extracted (dark ink on light paper, light text on a dark photo) and the
    sparser one wins, since a mark covers less of its box than the surface does.
    """
    if gray_crop.size == 0:
        return np.zeros_like(gray_crop, dtype=np.uint8)

    height, width = gray_crop.shape[:2]
    span = max(3, min(31, (min(height, width) // 2) | 1))
    background = cv2.medianBlur(gray_crop, span)
    residual = background.astype(np.float32) - gray_crop.astype(np.float32)

    noise = float(residual.std()) or 1.0
    threshold = max(6.0, noise * 1.4)

    dark_ink = (residual > threshold).astype(np.uint8) * 255
    light_ink = (residual < -threshold).astype(np.uint8) * 255

    dark_ratio = float((dark_ink > 0).mean())
    light_ratio = float((light_ink > 0).mean())

    if dark_ratio == 0.0 and light_ratio == 0.0:
        return dark_ink
    if light_ratio == 0.0:
        return dark_ink
    if dark_ratio == 0.0:
        return light_ink
    return dark_ink if dark_ratio <= light_ratio else light_ink


def stroke_statistics(ink: np.ndarray) -> dict:
    """Describe stroke geometry inside a binarised crop.

    Signatures have thin strokes of *varying* width and low ink coverage;
    printed text has more uniform strokes; solid graphics have high coverage.
    """
    total = float(ink.size or 1)
    foreground = float((ink > 0).sum())
    ink_ratio = foreground / total
    if foreground < 1:
        return {
            "ink_ratio": 0.0,
            "stroke_width_mean": 0.0,
            "stroke_width_std": 0.0,
            "stroke_variation": 0.0,
            "component_count": 0,
            "largest_component_ratio": 0.0,
        }

    distance = cv2.distanceTransform((ink > 0).astype(np.uint8), cv2.DIST_L2, 3)
    widths = distance[ink > 0] * 2.0
    mean_width = float(widths.mean())
    std_width = float(widths.std())

    count, _, stats, _ = cv2.connectedComponentsWithStats((ink > 0).astype(np.uint8), connectivity=8)
    areas = sorted((int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, count)), reverse=True)

    return {
        "ink_ratio": round(ink_ratio, 4),
        "stroke_width_mean": round(mean_width, 3),
        "stroke_width_std": round(std_width, 3),
        "stroke_variation": round(std_width / mean_width, 3) if mean_width else 0.0,
        "component_count": max(0, count - 1),
        "largest_component_ratio": round(areas[0] / foreground, 3) if areas else 0.0,
    }


def trace_statistics(gray_crop: np.ndarray) -> dict:
    """Describe the *continuity* of the marks in a crop.

    This is what separates handwriting from print. A signature is one long
    uninterrupted trace that wanders across its whole bounding box, so its
    longest edge contour is several times the box diagonal and spans nearly the
    full width. Printed text is many short, separate glyph outlines; surface
    texture is many short contours with no dominant trace.
    """
    height, width = gray_crop.shape[:2]
    if height < 4 or width < 4:
        return {
            "contour_count": 0,
            "longest_trace_ratio": 0.0,
            "trace_span_ratio": 0.0,
            "edge_density": 0.0,
        }

    blurred = cv2.GaussianBlur(gray_crop, (3, 3), 0)
    median = float(np.median(blurred))
    edges = cv2.Canny(
        blurred, int(max(0, 0.66 * median)), int(min(255, 1.33 * median)), L2gradient=True
    )
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    edge_density = float((edges > 0).mean())
    if not contours:
        return {
            "contour_count": 0,
            "longest_trace_ratio": 0.0,
            "trace_span_ratio": 0.0,
            "axis_alignment": 0.0,
            "edge_density": round(edge_density, 4),
        }

    lengths = [cv2.arcLength(contour, False) for contour in contours]
    longest = int(np.argmax(lengths))
    _, _, box_width, _ = cv2.boundingRect(contours[longest])
    diagonal = float(np.hypot(height, width)) or 1.0

    return {
        "contour_count": len(contours),
        "longest_trace_ratio": round(lengths[longest] / diagonal, 3),
        "trace_span_ratio": round(box_width / float(width), 3),
        "axis_alignment": _axis_alignment(contours[longest]),
        "edge_density": round(edge_density, 4),
    }


def _axis_alignment(contour: np.ndarray, *, step: int = 4, tolerance: float = 12.0) -> float:
    """Fraction of a contour that runs horizontally or vertically.

    Boxes, badges, panel borders and UI chrome trace almost entirely along the
    axes; handwriting almost never does. Without this, the outline of a solid
    rectangular badge reads as one long continuous trace and would be mistaken
    for a signature.
    """
    points = np.asarray(contour).reshape(-1, 2)
    if len(points) < 2 * step:
        return 0.0
    deltas = points[step:] - points[:-step]
    angles = np.degrees(np.arctan2(deltas[:, 1], deltas[:, 0])) % 180.0
    aligned = (
        (angles < tolerance)
        | (np.abs(angles - 90.0) < tolerance)
        | (angles > 180.0 - tolerance)
    )
    return round(float(aligned.mean()), 3)


def _ocr_text(bgr_or_gray: np.ndarray) -> str | None:
    """Read text from a crop when an OCR engine is installed.

    OCR is optional: when ``pytesseract`` and the tesseract binary are absent the
    geometric heuristics carry the decision on their own.
    """
    try:  # pragma: no cover - depends on an optional system binary
        import pytesseract
    except Exception:  # noqa: BLE001
        return None
    try:  # pragma: no cover
        return str(pytesseract.image_to_string(bgr_or_gray, config="--psm 7")).strip().lower()
    except Exception:  # noqa: BLE001
        return None


def _keyword_hit(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for keyword in RIGHTS_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


# ---------------------------------------------------------------------------
# Overlay candidate detection (assistive)
# ---------------------------------------------------------------------------


def detect_overlay_candidates(
    rgb: np.ndarray, config: DetectionConfig | None = None, *, limit: int = 25
) -> list[Region]:
    """Propose text / overlay regions the user may want to clean.

    Uses a morphological-gradient text detector: overlays (date stamps, burned-in
    captions, logos) show a dense cluster of high-gradient strokes that survives
    horizontal closing while photographic texture does not.
    """
    config = config or DetectionConfig()
    gray = _to_gray(rgb)
    height, width = gray.shape[:2]

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    gradient = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
    _, binary = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    closing_width = max(5, int(width * 0.012) | 1)
    closing = cv2.getStructuringElement(cv2.MORPH_RECT, (closing_width, 3))
    connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, closing)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[Region] = []
    image_area = float(height * width)

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < config.min_region_area or h < config.text_min_height:
            continue
        if h > height * 0.5 or w > width * 0.98:
            continue
        aspect = w / float(h)
        if aspect < 0.8 or aspect > 45:
            continue

        region_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(region_mask, [contour - (x, y)], -1, 255, -1)
        fill = float((binary[y : y + h, x : x + w] > 0).sum()) / float(area)
        if fill < 0.12 or fill > 0.92:
            continue

        crop = gray[y : y + h, x : x + w]
        stats = stroke_statistics(_ink_mask(crop))
        # Text-like: several small components with fairly uniform stroke width.
        text_score = 0.0
        if stats["component_count"] >= 2:
            text_score += 0.3
        if 0.1 <= stats["ink_ratio"] <= 0.6:
            text_score += 0.3
        if stats["stroke_variation"] < 0.6:
            text_score += 0.2
        if area / image_area < 0.2:
            text_score += 0.2

        if text_score < 0.5:
            continue

        candidates.append(
            Region(
                kind="overlay_candidate",
                x=int(x),
                y=int(y),
                width=int(w),
                height=int(h),
                confidence=min(1.0, text_score),
                reason="High-contrast text-like overlay cluster.",
                evidence={"fill_ratio": round(fill, 3), **stats},
            )
        )

    candidates.sort(key=lambda region: (region.confidence, region.width * region.height), reverse=True)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Protected-region detection (safeguard)
# ---------------------------------------------------------------------------


def _in_corner_or_bottom(
    box: tuple[int, int, int, int], shape: tuple[int, int], config: DetectionConfig
) -> tuple[bool, str]:
    x, y, w, h = box
    height, width = shape
    cx, cy = x + w / 2.0, y + h / 2.0
    corner_w = width * config.corner_fraction
    corner_h = height * config.corner_fraction
    if cx <= corner_w and cy <= corner_h:
        return True, "top-left corner"
    if cx >= width - corner_w and cy <= corner_h:
        return True, "top-right corner"
    if cx <= corner_w and cy >= height - corner_h:
        return True, "bottom-left corner"
    if cx >= width - corner_w and cy >= height - corner_h:
        return True, "bottom-right corner"
    if cy >= height * (1.0 - config.bottom_band_fraction):
        return True, "bottom margin"
    return False, ""


def _repeated_pattern_score(gray: np.ndarray, config: DetectionConfig) -> dict:
    """Detect the tiled, repeating structure typical of stock watermarks.

    Smooth gradients, vignettes and ordinary photographic content must not
    trigger this, so the analysis runs on a high-pass image (removing low
    frequency content entirely) and looks for a *lattice*: strong secondary
    peaks in the normalised autocorrelation, corroborated by consistently
    oriented diagonal edge energy. Either signal alone scores below the
    threshold; a tiled watermark produces both.
    """
    small = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA).astype(np.float32)
    high_pass = small - cv2.GaussianBlur(small, (0, 0), 4.0)
    if float(high_pass.std()) < 1.0:
        return {
            "secondary_peak_ratio": 0.0,
            "diagonal_energy": 0.0,
            "diagonal_lines": 0,
            "score": 0.0,
        }

    windowed = high_pass * np.outer(np.hanning(256), np.hanning(256)).astype(np.float32)
    spectrum = np.fft.fft2(windowed)
    autocorrelation = np.fft.fftshift(np.real(np.fft.ifft2(spectrum * np.conj(spectrum))))
    centre = float(autocorrelation[128, 128]) or 1.0
    normalised = autocorrelation / centre

    # Ignore the central lobe (every image autocorrelates with itself) and the
    # axis cross (rows/columns of uniform content are not a tiled watermark).
    yy, xx = np.mgrid[0:256, 0:256]
    radius = np.sqrt((yy - 128) ** 2 + (xx - 128) ** 2)
    off_centre = radius > 10
    off_axis = (np.abs(yy - 128) > 3) & (np.abs(xx - 128) > 3)
    candidates = normalised[off_centre & off_axis]
    secondary_peak_ratio = float(candidates.max()) if candidates.size else 0.0

    edges = cv2.Canny(cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA), 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=70, minLineLength=60, maxLineGap=8)
    diagonal = 0
    segments = np.empty((0, 4), dtype=np.int32)
    if lines is not None and len(lines):
        # OpenCV 4 returns (N, 1, 4) and OpenCV 5 returns (N, 4).
        segments = np.asarray(lines).reshape(-1, 4)[:400]
        for x1, y1, x2, y2 in segments:
            angle = abs(np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1))))
            if 20.0 <= angle <= 70.0 or 110.0 <= angle <= 160.0:
                diagonal += 1
    diagonal_energy = diagonal / float(len(segments) or 1)

    periodic = secondary_peak_ratio >= 0.40
    oriented = diagonal_energy >= 0.40 and diagonal >= 10
    score = 0.0
    if periodic:
        score += 0.35
    if oriented:
        score += 0.35
    if periodic and oriented:
        score += 0.3  # both signals agree: this is a tiled overlay

    return {
        "secondary_peak_ratio": round(secondary_peak_ratio, 3),
        "diagonal_energy": round(float(diagonal_energy), 3),
        "diagonal_lines": int(diagonal),
        "score": round(min(score, 1.0), 3),
    }


def detect_protected_regions(
    rgb: np.ndarray,
    *,
    config: DetectionConfig | None = None,
    provenance: dict | None = None,
    candidate_boxes: Iterable[tuple[int, int, int, int]] | None = None,
) -> list[Region]:
    """Find regions this product refuses to reconstruct over.

    ``candidate_boxes`` narrows the scan to the areas a user has actually
    selected; when omitted the whole image is scanned so the editor can show
    warning overlays before any mask exists.
    """
    config = config or DetectionConfig()
    gray = _to_gray(rgb)
    height, width = gray.shape[:2]
    image_area = float(height * width)
    found: list[Region] = []

    # 1. Metadata-derived provenance. Whole-image scope: an image carrying
    #    Content Credentials keeps them, and any visible credential badge is
    #    treated as protected.
    if provenance and provenance.get("has_any"):
        reasons = []
        if provenance.get("has_c2pa"):
            reasons.append("Content Credentials (C2PA) manifest")
        if provenance.get("has_xmp_rights"):
            reasons.append("XMP rights metadata")
        if provenance.get("has_iptc"):
            reasons.append("IPTC rights block")
        if provenance.get("exif_rights"):
            reasons.append("EXIF authorship fields")
        found.append(
            Region(
                kind="provenance_label",
                x=0,
                y=0,
                width=int(width),
                height=int(height),
                confidence=0.99,
                reason=(
                    "This image carries provenance metadata ("
                    + ", ".join(reasons)
                    + "). It is preserved on every export and cannot be removed here."
                ),
                evidence={"provenance": provenance, "scope": "metadata"},
            )
        )

    # 2. Whole-image stock watermark: a large, repeating, low-contrast overlay.
    pattern = _repeated_pattern_score(gray, config)
    if pattern["score"] >= 0.5:
        found.append(
            Region(
                kind="stock_watermark",
                x=0,
                y=0,
                width=int(width),
                height=int(height),
                confidence=min(0.95, 0.55 + pattern["score"] / 2.0),
                reason=(
                    "A large repeating overlay covering the image was detected. This looks like a "
                    "stock-agency or licensing watermark, which this product does not remove."
                ),
                evidence=pattern,
            )
        )

    # 3. Region-level scan.
    boxes: list[tuple[int, int, int, int]]
    if candidate_boxes is not None:
        boxes = [tuple(int(v) for v in box) for box in candidate_boxes]  # type: ignore[misc]
    else:
        boxes = [region.box for region in detect_overlay_candidates(rgb, config, limit=40)]

    for box in boxes:
        x, y, w, h = box
        x = max(0, min(int(x), width - 1))
        y = max(0, min(int(y), height - 1))
        w = max(1, min(int(w), width - x))
        h = max(1, min(int(h), height - y))
        area = float(w * h)
        if area < config.min_region_area:
            continue

        crop = gray[y : y + h, x : x + w]
        ink = _ink_mask(crop)
        stats = stroke_statistics(ink)
        placed, placement = _in_corner_or_bottom((x, y, w, h), (height, width), config)
        aspect = w / float(h)

        # 3a. Large overlay spanning the frame -> stock/agency style mark.
        if area / image_area >= config.stock_area_fraction or (
            w >= width * config.stock_span_fraction and h >= height * 0.12
        ):
            found.append(
                Region(
                    kind="stock_watermark",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    confidence=0.85,
                    reason=(
                        "The selection covers a large overlay spanning much of the frame, which "
                        "matches a stock-provider or agency watermark."
                    ),
                    evidence={"area_fraction": round(area / image_area, 4), **stats},
                )
            )
            continue

        text = _ocr_text(crop) if config.ocr_enabled else None
        keyword = _keyword_hit(text)
        if keyword:
            kind = "copyright_notice"
            if keyword in ("getty", "gettyimages", "shutterstock", "adobe stock", "istock",
                           "istockphoto", "alamy", "depositphotos", "dreamstime", "123rf"):
                kind = "agency_mark"
            elif keyword in ("content credentials", "c2pa"):
                kind = "provenance_label"
            found.append(
                Region(
                    kind=kind,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    confidence=0.95,
                    reason=(
                        f"Text in this region reads as attribution or licensing content "
                        f"(matched '{keyword}')."
                    ),
                    evidence={"matched_keyword": keyword, **stats},
                )
            )
            continue

        # 3b. Copyright-notice geometry: a short line of small uniform glyphs
        #     sitting in a margin or corner.
        if (
            placed
            and stats["component_count"] >= 4
            and stats["stroke_variation"] < 0.55
            and 2.0 <= aspect <= 30.0
            and h <= height * 0.06
            and area / image_area < 0.06
        ):
            found.append(
                Region(
                    kind="copyright_notice",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    confidence=0.62,
                    severity=SEVERITY_REVIEW,
                    reason=(
                        f"A short line of small, evenly-weighted glyphs in the {placement} matches "
                        "the shape of a credit or copyright line. A date stamp has the same shape, "
                        "so confirm this is not attribution content before cleaning it."
                    ),
                    evidence={"placement": placement, "aspect_ratio": round(aspect, 2), **stats},
                )
            )
            continue

        # 3c. Signature: one long continuous handwritten trace in a corner or
        #     bottom margin. The trace metrics - not stroke darkness - carry
        #     this decision, so it survives painted and photographic surfaces.
        trace = trace_statistics(crop)
        if (
            placed
            and trace["trace_span_ratio"] >= config.signature_min_span_ratio
            and trace["longest_trace_ratio"] >= config.signature_min_trace_ratio
            and trace["contour_count"] <= config.signature_max_contours
            and trace["axis_alignment"] <= config.signature_max_axis_alignment
            and stats["ink_ratio"] <= config.signature_max_ink_ratio
            and 1.2 <= aspect <= 14.0
            and area / image_area <= config.signature_max_area_fraction
        ):
            confidence = 0.6 + min(0.33, trace["longest_trace_ratio"] / 10.0)
            found.append(
                Region(
                    kind="signature",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    confidence=round(min(0.93, confidence), 3),
                    reason=(
                        f"Sparse, thin, continuously varying strokes in the {placement} match the "
                        "shape of a handwritten artist signature."
                    ),
                    evidence={
                        "placement": placement,
                        "aspect_ratio": round(aspect, 2),
                        **stats,
                        **trace,
                    },
                )
            )

    found.sort(key=lambda region: region.confidence, reverse=True)
    return found


@dataclass(slots=True)
class ProtectionAssessment:
    """The result of checking a user mask against protected regions."""

    blocked: bool
    regions: list[Region] = field(default_factory=list)
    overlaps: list[dict] = field(default_factory=list)
    requires_acknowledgement: bool = False

    @property
    def blocking_overlaps(self) -> list[dict]:
        return [item for item in self.overlaps if item["severity"] == SEVERITY_BLOCK]

    @property
    def review_overlaps(self) -> list[dict]:
        return [item for item in self.overlaps if item["severity"] == SEVERITY_REVIEW]

    @property
    def unacknowledged_kinds(self) -> list[str]:
        return sorted({item["kind"] for item in self.review_overlaps if not item["acknowledged"]})

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "requires_acknowledgement": self.requires_acknowledgement,
            "unacknowledged_kinds": self.unacknowledged_kinds,
            "regions": [region.to_dict() for region in self.regions],
            "overlaps": self.overlaps,
            "explanation": self.explanation,
        }

    @property
    def explanation(self) -> str:
        readable = {
            "signature": "an artist signature",
            "copyright_notice": "a copyright or credit line",
            "stock_watermark": "a stock-provider watermark",
            "agency_mark": "an agency mark",
            "provenance_label": "a provenance / Content Credentials label",
        }
        blocking = self.blocking_overlaps
        if blocking:
            described = ", ".join(
                readable.get(kind, kind) for kind in sorted({item["kind"] for item in blocking})
            )
            return (
                f"The selection overlaps {described}. ArtRestore Studio only performs authorized "
                "cleanup that does not obscure attribution or provenance, so this region is left "
                "untouched. Adjust the mask to exclude it. If this detection is wrong for your own "
                "artwork, contact support - it is not something this app lets you override."
            )
        if self.requires_acknowledgement:
            described = ", ".join(readable.get(kind, kind) for kind in self.unacknowledged_kinds)
            return (
                f"The selection may overlap {described}. This shape is ambiguous - a date stamp and "
                "a credit line look alike - so processing is paused. Confirm that the region is not "
                "attribution content to continue, or adjust the mask to exclude it."
            )
        return "No attribution or provenance content was detected inside the selection."


def assess_mask(
    binary_mask: np.ndarray,
    regions: list[Region],
    *,
    overlap_threshold: float = 0.06,
    block_kinds: tuple[str, ...] = PROTECTED_KINDS,
    enforcement: str = "block",
    acknowledged_kinds: Iterable[str] | None = None,
) -> ProtectionAssessment:
    """Check a user mask against detected protected regions.

    A whole-image ``provenance_label`` never blocks on its own - preserving
    metadata is handled by the export path - but a mask that targets a
    *visible* credential badge or a signature does.

    ``acknowledged_kinds`` lists region kinds the user has explicitly attested
    are not attribution content. Acknowledgements only ever clear ``review``
    severity findings; ``block`` severity cannot be acknowledged away.
    """
    acknowledged = set(acknowledged_kinds or ())
    mask_bool = binary_mask > 0
    mask_area = float(mask_bool.sum())
    overlaps: list[dict] = []
    if mask_area <= 0:
        return ProtectionAssessment(blocked=False, regions=regions, overlaps=[])

    height, width = binary_mask.shape[:2]
    image_area = float(height * width)

    for region in regions:
        if region.kind not in block_kinds:
            continue
        region_mask = region.to_mask((height, width)) > 0
        region_area = float(region_mask.sum())
        if region_area <= 0:
            continue
        intersection = float(np.logical_and(mask_bool, region_mask).sum())
        if intersection <= 0:
            continue

        share_of_mask = intersection / mask_area
        share_of_region = intersection / region_area
        whole_image = region_area >= image_area * 0.98

        if whole_image and region.kind == "provenance_label":
            # Metadata-only provenance: informational, preserved on export.
            continue

        significant = (
            whole_image
            or share_of_region >= overlap_threshold
            or share_of_mask >= overlap_threshold
        )
        if not significant:
            continue

        overlaps.append(
            {
                "kind": region.kind,
                "severity": region.severity,
                "confidence": region.confidence,
                "share_of_mask": round(share_of_mask, 4),
                "share_of_region": round(share_of_region, 4),
                "acknowledged": region.severity == SEVERITY_REVIEW and region.kind in acknowledged,
                "reason": region.reason,
            }
        )

    assessment = ProtectionAssessment(blocked=False, regions=regions, overlaps=overlaps)
    if enforcement != "block":
        # Warn-only deployments surface everything without stopping the job.
        return assessment

    assessment.requires_acknowledgement = bool(assessment.unacknowledged_kinds)
    assessment.blocked = bool(assessment.blocking_overlaps) or assessment.requires_acknowledgement
    return assessment


def subtract_protected(binary_mask: np.ndarray, overlaps_regions: list[Region]) -> np.ndarray:
    """Return the mask with protected areas removed (non-destructive preview)."""
    result = binary_mask.copy()
    height, width = binary_mask.shape[:2]
    for region in overlaps_regions:
        if region.kind not in PROTECTED_KINDS:
            continue
        if region.width >= width * 0.98 and region.height >= height * 0.98:
            continue
        result[region.y : region.y + region.height, region.x : region.x + region.width] = 0
    return result
