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
import zlib
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
    # zlib.crc32 rather than hash(): str hashing is salted per process, and a
    # stroke field must be identical for a given seed on every render.
    rng = np.random.default_rng(seed + zlib.crc32(pass_name.encode()) % 10_000)
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
        # A mark shorter than it is wide reads as a blob, not a stroke: keep
        # the walk long enough for at least ~2.5 brush-widths of travel.
        step_length = 2.4
        min_steps = int(math.ceil(stroke_width * 2.5 / step_length))
        step_count = int(
            np.clip(diagonal * 0.03 * scale_factor * rng.uniform(0.6, 1.8), min_steps, 140)
        )
        points = _walk(analysis.orientation, start, step_count, rng, width, height)
        if len(points) < 2 or _path_length(points) < stroke_width * 1.6:
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


def generate_fill_strokes(
    analysis: ArtworkAnalysis,
    *,
    density: float = 1.0,
    brush_min: float = 6.0,
    brush_max: float = 48.0,
    seed: int = 0,
    max_strokes: int = 4000,
) -> StrokeField:
    """Strokes that block in the base colours, one colour region at a time.

    This is how a painter lays in flats: pick a colour, fill its shapes with
    directional strokes, move to the next. Each palette region gets its own
    brush angle (the region's long axis), strokes are clipped to the region so
    colour never bleeds across an edge, and the drawing order runs largest
    colour group to smallest with a row-by-row sweep inside each group.
    """
    rng = np.random.default_rng(seed + 4241)
    height, width = analysis.rgb.shape[:2]
    # Gradient areas quantise to speckly labels; a median pass merges the
    # speckle so strokes run long instead of stopping at every stray pixel.
    labels = cv2.medianBlur(analysis.palette_labels.astype(np.uint8), 5).astype(np.int32)
    group_count = int(labels.max()) + 1
    area = height * width

    total_budget = int(np.clip(area / 1400.0 * density, 80, max_strokes))
    strokes: list[Stroke] = []

    for group in range(group_count):
        mask = labels == group
        share = float(mask.mean())
        if share < 0.002:
            continue

        ys, xs = np.nonzero(mask)
        # The region's long axis, from the covariance of its pixel positions.
        if len(xs) > 8:
            centred = np.stack([xs - xs.mean(), ys - ys.mean()]).astype(np.float32)
            cov = centred @ centred.T / len(xs)
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            principal = eigenvectors[:, int(np.argmax(eigenvalues))]
            base_angle = float(math.atan2(principal[1], principal[0]))
        else:
            base_angle = float(rng.uniform(0, math.pi))

        count = max(6, int(total_budget * share))
        picks = rng.choice(len(xs), size=min(count, len(xs)), replace=False)
        # Bigger colour masses take a bigger brush.
        stroke_width = float(
            np.clip(brush_min + (brush_max - brush_min) * math.sqrt(share), brush_min, brush_max)
        )

        # Row-by-row inside the group: order by position perpendicular to the
        # brush angle, so the colour sweeps across its shapes like passes of a
        # loaded brush rather than popping in at random.
        perpendicular = (
            xs[picks] * -math.sin(base_angle) + ys[picks] * math.cos(base_angle)
        ).astype(np.float32)
        row_order = np.argsort(np.argsort(perpendicular)).astype(np.float32)
        row_order /= float(max(1, len(picks) - 1))

        for index, pick in enumerate(picks):
            start = (int(xs[pick]), int(ys[pick]))
            wobble = float(rng.normal(0.0, 0.16))
            points = _walk_in_region(
                labels, group, start, base_angle + wobble, stroke_width, rng, width, height
            )
            if len(points) < 2:
                continue
            strokes.append(
                Stroke(
                    points=points,
                    width=stroke_width,
                    opacity=float(np.clip(rng.normal(0.9, 0.08), 0.5, 1.0)),
                    speed=float(np.clip(rng.normal(1.0, 0.25), 0.4, 2.2)),
                    # Group-major, row-minor with jitter: the group index sets
                    # which colour is being laid in, the row sets the pass.
                    order=(group + float(row_order[index]) * 0.9 + float(rng.uniform(0.0, 0.08))),
                )
            )

    # Normalise the composite keys onto 0..1 while preserving their order.
    if strokes:
        ranks = np.argsort(np.argsort([stroke.order for stroke in strokes]))
        for stroke, rank in zip(strokes, ranks, strict=True):
            stroke.order = float(rank) / float(len(strokes))
    return StrokeField(strokes=strokes)


def _walk_in_region(
    labels: np.ndarray,
    group: int,
    start: tuple[int, int],
    angle: float,
    width_hint: float,
    rng: np.random.Generator,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """A straight-ish stroke that stops at its colour region's boundary."""
    x, y = float(start[0]), float(start[1])
    points: list[tuple[int, int]] = [(int(x), int(y))]
    step = 2.4
    direction = angle
    max_steps = int(max(28, width_hint * 3.5 / step))
    off_region = 0

    for _ in range(max_steps):
        direction += float(rng.normal(0.0, 0.05))
        x += math.cos(direction) * step
        y += math.sin(direction) * step
        if not (0 <= x < width and 0 <= y < height):
            break
        if labels[int(y), int(x)] != group:
            # Tolerate a few stray pixels of another label; end the stroke
            # only once it has genuinely left its colour region.
            off_region += 1
            if off_region > 3:
                break
            continue
        off_region = 0
        points.append((int(x), int(y)))
    return points


def _path_length(points: list[tuple[int, int]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        ax, ay = points[index - 1]
        bx, by = points[index]
        total += math.hypot(bx - ax, by - ay)
    return total


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
