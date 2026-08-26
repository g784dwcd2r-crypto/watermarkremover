"""A single simulated pen.

The sketch stages used to reveal many lines at once, which no hand can do.
This module turns a line image into an ordered list of pen strokes - by
thinning the lines to centrelines, walking them as a graph, and joining
segments the way a moving pen would - then animates one pen tip along them.
At any instant exactly one stroke is partially drawn; everything else is
either finished or untouched.

Deterministic for a seed, like the rest of the renderer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# -- thinning ---------------------------------------------------------------


def _zhang_suen_tables() -> tuple[np.ndarray, np.ndarray]:
    """Deletion lookup tables for the two Zhang-Suen sub-iterations.

    Indexed by the 8-neighbourhood code with bit order P2..P9 clockwise:
    bit0=N, bit1=NE, bit2=E, bit3=SE, bit4=S, bit5=SW, bit6=W, bit7=NW.
    """
    first_pass = np.zeros(256, np.uint8)
    second_pass = np.zeros(256, np.uint8)
    for code in range(256):
        p = [(code >> bit) & 1 for bit in range(8)]
        neighbours = sum(p)
        transitions = sum(1 for i in range(8) if p[i] == 0 and p[(i + 1) % 8] == 1)
        if 2 <= neighbours <= 6 and transitions == 1:
            if p[0] * p[2] * p[4] == 0 and p[2] * p[4] * p[6] == 0:
                first_pass[code] = 1
            if p[0] * p[2] * p[6] == 0 and p[0] * p[4] * p[6] == 0:
                second_pass[code] = 1
    return first_pass, second_pass


_ZS_TABLES = _zhang_suen_tables()

#: Correlation kernel producing the neighbourhood code above: the entry at a
#: neighbour's offset holds that neighbour's bit value.
_ZS_KERNEL = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], dtype=np.float32)


def _thin(binary: np.ndarray, max_iterations: int = 60) -> np.ndarray:
    """Zhang-Suen thinning, vectorised. Input/output are 0/1 uint8."""
    image = binary.astype(np.uint8).copy()
    for _ in range(max_iterations):
        changed = False
        for table in _ZS_TABLES:
            codes = cv2.filter2D(
                image.astype(np.float32), -1, _ZS_KERNEL, borderType=cv2.BORDER_CONSTANT
            ).astype(np.int32)
            remove = (image == 1) & (table[np.clip(codes, 0, 255)] == 1)
            if remove.any():
                image[remove] = 0
                changed = True
        if not changed:
            break
    return image


# -- stroke extraction ------------------------------------------------------

_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def extract_strokes(
    lines: np.ndarray,
    *,
    rng: np.random.Generator,
    min_length: int = 4,
) -> list[np.ndarray]:
    """Turn a line image into pen strokes: ordered (x, y) polylines.

    The lines are thinned to centrelines, the skeleton is walked as a graph
    (cut at junctions, so crossing lines become separate marks), and segments
    that meet end-to-end at a shallow angle are joined into single strokes,
    because a real pen draws them in one motion.
    """
    binary = (lines.astype(np.float32) > (60 if lines.max() > 1.5 else 0.24)).astype(np.uint8)
    if not binary.any():
        return []
    skeleton = _thin(binary)

    height, width = skeleton.shape
    neighbour_count = cv2.filter2D(
        skeleton.astype(np.float32), -1, np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32)
    )
    on = skeleton == 1
    junctions = on & (neighbour_count >= 3)
    visited = np.zeros_like(skeleton, dtype=bool)
    visited[junctions] = True  # junction pixels separate segments

    def _walk(start_y: int, start_x: int) -> list[tuple[int, int]]:
        path = [(start_x, start_y)]
        visited[start_y, start_x] = True
        y, x = start_y, start_x
        while True:
            step = None
            for dy, dx in _OFFSETS:
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and on[ny, nx] and not visited[ny, nx]:
                    step = (ny, nx)
                    break
            if step is None:
                break
            y, x = step
            visited[y, x] = True
            path.append((x, y))
        return path

    endpoints = np.argwhere(on & (neighbour_count == 1))
    segments: list[list[tuple[int, int]]] = []
    for y, x in endpoints:
        if not visited[y, x]:
            segments.append(_walk(int(y), int(x)))
    # Pixels adjacent to junctions start the segments the endpoint pass missed.
    junction_neighbours = np.argwhere(
        on
        & ~junctions
        & (cv2.filter2D(junctions.astype(np.float32), -1, np.ones((3, 3), np.float32)) > 0)
    )
    for y, x in junction_neighbours:
        if not visited[y, x]:
            segments.append(_walk(int(y), int(x)))
    # Loops with no endpoints or junctions (a drawn circle).
    remaining = np.argwhere(on & ~visited)
    for y, x in remaining:
        if not visited[y, x]:
            segments.append(_walk(int(y), int(x)))

    segments = [segment for segment in segments if len(segment) >= min_length]

    # Join segments end-to-end where a pen would keep moving: their meeting
    # ends are close and the direction carries through.
    strokes = _join_segments(segments)
    rng.shuffle(strokes)  # neutral starting order; the tour decides the rest
    return [np.asarray(stroke, dtype=np.float32) for stroke in strokes]


def _tangent(path: list[tuple[int, int]], at_end: bool) -> tuple[float, float]:
    span = min(6, len(path) - 1)
    if at_end:
        (x0, y0), (x1, y1) = path[-1 - span], path[-1]
    else:
        (x0, y0), (x1, y1) = path[span], path[0]
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    return ((x1 - x0) / length, (y1 - y0) / length)


def _join_segments(segments: list[list[tuple[int, int]]]) -> list[list[tuple[int, int]]]:
    strokes = [list(segment) for segment in segments]
    joined = True
    while joined:
        joined = False
        for i in range(len(strokes)):
            if strokes[i] is None:
                continue
            for j in range(len(strokes)):
                if i == j or strokes[j] is None:
                    continue
                a, b = strokes[i], strokes[j]
                ax, ay = a[-1]
                bx, by = b[0]
                if abs(ax - bx) > 3 or abs(ay - by) > 3:
                    continue
                tx, ty = _tangent(a, at_end=True)
                ux, uy = _tangent(b, at_end=False)
                if tx * ux + ty * uy < 0.55:  # ~<57 degrees of turn: pen continues
                    continue
                strokes[i] = a + b
                strokes[j] = None
                joined = True
                break
    return [stroke for stroke in strokes if stroke is not None]


# -- the pen plan -----------------------------------------------------------


@dataclass(slots=True)
class PenPlan:
    """One pen's complete journey across a stage, in drawing order."""

    strokes: list[np.ndarray]  # (N, 2) float32 (x, y) paths, in order
    lengths: np.ndarray  # arc length of each stroke
    costs: np.ndarray  # time cost of each stroke (length / its speed factor)
    hops: np.ndarray  # travel cost before each stroke
    widths: np.ndarray  # the drawn line's local thickness along each stroke
    #: For every line pixel, the index of the stroke whose completion reveals
    #: it (-1 off the lines). Guarantees the drawing is exactly complete when
    #: the pen finishes, however thick or speckled the ink is.
    territory: np.ndarray | None = None
    starts: np.ndarray = field(init=False)  # cumulative start, in cost units
    total: float = field(init=False, default=1.0)

    def __post_init__(self) -> None:
        cumulative = np.cumsum(self.hops + self.costs)
        self.starts = cumulative - self.costs
        self.total = float(cumulative[-1]) if len(cumulative) else 1.0


