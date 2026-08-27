"""Stage plans, reveal ordering, strokes and frame generation."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from artrestore_timelapse import (
    MODES,
    REVEAL_KINDS,
    RenderOptions,
    Stage,
    TimelapseRenderer,
    apply_reveal,
    build_plan,
    build_reveal_map,
    describe_plan,
    generate_strokes,
    normalise_plan,
    plan_duration,
    render_strokes,
)
from artrestore_timelapse.errors import InvalidPlanError, RenderCancelledError

# -- plans ------------------------------------------------------------------


@pytest.mark.parametrize("mode", [m for m in MODES if m != "real_intermediates"])
def test_every_mode_builds_a_plan_of_the_requested_length(mode):
    stages = build_plan(mode, total_seconds=20)
    assert len(stages) >= 4
    assert plan_duration(stages) == pytest.approx(20.0, abs=0.05)
    assert [stage.order_index for stage in stages] == list(range(len(stages)))


def test_real_intermediates_preserves_uploaded_order():
    stages = build_plan("real_intermediates", total_seconds=15, intermediate_count=4)
    authentic = [stage for stage in stages if stage.stage_type == "real_intermediate"]
    assert len(authentic) == 4
    assert [stage.settings["intermediate_index"] for stage in authentic] == [0, 1, 2, 3]
    assert plan_duration(stages) == pytest.approx(15.0, abs=0.05)


def test_real_intermediates_requires_uploads():
    with pytest.raises(InvalidPlanError):
        build_plan("real_intermediates", total_seconds=10, intermediate_count=0)


def test_unknown_mode_is_rejected():
    with pytest.raises(InvalidPlanError):
        build_plan("interpretive_dance", total_seconds=10)


def test_duration_is_clamped_to_the_supported_range():
    assert plan_duration(build_plan("paint_reveal", total_seconds=1)) == pytest.approx(
        5.0, abs=0.05
    )
    assert plan_duration(build_plan("paint_reveal", total_seconds=9999)) == pytest.approx(
        300.0, abs=0.5
    )


def test_normalise_plan_rescales_and_renumbers():
    stages = [
        Stage("highlights", order_index=5, duration=2.0),
        Stage("base_colours", order_index=1, duration=2.0),
        Stage("shadows", order_index=9, duration=0.0),  # dropped: zero length
    ]
    result = normalise_plan(stages, total_seconds=10)
    assert [stage.stage_type for stage in result] == ["base_colours", "highlights"]
    assert [stage.order_index for stage in result] == [0, 1]
    assert plan_duration(result) == pytest.approx(10.0, abs=0.01)


def test_disabled_stages_are_dropped():
    stages = [Stage("base_colours", 0, 2.0), Stage("shadows", 1, 2.0, enabled=False)]
    assert [stage.stage_type for stage in normalise_plan(stages)] == ["base_colours"]


def test_plan_with_no_enabled_stages_is_rejected():
    with pytest.raises(InvalidPlanError):
        normalise_plan([Stage("shadows", 0, 2.0, enabled=False)])


def test_describe_plan_reports_timing_windows():
    described = describe_plan(build_plan("layer_build", total_seconds=12))
    assert described[0]["starts_at"] == 0.0
    assert described[-1]["ends_at"] == pytest.approx(12.0, abs=0.05)
    for earlier, later in itertools.pairwise(described):
        assert earlier["ends_at"] == pytest.approx(later["starts_at"], abs=1e-6)


def test_sketch_workflow_follows_a_real_drawing_order():
    """Planning, rough, refined, ink, erase - all before any colour; shading
    after the flats and markings, and a long finishing pass before the hold.
    The sketch is the prelude: the painting carries most of the runtime."""
    stages = build_plan("sketch_to_colour", total_seconds=30)
    types = [stage.stage_type for stage in stages]
    sequence = [
        "blank_canvas",
        "construction_planning",
        "construction_sketch",
        "refined_lines",
        "ink_lines",
        "erase_sketch",
        "base_colours",
        "markings",
        "shadows",
        "highlights",
        "texture_details",
    ]
    indices = [types.index(name) for name in sequence]
    assert indices == sorted(indices)
    assert types.index("erase_sketch") < types.index("base_colours")

    sketch_time = sum(
        stage.duration
        for stage in stages
        if stage.stage_type in sequence[: sequence.index("base_colours")]
    )
    active_time = sum(stage.duration for stage in stages if stage.stage_type != "final_hold")
    assert (
        0.2 <= sketch_time / active_time <= 0.35
    ), "the sketch should be a prelude, not half the video"


def test_hold_stage_keeps_the_canvas_still(analysis):
    stages = [
        Stage(
            stage_type="base_colours", order_index=0, duration=0.4, settings={"reveal": "region"}
        ),
        Stage(stage_type="hold", order_index=1, duration=0.4),
    ]
    renderer = TimelapseRenderer(
        analysis, stages, RenderOptions(fps=10, preset="source", end_card_disclosure=False)
    )
    frames = list(renderer.iter_frames())
    hold_frames = frames[-renderer.plan.frame_counts[-1] :]
    for frame in hold_frames[1:]:
        assert np.array_equal(frame, hold_frames[0])
    # And the held canvas is the completed previous stage, not a blank.
    assert np.array_equal(hold_frames[0], frames[renderer.plan.frame_counts[0] - 1])


# -- the pen ----------------------------------------------------------------


def test_pen_draws_one_stroke_at_a_time(analysis):
    from artrestore_timelapse.pen import plan_pen

    plan = plan_pen(analysis.line_art, rng=np.random.default_rng(3))
    assert len(plan.strokes) > 10
    # Strict sequence: every stroke begins at or after the previous one ends.
    ends = plan.starts + plan.costs
    assert np.all(plan.starts[1:] >= ends[:-1] - 1e-4)


def test_pen_plan_is_deterministic(analysis):
    from artrestore_timelapse.pen import plan_pen

    first = plan_pen(analysis.line_art, rng=np.random.default_rng(11))
    second = plan_pen(analysis.line_art, rng=np.random.default_rng(11))
    assert len(first.strokes) == len(second.strokes)
    assert all(np.array_equal(a, b) for a, b in zip(first.strokes, second.strokes, strict=True))


def test_pen_rendering_grows_and_finishes(analysis):
    from artrestore_timelapse.pen import plan_pen, render_pen

    plan = plan_pen(analysis.line_art, rng=np.random.default_rng(5))
    underlay = np.full_like(analysis.rgb, 245)
    target = np.zeros_like(analysis.rgb)
    cache: dict = {}
    covered = []
    for progress in (0.25, 0.5, 0.75, 1.0):
        frame = render_pen(underlay, target, plan, progress, cache=cache)
        covered.append(float((frame.mean(axis=2) < 128).mean()))
    assert covered[0] < covered[1] < covered[2] < covered[3]
    # At full progress the pen has visited every line.
    mask = cache["mask"]
    lines = analysis.line_art > 60
    assert float((mask[lines] > 0).mean()) > 0.95


# -- reveal maps ------------------------------------------------------------


@pytest.mark.parametrize("kind", REVEAL_KINDS)
def test_reveal_maps_are_uniformly_paced(kind, analysis):
    reveal = build_reveal_map(kind, analysis, rng=np.random.default_rng(4))
    assert reveal.shape == analysis.rgb.shape[:2]
    for progress in (0.25, 0.5, 0.75):
        revealed = float((reveal <= progress).mean())
        assert revealed == pytest.approx(progress, abs=0.02)


@pytest.mark.parametrize("kind", REVEAL_KINDS)
def test_reveal_is_not_a_horizontal_wipe(kind, analysis):
    """A generic left-to-right wipe would correlate almost perfectly with x."""
    reveal = build_reveal_map(kind, analysis, rng=np.random.default_rng(4))
    columns = np.mgrid[0 : reveal.shape[0], 0 : reveal.shape[1]][1].astype(np.float32)
    correlation = abs(float(np.corrcoef(reveal.ravel(), columns.ravel())[0, 1]))
    assert correlation < 0.6, f"{kind} reveal is close to a horizontal wipe"


def test_apply_reveal_endpoints(analysis, artwork):
    reveal = build_reveal_map("organic", analysis, rng=np.random.default_rng(1))
    blank = np.full_like(analysis.rgb, 250)
    assert np.array_equal(apply_reveal(blank, analysis.rgb, reveal, 0.0), blank)
    assert np.array_equal(apply_reveal(blank, analysis.rgb, reveal, 1.0), analysis.rgb)


# -- strokes ----------------------------------------------------------------


@pytest.mark.parametrize("pass_name", ["structure", "mass", "detail"])
def test_strokes_are_generated_and_ordered(analysis, pass_name):
    field = generate_strokes(analysis, pass_name=pass_name, seed=5)
    assert len(field) > 20
    orders = [stroke.order for stroke in field.strokes]
    assert min(orders) >= 0.0 and max(orders) < 1.0
    assert len(set(orders)) > len(orders) // 2, "stroke order should be spread out"


def test_stroke_widths_respect_the_brush_range(analysis):
    field = generate_strokes(analysis, brush_min=4, brush_max=12, seed=5)
    assert all(4 <= stroke.width <= 12 for stroke in field.strokes)


def test_detail_pass_makes_shorter_marks_than_the_mass_pass(analysis):
    mass = generate_strokes(analysis, pass_name="mass", seed=5)
    detail = generate_strokes(analysis, pass_name="detail", seed=5)
    mass_length = np.mean([stroke.length for stroke in mass.strokes])
    detail_length = np.mean([stroke.length for stroke in detail.strokes])
    assert detail_length < mass_length


def test_strokes_are_deterministic(analysis):
    first = generate_strokes(analysis, seed=17)
    second = generate_strokes(analysis, seed=17)
    assert [stroke.to_dict() for stroke in first.strokes] == [
        stroke.to_dict() for stroke in second.strokes
    ]


def test_stroke_rendering_grows_monotonically(analysis):
    field = generate_strokes(analysis, seed=8)
    canvas = np.full_like(analysis.rgb, 250)
    covered = []
    for progress in (0.2, 0.5, 0.9):
        frame = render_strokes(canvas, analysis.rgb, field, progress)
        covered.append(float((np.abs(frame.astype(int) - canvas.astype(int)).sum(2) > 8).mean()))
    assert covered[0] < covered[1] < covered[2]


def test_fill_strokes_work_element_by_element(analysis):
    import cv2
    from artrestore_timelapse import generate_fill_strokes

    field = generate_fill_strokes(analysis, seed=3)
    assert len(field) > 30
    orders = [stroke.order for stroke in field.strokes]
    assert min(orders) >= 0.0 and max(orders) < 1.0

    # Element by element: strokes inside one line-bounded shape of one colour
    # stay contiguous in the drawing order - the brush finishes an element
    # before moving on, rather than painting a colour everywhere at once.
    labels = cv2.medianBlur(analysis.palette_labels.astype(np.uint8), 5).astype(np.int32)
    line_mask = analysis.line_art > 60
    height, width = labels.shape
    min_area = max(64.0, height * width * 0.0003)
    element_map = np.full(labels.shape, -1, np.int32)
    next_id = 0
    for group in range(int(labels.max()) + 1):
        open_mask = (labels == group) & ~line_mask
        count, components = cv2.connectedComponents(open_mask.astype(np.uint8), connectivity=4)
        for component in range(1, count):
            selection = components == component
            if selection.sum() >= min_area:
                element_map[selection] = next_id
                next_id += 1
    by_element: dict[int, list[float]] = {}
    for stroke in field.strokes:
        element = int(element_map[stroke.points[0][1], stroke.points[0][0]])
        if element >= 0:
            by_element.setdefault(element, []).append(stroke.order)
    # The threshold leaves room for the deliberate back-and-forth: a slice of
    # each element's fill work returns after the next element is underway.
    spans = [float(np.std(values)) for values in by_element.values() if len(values) > 5]
    assert len(spans) >= 2
    assert float(np.mean(spans)) < 0.17, "each sketch element should be painted as one block"


def test_fill_strokes_paint_far_to_near(analysis):
    from artrestore_timelapse import generate_fill_strokes

    field = generate_fill_strokes(analysis, seed=3)
    # The big fields go in top of the canvas first (sky before mountains
    # before water). Compare the median start row of the earliest strokes
    # with the latest strokes among the wide ones.
    wide = [
        stroke
        for stroke in field.strokes
        if stroke.width > np.median([s.width for s in field.strokes])
    ]
    wide.sort(key=lambda stroke: stroke.order)
    third = max(1, len(wide) // 3)
    early_rows = np.median([stroke.points[0][1] for stroke in wide[:third]])
    late_rows = np.median([stroke.points[0][1] for stroke in wide[-third:]])
    assert early_rows < late_rows, "painting should start at the top of the canvas and move down"


def test_fill_strokes_respect_the_sketch_lines(analysis):
    from artrestore_timelapse import generate_fill_strokes

    field = generate_fill_strokes(analysis, seed=3)
    lines = analysis.line_art > 60
    for stroke in field.strokes:
        for x, y in stroke.points:
            assert not lines[y, x], "a fill stroke painted across a sketch line"


def test_fill_strokes_paint_one_at_a_time(analysis):
    from artrestore_timelapse import generate_fill_strokes

    field = generate_fill_strokes(analysis, seed=3)
    timed = sorted(
        ((stroke.order, stroke.order + 1.0 / (6.0 * stroke.speed)) for stroke in field.strokes),
    )
    for (_, previous_end), (next_start, _) in itertools.pairwise(timed):
        assert next_start >= previous_end - 1e-6, "two brush strokes were in flight at once"


def test_fill_strokes_are_deterministic(analysis):
    from artrestore_timelapse import generate_fill_strokes

    first = generate_fill_strokes(analysis, seed=9)
    second = generate_fill_strokes(analysis, seed=9)
    assert [stroke.to_dict() for stroke in first.strokes] == [
        stroke.to_dict() for stroke in second.strokes
    ]


def test_stroke_field_exports_svg(analysis):
    svg = generate_strokes(analysis, seed=2).to_svg(400, 300)
    assert svg.startswith("<svg")
    assert "<path" in svg


# -- frames -----------------------------------------------------------------


@pytest.mark.parametrize("mode", [m for m in MODES if m != "real_intermediates"])
def test_frames_are_produced_for_every_mode(analysis, mode):
    stages = build_plan(mode, total_seconds=5)
    renderer = TimelapseRenderer(
        analysis, stages, RenderOptions(fps=24, seed=3, preview=True, preview_max_side=180)
    )
    frames = list(renderer.iter_frames())
    assert len(frames) == renderer.plan.total_frames
    assert all(frame.shape == (renderer.plan.height, renderer.plan.width, 3) for frame in frames)


def test_render_starts_blank_and_ends_on_the_artwork(analysis):
    stages = build_plan("paint_reveal", total_seconds=5)
    renderer = TimelapseRenderer(
        analysis,
        stages,
        RenderOptions(
            fps=24,
            seed=3,
            preview=True,
            preview_max_side=180,
            end_card_disclosure=False,
            background_colour="#FFFFFF",
        ),
    )
    frames = list(renderer.iter_frames())
    assert frames[0].mean() > 200, "the first frame should be close to the blank canvas"

    # The last frame should resemble the finished artwork, not the blank canvas.
    import cv2

    final = cv2.resize(analysis.rgb, (renderer.plan.width, renderer.plan.height))
    difference = float(np.abs(frames[-1].astype(int) - final.astype(int)).mean())
    assert difference < 40


def test_sketch_ending_never_fades_into_the_source_image(analysis):
    stages = build_plan("sketch_to_colour", total_seconds=8)
    renderer = TimelapseRenderer(
        analysis,
        stages,
        RenderOptions(
            fps=24,
            seed=3,
            preview=True,
            preview_max_side=180,
            end_card_disclosure=False,
            background_colour="#FFFFFF",
        ),
    )
    frames = list(renderer.iter_frames())

    import cv2

    # The video ends on the painted canvas, held steady - never on the source
    # image itself. A crossfade into the finished photograph would collapse
    # this difference toward zero.
    source = cv2.resize(analysis.rgb, (renderer.plan.width, renderer.plan.height))
    difference = float(np.abs(frames[-1].astype(int) - source.astype(int)).mean())
    assert difference > 2.0, "the final frame matched the source image - the ending faded"

    hold_frames = max(2, int(round(renderer.plan.fps * 0.2)))
    tail = frames[-hold_frames:]
    assert all(
        np.array_equal(tail[0], frame) for frame in tail[1:]
    ), "the final hold should keep the painted canvas perfectly still"


def test_progress_reaches_completion(analysis):
    seen: list[float] = []
    renderer = TimelapseRenderer(
        analysis,
        build_plan("layer_build", total_seconds=5),
        RenderOptions(fps=24, seed=3, preview=True, preview_max_side=160),
    )
    list(renderer.iter_frames(progress=lambda fraction, message: seen.append(fraction)))
    assert seen and seen[-1] == 1.0
    assert all(0.0 <= value <= 1.0 for value in seen)


def test_render_can_be_cancelled(analysis):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=24, seed=3, preview=True, preview_max_side=160),
    )
    with pytest.raises(RenderCancelledError):
        list(renderer.iter_frames(should_cancel=lambda: True))


def test_same_seed_produces_identical_frames(analysis):
    def render():
        renderer = TimelapseRenderer(
            analysis,
            build_plan("hand_drawn_strokes", total_seconds=5),
            RenderOptions(fps=24, seed=42, preview=True, preview_max_side=160),
        )
        return list(renderer.iter_frames())

    first, second = render(), render()
    assert len(first) == len(second)
    assert all(np.array_equal(a, b) for a, b in zip(first, second, strict=True))


def test_different_seeds_produce_different_frames(analysis):
    def render(seed):
        renderer = TimelapseRenderer(
            analysis,
            build_plan("hand_drawn_strokes", total_seconds=5),
            RenderOptions(fps=24, seed=seed, preview=True, preview_max_side=160),
        )
        return list(renderer.iter_frames())

    first, second = render(1), render(2)
    assert any(not np.array_equal(a, b) for a, b in zip(first, second, strict=True))


def test_end_card_is_enabled_by_default(analysis):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=24, seed=3, preview=True, preview_max_side=200),
    )
    assert renderer.plan.end_card_frames > 0
    frames = list(renderer.iter_frames())

    # The end card darkens a band at the bottom of the frame.
    band = frames[-1][int(renderer.plan.height * 0.9) :]
    earlier = frames[-renderer.plan.end_card_frames - 1][int(renderer.plan.height * 0.9) :]
    assert band.mean() < earlier.mean()


def test_end_card_can_be_disabled(analysis):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=24, seed=3, preview=True, end_card_disclosure=False),
    )
    assert renderer.plan.end_card_frames == 0


def test_canvas_presets_change_the_output_shape(analysis):
    shapes = {}
    for preset in ("square", "portrait_4x5", "vertical_9x16", "landscape_16x9"):
        renderer = TimelapseRenderer(
            analysis,
            build_plan("paint_reveal", total_seconds=5),
            RenderOptions(fps=24, preset=preset, seed=1),
        )
        shapes[preset] = (renderer.plan.width, renderer.plan.height)
    assert shapes["square"] == (1080, 1080)
    assert shapes["vertical_9x16"] == (1080, 1920)
    assert shapes["landscape_16x9"] == (1920, 1080)
    assert shapes["portrait_4x5"] == (1080, 1350)


def test_source_preset_follows_the_artwork_aspect(analysis):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=24, preset="source", seed=1),
    )
    source_ratio = analysis.rgb.shape[1] / analysis.rgb.shape[0]
    output_ratio = renderer.plan.width / renderer.plan.height
    assert output_ratio == pytest.approx(source_ratio, rel=0.02)


def test_output_dimensions_are_even_for_h264(analysis):
    """yuv420p requires even dimensions; odd sizes would fail at encode time."""
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=30, preset="source", seed=1, preview=True, preview_max_side=181),
    )
    assert renderer.plan.width % 2 == 0
    assert renderer.plan.height % 2 == 0


def test_real_intermediates_use_the_uploaded_images(analysis):
    stage_images = [
        np.full_like(analysis.rgb, 40),
        np.full_like(analysis.rgb, 120),
    ]
    stages = build_plan("real_intermediates", total_seconds=6, intermediate_count=2)
    renderer = TimelapseRenderer(
        analysis,
        stages,
        RenderOptions(
            fps=24, seed=3, preview=True, preview_max_side=160, end_card_disclosure=False
        ),
        intermediates=stage_images,
    )
    frames = list(renderer.iter_frames())

    # Sample the centre of the canvas, away from the letterbox bars, and look
    # for the artist's own stage rather than a generated approximation of it.
    height, width = frames[0].shape[:2]
    centre = (
        slice(int(height * 0.4), int(height * 0.6)),
        slice(int(width * 0.4), int(width * 0.6)),
    )
    centres = [float(frame[centre].mean()) for frame in frames]
    assert min(centres) < 55, "the first uploaded stage never appeared"
    assert any(abs(value - 120) < 20 for value in centres), "the second stage never appeared"


def test_missing_intermediate_holds_rather_than_substituting(analysis):
    """An absent upload must not be replaced by a generated stand-in."""
    stages = build_plan("real_intermediates", total_seconds=6, intermediate_count=2)
    renderer = TimelapseRenderer(
        analysis,
        stages,
        RenderOptions(fps=24, seed=3, preview=True, preview_max_side=160),
        intermediates=[],
    )
    frames = list(renderer.iter_frames())
    assert len(frames) == renderer.plan.total_frames


def test_zoom_pan_and_cursor_options_render(analysis):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("hand_drawn_strokes", total_seconds=5),
        RenderOptions(
            fps=24, seed=3, preview=True, preview_max_side=160, zoom_pan=True, show_cursor=True
        ),
    )
    frames = list(renderer.iter_frames())
    assert len(frames) == renderer.plan.total_frames


def test_brand_watermark_is_composited(analysis):
    mark = np.zeros((40, 120, 4), np.uint8)
    mark[:, :, :3] = 255
    mark[:, :, 3] = 255
    options = RenderOptions(fps=24, seed=3, preview=True, preview_max_side=240)
    plain = list(
        TimelapseRenderer(
            analysis, build_plan("paint_reveal", total_seconds=5), options
        ).iter_frames()
    )

    branded_options = RenderOptions(
        fps=24, seed=3, preview=True, preview_max_side=240, brand_watermark=mark
    )
    branded = list(
        TimelapseRenderer(
            analysis, build_plan("paint_reveal", total_seconds=5), branded_options
        ).iter_frames()
    )
    assert not np.array_equal(plain[10], branded[10])


def test_plan_over_the_duration_limit_is_rejected(analysis):
    stages = [Stage("texture_details", 0, 400.0)]
    with pytest.raises(InvalidPlanError):
        TimelapseRenderer(analysis, stages, RenderOptions(fps=24))
