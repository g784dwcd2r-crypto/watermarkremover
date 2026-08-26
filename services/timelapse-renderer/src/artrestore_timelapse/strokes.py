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
    #: Paint colour for fill strokes. None = the stroke reveals the target
    #: image instead of carrying its own pigment.
    colour: tuple[int, int, int] | None = None

    @property
    def length(self) -> float:
        total = 0.0
        for index in range(1, len(self.points)):
            ax, ay = self.points[index - 1]
            bx, by = self.points[index]
            total += math.hypot(bx - ax, by - ay)
        return total

    def to_dict(self) -> dict:
        payload = {
            "points": self.points,
            "width": round(self.width, 2),
            "opacity": round(self.opacity, 3),
            "speed": round(self.speed, 3),
            "order": round(self.order, 5),
        }
        if self.colour is not None:
            payload["colour"] = list(self.colour)
        return payload

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


def _schedule_hand_tour(
    strokes: list[Stroke],
    buckets: list[int],
    *,
    rng: np.random.Generator,
    late_indices: set[int] | None = None,
    late_fraction: float = 0.0,
    bucket_beat: float = 45.0,
) -> None:
    """Order and time the strokes the way one hand actually paints.

    Buckets (colour group x pass) are worked in order; inside each, the next
    stroke is whichever starts nearest to where the brush just lifted - the
    same nearest-neighbour tour the pen uses - reversing a stroke when its far
    end is the closer one. Timing is strictly one-in-flight: each stroke's
    window is its drawing cost, an air-travel beat proportional to the hop
    separates strokes, and a longer beat separates buckets.

    ``late_fraction`` sends some flagged gap-work strokes to a final bucket,
    like a hand going back over earlier areas before calling it done.
    """
    if not strokes:
        return
    bucket_keys = np.array(buckets, dtype=np.int64)
    if late_indices and late_fraction > 0:
        final = int(bucket_keys.max()) + 1
        for index in late_indices:
            if rng.random() < late_fraction:
                bucket_keys[index] = final

    position = np.array([0.0, 0.0], np.float32)
    schedule: list[tuple[int, float, float]] = []  # (stroke index, hop, window)
    for bucket in sorted({int(b) for b in bucket_keys}):
        members = [int(i) for i in np.flatnonzero(bucket_keys == bucket)]
        first_in_bucket = True
        while members:
            heads = np.array([strokes[i].points[0] for i in members], np.float32)
            tails = np.array([strokes[i].points[-1] for i in members], np.float32)
            head_d = np.linalg.norm(heads - position, axis=1)
            tail_d = np.linalg.norm(tails - position, axis=1)
            best = int(np.argmin(np.minimum(head_d, tail_d)))
            index = members.pop(best)
            stroke = strokes[index]
            if tail_d[best] < head_d[best]:
                stroke.points = stroke.points[::-1]
            hop = float(min(min(head_d[best], tail_d[best]) / 3.0, 60.0))
            if first_in_bucket:
                hop += bucket_beat
                first_in_bucket = False
            window = max(1.0, stroke.length + 2.0 * stroke.width)
            schedule.append((index, hop, window))
            position = np.asarray(stroke.points[-1], np.float32)

    total = sum(hop + window for _, hop, window in schedule) or 1.0
    cursor = 0.0
    for index, hop, window in schedule:
        cursor += hop
        stroke = strokes[index]
        stroke.order = float(cursor / total)
        # Complete the mark exactly within its own window: the brush lifts as
        # the next mark's travel begins.
        stroke.speed = float(np.clip(total / (6.0 * window), 0.05, 40000.0))
        cursor += window


#: The two passes a painter makes over each colour: a loose block-in with a
#: big brush, then a tighter fill that closes the gaps.
_FILL_PASSES = (
    {"brush_scale": 1.5, "share": 0.55, "opacity": 0.8},
    {"brush_scale": 0.85, "share": 0.45, "opacity": 0.92},
)