def plan_pen(
    lines: np.ndarray,
    *,
    rng: np.random.Generator,
    speed_variation: float = 0.2,
) -> PenPlan:
    """Extract strokes and order them the way a hand travels.

    Greedy nearest-neighbour from wherever the pen last lifted, trying both
    ends of every candidate stroke - so the hand finishes a neighbourhood
    before hopping across the canvas, and never draws two things at once.
    """
    strokes = extract_strokes(lines, rng=rng)
    if not strokes:
        empty = np.zeros(0, np.float32)
        return PenPlan(strokes=[], lengths=empty, costs=empty, hops=empty, widths=empty)

    # The corridor each stroke reveals must cover the drawn line's real
    # thickness - a fat mark thins to one skeleton path, but the pen that
    # made it was wide.
    binary = (lines.astype(np.float32) > (60 if lines.max() > 1.5 else 0.24)).astype(np.uint8)
    thickness = cv2.distanceTransform(binary, cv2.DIST_L2, 3)

    remaining = list(range(len(strokes)))
    heads = np.array([stroke[0] for stroke in strokes], np.float32)
    tails = np.array([stroke[-1] for stroke in strokes], np.float32)

    ordered: list[np.ndarray] = []
    hops: list[float] = []
    # Start with the stroke nearest the top-left, like a page being begun.
    position = np.array([0.0, 0.0], np.float32)
    while remaining:
        head_d = np.linalg.norm(heads[remaining] - position, axis=1)
        tail_d = np.linalg.norm(tails[remaining] - position, axis=1)
        best = int(np.argmin(np.minimum(head_d, tail_d)))
        index = remaining.pop(best)
        stroke = strokes[index]
        if tail_d[best] < head_d[best]:
            stroke = stroke[::-1]
        hop = float(min(head_d[best], tail_d[best]))
        # The pen moves ~3x faster through the air, and a long reach never
        # costs more than a beat.
        hops.append(min(hop / 3.0, 60.0))
        ordered.append(stroke)
        position = stroke[-1]

    lengths = np.array(
        [float(np.hypot(*np.diff(stroke, axis=0).T).sum()) for stroke in ordered], np.float32
    )
    lengths = np.maximum(lengths, 1.0)
    factors = rng.uniform(1.0 - speed_variation, 1.0 + speed_variation, len(ordered)).astype(
        np.float32
    )
    # Assign every inked pixel to its nearest stroke: that stroke's
    # completion reveals it. Speckles too small to be strokes of their own
    # are revealed by whichever neighbour the hand was closest to.
    height, width = binary.shape
    stroke_pixels = np.zeros((height, width), np.uint8)
    owner_at = np.full((height, width), -1, np.int32)
    for index, stroke in enumerate(ordered):
        xs = np.clip(stroke[:, 0].astype(int), 0, width - 1)
        ys = np.clip(stroke[:, 1].astype(int), 0, height - 1)
        stroke_pixels[ys, xs] = 1
        owner_at[ys, xs] = index
    _, nearest = cv2.distanceTransformWithLabels(
        (1 - stroke_pixels).astype(np.uint8),
        cv2.DIST_L2,
        3,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    label_owner = np.full(int(nearest.max()) + 1, -1, np.int32)
    sy, sx = np.nonzero(stroke_pixels)
    label_owner[nearest[sy, sx]] = owner_at[sy, sx]
    territory = np.where(binary > 0, label_owner[nearest], -1).astype(np.int32)

    widths = np.array(
        [
            2.0
            * float(
                np.median(
                    thickness[
                        np.clip(stroke[:, 1].astype(int), 0, height - 1),
                        np.clip(stroke[:, 0].astype(int), 0, width - 1),
                    ]
                )
            )
            + 2.0
            for stroke in ordered
        ],
        np.float32,
    )
    return PenPlan(
        strokes=ordered,
        lengths=lengths,
        costs=lengths / factors,
        hops=np.array(hops, np.float32),
        widths=np.clip(widths, 3.0, 28.0),
        territory=territory,
    )


def render_pen(
    underlay: np.ndarray,
    target: np.ndarray,
    plan: PenPlan,
    progress: float,
    *,
    cache: dict,
    line_width: int = 5,
) -> np.ndarray:
    """Show the target's lines only where the pen has physically been.

    The cache carries the corridor mask between frames; each call stamps just
    the newly traversed portion, so a frame costs one short polyline draw.
    """
    height, width = underlay.shape[:2]
    if "mask" not in cache:
        cache["mask"] = np.zeros((height, width), np.uint8)
        cache["done"] = 0  # fully stamped strokes
        cache["partial"] = 0  # points stamped of the current stroke
    mask = cache["mask"]

    units = float(np.clip(progress, 0.0, 1.0)) * plan.total
    for index in range(cache["done"], len(plan.strokes)):
        start = float(plan.starts[index])
        if units <= start:
            break
        stroke = plan.strokes[index]
        fraction = float(np.clip((units - start) / float(plan.costs[index]), 0.0, 1.0))
        count = max(2, int(round(len(stroke) * fraction)))
        begin = cache["partial"] if index == cache["done"] else 0
        if count > begin:
            portion = stroke[max(0, begin - 1) : count].astype(np.int32)
            stroke_width = max(line_width, int(round(float(plan.widths[index]))))
            cv2.polylines(mask, [portion], False, 255, stroke_width, cv2.LINE_AA)
        if fraction >= 1.0:
            if plan.territory is not None:
                # The finished mark reveals its full territory, so thick ink
                # and speckle around the centreline complete with the stroke.
                mask[plan.territory == index] = 255
            cache["done"] = index + 1
            cache["partial"] = 0
        else:
            cache["done"] = index
            cache["partial"] = count
            break

    soft = cv2.GaussianBlur(mask, (0, 0), 0.8).astype(np.float32)[:, :, None] / 255.0
    return np.clip(
        target.astype(np.float32) * soft + underlay.astype(np.float32) * (1.0 - soft), 0, 255
    ).astype(np.uint8)
