"""Simulated drawing strokes.

Revealing an image through a uniform mask looks like a wipe, not like drawing.
These strokes are generated from the artwork's own structure: seeds are placed
where there is something to draw, each stroke walks along the local edge
orientation, and width, speed and opacity vary per stroke. The result reads as
marks being made rather than as a curtain rising.

Nothing here claims to be a record of real input. Stroke order is synthesised,
and the renderer labels it as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .analysis import ArtworkAnalysis


@dataclass(slots=True)
class Stroke:
    """One simulated mark."""

    points: list[tuple[int, int]]
    width: float
    opacity: float
    speed: float
    order: float = 0.0  # 0..1 position in the drawing sequence

    @property
    def length(self) -> float:
        total = 0.0
        for index in range(1, len(self.points)):
            ax, ay = self.points[index - 1]
            bx, by = self.points[index]
            total += math.hypot(bx - ax, by - ay)
        return total

    def to_dict(self) -> dict:
        return {
            "points": self.points,
            "width": round(self.width, 2),
            "opacity": round(self.opacity, 3),
            "speed": round(self.speed, 3),
            "order": round(self.order, 5),
        }

    def to_svg_path(self) -> str:
        """An SVG path for the optional vector export of a stroke pass."""
        if not self.points:
            return ""
        head = f"M {self.points[0][0]} {self.points[0][1]}"
        tail = " ".join(f"L {x} {y}" for x, y in self.points[1:])
        return f"{head} {tail}".strip()


@dataclass(slots=True)
class StrokeField:
    strokes: list[Stroke] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.strokes)

    def to_svg(self, width: int, height: int, colour: str = "#2c2c2c") -> str:
        paths = "\n".join(
            f'  <path d="{stroke.to_svg_path()}" stroke="{colour}" '
            f'stroke-width="{stroke.width:.2f}" stroke-opacity="{stroke.opacity:.2f}" '
            f'fill="none" stroke-linecap="round" />'
            for stroke in self.strokes
            if stroke.points
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n{paths}\n</svg>'
        )


#: How each pass chooses where to draw.
PASS_WEIGHTS = {
    "structure": {"edges": 1.0, "detail": 0.2, "subject": 0.4, "scale_bias": -0.6},
    "mass": {"edges": 0.2, "detail": 0.1, "subject": 0.9, "scale_bias": -1.0},
    "detail": {"edges": 0.6, "detail": 1.0, "subject": 0.5, "scale_bias": 1.0},
}


def generate_strokes(
    analysis: ArtworkAnalysis,
    *,
    pass_name: str = "structure",
    density: float = 1.0,
    brush_min: float = 6.0,
    brush_max: float = 48.0,
    seed: int = 0,
    max_strokes: int = 4000,
) -> StrokeField:
    """Build a stroke field for one drawing pass. Deterministic for a seed."""
    rng = np.random.default_rng(seed + hash(pass_name) % 10_000)
    height, width = analysis.rgb.shape[:2]
    weights = PASS_WEIGHTS.get(pass_name, PASS_WEIGHTS["structure"])

    edge_field = cv2.GaussianBlur((analysis.edges > 0).astype(np.float32), (0, 0), 2.0)
    interest = (
        edge_field * weights["edges"]
        + analysis.detail_map * weights["detail"]
        + analysis.subject_mask * weights["subject"]
    )
    interest = np.clip(interest, 1e-4, None)
    interest /= interest.sum()

    area = height * width
    base_count = int(np.clip(area / 900.0 * density, 60, max_strokes))
    flat_index = rng.choice(area, size=base_count, replace=True, p=interest.reshape(-1))
    seeds_y, seeds_x = np.unravel_index(flat_index, (height, width))

    diagonal = math.hypot(height, width)
    strokes: list[Stroke] = []
    for index in range(base_count):
        start = (int(seeds_x[index]), int(seeds_y[index]))
        local_scale = float(analysis.scale_map[start[1], start[0]])
        # Broad passes make long fat marks; detail passes make short fine ones.
        scale_factor = 1.0 - abs(weights["scale_bias"]) * abs(
            local_scale + weights["scale_bias"] / 2
        )
        scale_factor = float(np.clip(scale_factor, 0.2, 1.0))

        stroke_width = float(
            np.clip(
                brush_min + (brush_max - brush_min) * scale_factor * rng.uniform(0.4, 1.0),
                brush_min,
                brush_max,
            )
        )
        step_count = int(np.clip(diagonal * 0.03 * scale_factor * rng.uniform(0.6, 1.8), 4, 90))
        points = _walk(analysis.orientation, start, step_count, rng, width, height)
        if len(points) < 2:
            continue

        strokes.append(
            Stroke(
                points=points,
                width=stroke_width,
                opacity=float(np.clip(rng.normal(0.85, 0.12), 0.3, 1.0)),
                speed=float(np.clip(rng.normal(1.0, 0.28), 0.35, 2.5)),
            )
        )

    _assign_order(strokes, analysis, pass_name, rng)
    return StrokeField(strokes=strokes)


def _walk(
    orientation: np.ndarray,
    start: tuple[int, int],
    steps: int,
    rng: np.random.Generator,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Follow the local edge direction, with a little hand-wobble."""
    x, y = float(start[0]), float(start[1])
    points: list[tuple[int, int]] = [(int(x), int(y))]
    step_length = 2.4
    direction = float(orientation[start[1], start[0]])

    for _ in range(steps):
        target = float(orientation[int(np.clip(y, 0, height - 1)), int(np.clip(x, 0, width - 1))])
        # Turn toward the local direction rather than snapping to it.
        delta = math.atan2(math.sin(target - direction), math.cos(target - direction))
        direction += delta * 0.45 + float(rng.normal(0.0, 0.09))

        x += math.cos(direction) * step_length
        y += math.sin(direction) * step_length
        if not (0 <= x < width and 0 <= y < height):
            break
        points.append((int(x), int(y)))
    return points