def generate_fill_strokes(
    analysis: ArtworkAnalysis,
    *,
    density: float = 1.0,
    brush_min: float = 6.0,
    brush_max: float = 48.0,
    seed: int = 0,
    max_strokes: int = 4000,
    region_filter: str = "all",
    pause_fraction: float = 0.04,
    late_touchup_fraction: float = 0.0,
) -> StrokeField:
    """Strokes that block in the base colours the way a painter lays flats.

    One colour at a time, two passes per colour (a loose block-in, then a
    fill), strokes following a direction field that hugs each shape's
    contours near its edges and relaxes to the shape's long axis inside,
    and each stroke loaded with its own slightly-varied pigment so the
    colour builds up instead of appearing flat.
    """
    rng = np.random.default_rng(seed + 4241)
    height, width = analysis.rgb.shape[:2]
    # Gradient areas quantise to speckly labels; a median pass merges the
    # speckle so strokes run long instead of stopping at every stray pixel.
    labels = cv2.medianBlur(analysis.palette_labels.astype(np.uint8), 5).astype(np.int32)
    group_count = int(labels.max()) + 1
    area = height * width

    total_budget = int(np.clip(area / 950.0 * density, 120, max_strokes))
    strokes: list[Stroke] = []
    gap_indices: set[int] = set()
    flat = analysis.flat_colours
    # Coarse occupancy grid: a painter keeps working a shape until it is
    # actually filled, so gap-filling strokes are added wherever the passes
    # left bare canvas.
    coarse = 3
    occupancy = np.zeros((height // coarse + 1, width // coarse + 1), np.uint8)

    def _mark(points: list[tuple[int, int]], stroke_width: float) -> None:
        # Credit only the opaque core: taper and soft edges leave the outer
        # band translucent, and counting it would leave pinholes unfilled.
        radius = max(1, int(stroke_width * 0.32 / coarse))
        for px, py in points[::2]:
            cv2.circle(occupancy, (px // coarse, py // coarse), radius, 1, -1)

    def _make_stroke(
        group: int,
        start: tuple[int, int],
        field: _DirectionField,
        stroke_width: float,
        opacity_mean: float,
        order_key: float,
    ) -> bool:
        points = _walk_field(labels, group, start, field, stroke_width, rng, width, height)
        if len(points) < 3:
            return False
        # A loaded brush never carries exactly the same mix twice.
        base_colour = flat[start[1], start[0]].astype(np.float32)
        tone = 1.0 + float(rng.normal(0.0, 0.045))
        jitter = rng.normal(0.0, 2.5, 3).astype(np.float32)
        colour = np.clip(base_colour * tone + jitter, 0, 255)
        strokes.append(
            Stroke(
                points=points,
                width=stroke_width,
                opacity=float(np.clip(rng.normal(opacity_mean, 0.06), 0.45, 1.0)),
                speed=float(np.clip(rng.normal(1.0, 0.25), 0.4, 2.2)),
                order=order_key,
                colour=(int(colour[0]), int(colour[1]), int(colour[2])),
            )
        )
        _mark(points, stroke_width)
        return True

    # A painter works the subject before the backdrop. Classify each colour
    # group by how much of it lies in the background, then order: subject
    # groups (largest first), background groups after - or only one side of
    # that split when the stage asks for it.
    subject_groups: list[int] = []
    background_groups: list[int] = []
    for group in range(group_count):
        selection = labels == group
        share = float(selection.mean())
        if share < 0.002:
            continue
        backgroundness = float(analysis.background_mask[selection].mean())
        # Only large, border-dominated fields count as background; a small
        # distinctive region is part of the subject even if it touches an
        # edge - a boat, a reflection, a tree line.
        is_background = backgroundness > 0.55 and share > 0.08
        (background_groups if is_background else subject_groups).append(group)
    if region_filter == "subject":
        ordered_groups = subject_groups
    elif region_filter == "background":
        ordered_groups = background_groups
    else:
        ordered_groups = subject_groups + background_groups

    for position, group in enumerate(ordered_groups):
        mask = labels == group
        share = float(mask.mean())
        ys, xs = np.nonzero(mask)
        field = _direction_field(mask, xs, ys, rng)
        base_width = float(
            np.clip(brush_min + (brush_max - brush_min) * math.sqrt(share), brush_min, brush_max)
        )
        sweep_angle = field.sweep_angle
        group_budget = max(10, int(total_budget * share))
        mask_coarse = mask[::coarse, ::coarse]

        for pass_index, fill_pass in enumerate(_FILL_PASSES):
            count = max(5, int(group_budget * fill_pass["share"]))
            picks = rng.choice(len(xs), size=min(count, len(xs)), replace=False)
            stroke_width = base_width * fill_pass["brush_scale"]

            # Row-by-row inside the pass: order along the sweep so each pass
            # moves across the shape like a hand, not like rainfall.
            perpendicular = (
                xs[picks] * -math.sin(sweep_angle) + ys[picks] * math.cos(sweep_angle)
            ).astype(np.float32)
            row_order = np.argsort(np.argsort(perpendicular)).astype(np.float32)
            row_order /= float(max(1, len(picks) - 1))

            for index, pick in enumerate(picks):
                _make_stroke(
                    group,
                    (int(xs[pick]), int(ys[pick])),
                    field,
                    stroke_width,
                    fill_pass["opacity"],
                    position
                    + pass_index * 0.4
                    + float(row_order[index]) * 0.36
                    + float(rng.uniform(0.0, 0.04)),
                )

        # Gap-filling: keep dabbing at whatever the passes missed until the
        # shape is essentially covered, the way a hand goes back over bare
        # spots before calling a colour done.
        occ = occupancy[: mask_coarse.shape[0], : mask_coarse.shape[1]]
        for _ in range(group_budget * 4):
            bare_ys, bare_xs = np.nonzero(mask_coarse & (occ == 0))
            if len(bare_xs) == 0 or len(bare_xs) < 0.015 * max(1, int(mask_coarse.sum())):
                break
            pick = int(rng.integers(len(bare_xs)))
            start = (
                int(np.clip(bare_xs[pick] * coarse + coarse // 2, 0, width - 1)),
                int(np.clip(bare_ys[pick] * coarse + coarse // 2, 0, height - 1)),
            )
            if labels[start[1], start[0]] != group:
                # A bare coarse cell can straddle a boundary; mark it so the
                # loop cannot spin on an unpaintable cell.
                cv2.circle(occupancy, (start[0] // coarse, start[1] // coarse), 1, 1, -1)
                continue
            if _make_stroke(
                group,
                start,
                field,
                base_width * 0.7,
                0.97,
                position + 0.82 + float(rng.uniform(0.0, 0.12)),
            ):
                gap_indices.add(len(strokes) - 1)

    # Bucket = colour group x pass (block-in, fill, gap-work), worked in
    # order by one hand.
    buckets = []
    for stroke in strokes:
        whole = int(stroke.order)
        frac = stroke.order - whole
        slot = 0 if frac < 0.4 else (1 if frac < 0.8 else 2)
        buckets.append(whole * 3 + slot)
    _schedule_hand_tour(
        strokes,
        buckets,
        rng=rng,
        late_indices=gap_indices,
        late_fraction=late_touchup_fraction,
        bucket_beat=45.0 + 600.0 * float(np.clip(pause_fraction, 0.0, 0.35)),
    )
    return StrokeField(strokes=strokes)


def generate_detail_strokes(
    analysis: ArtworkAnalysis,
    *,
    density: float = 1.0,
    brush_min: float = 4.0,
    seed: int = 0,
    max_strokes: int = 2500,
) -> StrokeField:
    """Small deliberate strokes for markings and identifying details.

    Seeds land where the artwork has fine structure - markings, patterns,
    facial features, edges of shapes - weighted toward the subject. Each
    stroke is short, follows the local edge orientation, and carries the true
    colour of the finished artwork at that spot, so the distinctive details
    build up mark by mark and never shift once placed.
    """
    rng = np.random.default_rng(seed + 9187)
    height, width = analysis.rgb.shape[:2]

    interest = analysis.detail_map * (0.45 + 0.55 * analysis.subject_mask)
    interest = np.clip(interest, 1e-5, None)
    probabilities = (interest / interest.sum()).reshape(-1)

    area = height * width
    count = int(np.clip(area / 1400.0 * density, 80, max_strokes))
    flat_index = rng.choice(area, size=count, replace=True, p=probabilities)
    seeds_y, seeds_x = np.unravel_index(flat_index, (height, width))

    strokes: list[Stroke] = []
    for index in range(count):
        start = (int(seeds_x[index]), int(seeds_y[index]))
        stroke_width = float(np.clip(brush_min * rng.uniform(0.6, 1.6), 1.5, brush_min * 2.2))
        steps = int(np.clip(rng.normal(14, 5), 6, 30))
        points = _walk(analysis.orientation, start, steps, rng, width, height)
        if len(points) < 2:
            continue

        base_colour = analysis.rgb[start[1], start[0]].astype(np.float32)
        jitter = rng.normal(0.0, 1.5, 3).astype(np.float32)
        colour = np.clip(base_colour + jitter, 0, 255)

        # Strong, distinctive details first (they define the likeness), with
        # enough jitter that the order never reads as mechanical.
        salience = float(interest[start[1], start[0]])
        strokes.append(
            Stroke(
                points=points,
                width=stroke_width,
                opacity=float(np.clip(rng.normal(0.9, 0.06), 0.6, 1.0)),
                speed=float(np.clip(rng.normal(1.0, 0.25), 0.4, 2.2)),
                order=-salience + float(rng.normal(0.0, 0.08)),
                colour=(int(colour[0]), int(colour[1]), int(colour[2])),
            )
        )

    # Two tiers: the strongest, most identifying details first, then the
    # rest - each toured by one hand.
    if strokes:
        median = float(np.median([stroke.order for stroke in strokes]))
        tiers = [0 if stroke.order <= median else 1 for stroke in strokes]
        _schedule_hand_tour(strokes, tiers, rng=rng)
    return StrokeField(strokes=strokes)


@dataclass(slots=True)
class _DirectionField:
    """Per-region stroke orientation, doubled-angle encoded (mod-pi safe)."""

    cos2: np.ndarray
    sin2: np.ndarray
    sweep_angle: float

    def angle_at(self, x: int, y: int) -> float:
        return 0.5 * math.atan2(float(self.sin2[y, x]), float(self.cos2[y, x]))


def _direction_field(
    mask: np.ndarray, xs: np.ndarray, ys: np.ndarray, rng: np.random.Generator
) -> _DirectionField:
    """How a painter's strokes run inside one shape.

    Near the boundary, strokes follow the contour (nobody paints across an
    edge they are trying to keep); toward the interior they relax onto the
    shape's long axis. Orientations are blended as doubled angles because a
    stroke direction is a line, not an arrow.
    """
    if len(xs) > 8:
        centred = np.stack([xs - xs.mean(), ys - ys.mean()]).astype(np.float32)
        cov = centred @ centred.T / len(xs)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        principal = eigenvectors[:, int(np.argmax(eigenvalues))]
        axis_angle = float(math.atan2(principal[1], principal[0]))
    else:
        axis_angle = float(rng.uniform(0, math.pi))

    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    smooth = cv2.GaussianBlur(distance, (0, 0), 7.0)
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    # The contour tangent is the gradient rotated a quarter turn; encode it as
    # a doubled angle so opposite tangents reinforce instead of cancelling.
    magnitude = gx * gx + gy * gy + 1e-6
    tangent_cos2 = (gy * gy - gx * gx) / magnitude
    tangent_sin2 = (-2.0 * gx * gy) / magnitude

    edge_weight = np.exp(-distance / 14.0).astype(np.float32)
    axis_cos2 = math.cos(2.0 * axis_angle)
    axis_sin2 = math.sin(2.0 * axis_angle)
    cos2 = tangent_cos2 * edge_weight + axis_cos2 * (1.0 - edge_weight)
    sin2 = tangent_sin2 * edge_weight + axis_sin2 * (1.0 - edge_weight)
    return _DirectionField(cos2=cos2, sin2=sin2, sweep_angle=axis_angle)


def _walk_field(
    labels: np.ndarray,
    group: int,
    start: tuple[int, int],
    field: _DirectionField,
    width_hint: float,
    rng: np.random.Generator,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """Follow the region's direction field, stopping at the colour boundary."""
    x, y = float(start[0]), float(start[1])
    points: list[tuple[int, int]] = [(int(x), int(y))]
    step = 2.2
    heading = field.angle_at(start[0], start[1])
    if rng.random() < 0.5:
        heading += math.pi
    max_steps = int(max(30, width_hint * 4.0 / step))
    off_region = 0

    for _ in range(max_steps):
        cx = int(np.clip(x, 0, width - 1))
        cy = int(np.clip(y, 0, height - 1))
        target = field.angle_at(cx, cy)
        # The field gives a line; take whichever direction of it is closer to
        # where the hand is already travelling, plus a little wobble.
        delta = math.atan2(math.sin(target - heading), math.cos(target - heading))
        if abs(delta) > math.pi / 2:
            delta = math.atan2(math.sin(delta + math.pi), math.cos(delta + math.pi))
        heading += delta * 0.5 + float(rng.normal(0.0, 0.06))

        x += math.cos(heading) * step
        y += math.sin(heading) * step
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


def render_fill_strokes(
    previous: np.ndarray,
    target: np.ndarray,
    field: StrokeField,
    progress: float,
    *,
    cache: dict | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Paint fill strokes as a stamped, tapered brush laying real pigment.

    Each stroke is a run of soft round stamps whose radius swells and tapers
    like pressure, carrying the stroke's own colour at partial opacity - so
    paint overlaps, builds up and lets the sketch ghost through, instead of
    appearing as flat opaque sausages.

    ``cache`` carries the wet canvas between frames of one stage; passing the
    same dict for monotonically increasing ``progress`` only paints the new
    stamps. With no cache the frame is rebuilt from ``previous``.
    """
    progress = float(np.clip(progress, 0.0, 1.0))
    if cache is None:
        cache = {}
    if "canvas" not in cache:
        cache["canvas"] = previous.astype(np.float32).copy()
        cache["drawn"] = [0] * len(field.strokes)
        cache["stamps"] = {}
    canvas: np.ndarray = cache["canvas"]

    if field.strokes and progress > 0:
        height, width = canvas.shape[:2]
        for index, stroke in enumerate(field.strokes):
            if stroke.order > progress:
                continue
            fraction = float(
                np.clip((progress - stroke.order) * max(0.2, stroke.speed) * 6.0, 0.0, 1.0)
            )
            if fraction <= 0:
                continue
            stamps = cache["stamps"].get(index)
            if stamps is None:
                stamps = _stroke_stamps(stroke, seed + index)
                cache["stamps"][index] = stamps
            want = max(1, int(round(len(stamps) * fraction)))
            for cx, cy, radius, alpha in stamps[cache["drawn"][index] : want]:
                _blend_stamp(canvas, cx, cy, radius, alpha, stroke.colour, width, height)
            cache["drawn"][index] = max(cache["drawn"][index], want)

    return np.clip(canvas, 0, 255).astype(np.uint8)


def _stroke_stamps(stroke: Stroke, seed: int) -> list[tuple[float, float, float, float]]:
    """Resample a stroke path into brush stamps with a pressure profile."""
    rng = np.random.default_rng(seed * 31 + 7)
    points = np.asarray(stroke.points, dtype=np.float32)
    deltas = np.diff(points, axis=0)
    seg_lengths = np.hypot(deltas[:, 0], deltas[:, 1])
    total = float(seg_lengths.sum())
    if total <= 0:
        return []
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lengths)])

    spacing = max(1.6, stroke.width * 0.3)
    distances = np.arange(0.0, total + spacing * 0.5, spacing)
    stamps: list[tuple[float, float, float, float]] = []
    for distance in distances:
        t = distance / total
        segment = min(len(seg_lengths) - 1, int(np.searchsorted(cumulative, distance) - 1))
        segment = max(0, segment)
        local = (distance - cumulative[segment]) / max(1e-6, seg_lengths[segment])
        x, y = points[segment] + deltas[segment] * min(1.0, local)

        # Pressure: the brush lands light, presses through the body of the
        # mark, and lifts off the end.
        attack = min(1.0, t / 0.18) if t < 0.18 else 1.0
        release = min(1.0, (1.0 - t) / 0.28) if t > 0.72 else 1.0
        pressure = 0.35 + 0.65 * min(attack, release)

        radius = max(0.8, 0.5 * stroke.width * pressure * (1.0 + float(rng.normal(0.0, 0.07))))
        wobble = rng.normal(0.0, radius * 0.08, 2)
        alpha = stroke.opacity * (0.62 + 0.33 * pressure)
        stamps.append((float(x + wobble[0]), float(y + wobble[1]), radius, float(alpha)))
    return stamps


def _blend_stamp(
    canvas: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    alpha: float,
    colour: tuple[int, int, int] | None,
    width: int,
    height: int,
) -> None:
    """Alpha-blend one soft round dab of pigment into the wet canvas."""
    if colour is None:
        return
    reach = int(math.ceil(radius + 2))
    x0, x1 = int(cx) - reach, int(cx) + reach + 1
    y0, y1 = int(cy) - reach, int(cy) + reach + 1
    if x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height:
        return
    x0c, x1c = max(0, x0), min(width, x1)
    y0c, y1c = max(0, y0), min(height, y1)

    yy, xx = np.mgrid[y0c:y1c, x0c:x1c].astype(np.float32)
    distance = np.hypot(xx - cx, yy - cy)
    mask = np.clip((radius - distance) / 1.2 + 0.5, 0.0, 1.0) * alpha

    patch = canvas[y0c:y1c, x0c:x1c]
    pigment = np.asarray(colour, dtype=np.float32)
    patch += (pigment - patch) * mask[:, :, None]


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