def _assign_order(
    strokes: list[Stroke], analysis: ArtworkAnalysis, pass_name: str, rng: np.random.Generator
) -> None:
    """Decide the drawing sequence.

    Structure passes work outside-in from the largest forms; detail passes work
    from the focal point outward. Both get jitter so the order never looks
    mechanical.
    """
    if not strokes:
        return
    scores = []
    for stroke in strokes:
        x, y = stroke.points[0]
        saliency = float(analysis.saliency[y, x])
        scale = float(analysis.scale_map[y, x])
        if pass_name == "detail":
            score = (1.0 - saliency) * 0.7 + scale * 0.3
        elif pass_name == "mass":
            score = scale * 0.8 + (1.0 - saliency) * 0.2
        else:
            score = scale * 0.5 + float(y) / max(1, analysis.rgb.shape[0]) * 0.3
        scores.append(score + float(rng.normal(0.0, 0.12)))

    order = np.argsort(scores)
    total = float(len(strokes))
    for position, index in enumerate(order):
        strokes[index].order = position / total


def render_strokes(
    canvas: np.ndarray,
    target: np.ndarray,
    field: StrokeField,
    progress: float,
    *,
    soft_edge: float = 0.6,
) -> np.ndarray:
    """Paint the strokes whose turn has come, sampling colour from the artwork.

    Each stroke reveals the *target* pixels beneath it, so the marks carry the
    artwork's real colour rather than a synthetic ink.
    """
    progress = float(np.clip(progress, 0.0, 1.0))
    if not field.strokes or progress <= 0:
        return canvas

    mask = np.zeros(canvas.shape[:2], dtype=np.float32)
    for stroke in field.strokes:
        if stroke.order > progress:
            continue
        # Strokes near the front of the window are still being drawn.
        local = (progress - stroke.order) * max(0.2, stroke.speed) * 6.0
        fraction = float(np.clip(local, 0.0, 1.0))
        if fraction <= 0:
            continue
        count = max(2, int(len(stroke.points) * fraction))
        polyline = np.array(stroke.points[:count], dtype=np.int32)
        cv2.polylines(
            mask,
            [polyline],
            isClosed=False,
            color=float(stroke.opacity),
            thickness=max(1, int(round(stroke.width))),
            lineType=cv2.LINE_AA,
        )

    if soft_edge > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), soft_edge)
    alpha = np.clip(mask, 0.0, 1.0)[:, :, None]
    blended = target.astype(np.float32) * alpha + canvas.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)
