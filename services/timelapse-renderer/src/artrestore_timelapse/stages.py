"""Stage plans: the editable timeline behind every reconstruction mode.

A plan is a list of stages, each with a type, a duration and its own settings.
The five modes are templates that produce a starting plan; the user then
reorders, retimes, disables and tweaks stages, and the renderer works from
whatever the plan says rather than from the mode name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import InvalidPlanError
from .presets import MAX_DURATION_SECONDS, MIN_DURATION_SECONDS

MODES = (
    "sketch_to_colour",
    "paint_reveal",
    "layer_build",
    "hand_drawn_strokes",
    "real_intermediates",
)

MODE_LABELS = {
    "sketch_to_colour": "Sketch to Colour",
    "paint_reveal": "Paint Reveal",
    "layer_build": "Layer Build",
    "hand_drawn_strokes": "Hand-Drawn Stroke Simulation",
    "real_intermediates": "Real Intermediate Frames",
}

STAGE_LABELS = {
    "blank_canvas": "Blank canvas",
    "construction_sketch": "Construction sketch",
    "refined_lines": "Refined line art",
    "base_colours": "Base colours",
    "shadows": "Shadows",
    "highlights": "Highlights",
    "texture_details": "Texture and finishing details",
    "background": "Background",
    "silhouette": "Subject silhouette",
    "colour_groups": "Main colour groups",
    "focal_details": "Focal details",
    "polish": "Highlights and polish",
    "broad_forms": "Large forms",
    "secondary_forms": "Secondary forms",
    "detail_pass": "Details",
    "colour_correction": "Final colour correction",
    "stroke_pass": "Stroke pass",
    "real_intermediate": "Artist stage",
    "final_hold": "Finished artwork",
}

#: Relative weights used to distribute a requested total duration.
_TEMPLATES: dict[str, list[tuple[str, float, dict]]] = {
    "sketch_to_colour": [
        ("blank_canvas", 0.4, {}),
        ("construction_sketch", 1.6, {"reveal": "stroke", "jitter": 1.0}),
        ("refined_lines", 1.4, {"reveal": "stroke"}),
        ("base_colours", 2.0, {"reveal": "region"}),
        ("shadows", 1.2, {"reveal": "tonal"}),
        ("highlights", 1.0, {"reveal": "tonal"}),
        ("texture_details", 1.8, {"reveal": "detail"}),
        ("final_hold", 0.6, {}),
    ],
    "paint_reveal": [
        ("blank_canvas", 0.3, {}),
        ("broad_forms", 2.2, {"reveal": "organic", "pyramid_level": 1}),
        ("secondary_forms", 2.0, {"reveal": "organic", "pyramid_level": 3}),
        ("detail_pass", 2.2, {"reveal": "detail", "pyramid_level": 5}),
        ("colour_correction", 1.0, {"reveal": "dissolve"}),
        ("final_hold", 0.6, {}),
    ],
    "layer_build": [
        ("blank_canvas", 0.3, {}),
        ("background", 1.6, {"reveal": "organic"}),
        ("silhouette", 1.4, {"reveal": "region"}),
        ("colour_groups", 2.2, {"reveal": "region"}),
        ("focal_details", 1.8, {"reveal": "detail"}),
        ("polish", 1.2, {"reveal": "tonal"}),
        ("final_hold", 0.6, {}),
    ],
    "hand_drawn_strokes": [
        ("blank_canvas", 0.3, {}),
        ("stroke_pass", 2.4, {"pass": "structure", "brush_scale": 1.6}),
        ("stroke_pass", 2.4, {"pass": "mass", "brush_scale": 1.0}),
        ("stroke_pass", 2.2, {"pass": "detail", "brush_scale": 0.5}),
        ("texture_details", 1.4, {"reveal": "detail"}),
        ("final_hold", 0.6, {}),
    ],
}


@dataclass(slots=True)
class Stage:
    """One entry on the timeline."""

    stage_type: str
    order_index: int
    duration: float
    label: str = ""
    enabled: bool = True
    settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage_type": self.stage_type,
            "order_index": self.order_index,
            "duration": round(float(self.duration), 3),
            "label": self.label or STAGE_LABELS.get(self.stage_type, self.stage_type),
            "enabled": self.enabled,
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Stage:
        return cls(
            stage_type=str(data.get("stage_type", "final_hold")),
            order_index=int(data.get("order_index", 0)),
            duration=float(data.get("duration", 1.0)),
            label=str(data.get("label", "")),
            enabled=bool(data.get("enabled", True)),
            settings=dict(data.get("settings") or {}),
        )


def build_plan(
    mode: str,
    *,
    total_seconds: float,
    intermediate_count: int = 0,
    hold_final_seconds: float = 1.5,
) -> list[Stage]:
    """Produce the starting timeline for a mode.

    ``real_intermediates`` is built from the artist's own uploaded stages, so
    its shape depends on how many they supplied rather than on a template.
    """
    if mode not in MODES:
        raise InvalidPlanError(f"Unknown timelapse mode '{mode}'.", details={"modes": list(MODES)})
    total = float(max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, total_seconds)))

    if mode == "real_intermediates":
        return _intermediates_plan(total, intermediate_count, hold_final_seconds)

    template = _TEMPLATES[mode]
    hold = max(0.0, min(hold_final_seconds, total * 0.4))
    budget = max(0.5, total - hold)
    weights = [weight for _, weight, _ in template if _ != "final_hold"]
    weight_total = sum(weight for stage_type, weight, _ in template if stage_type != "final_hold")

    stages: list[Stage] = []
    index = 0
    for stage_type, weight, settings in template:
        if stage_type == "final_hold":
            duration = hold
        else:
            duration = budget * (weight / weight_total)
        if duration <= 0:
            continue
        stages.append(
            Stage(
                stage_type=stage_type,
                order_index=index,
                duration=round(duration, 3),
                label=STAGE_LABELS.get(stage_type, stage_type),
                settings=dict(settings),
            )
        )
        index += 1
    _ = weights
    return stages


def _intermediates_plan(total: float, count: int, hold: float) -> list[Stage]:
    """Use the artist's uploaded stages as real keyframes.

    Their order is preserved and no stage is replaced by a generated one: the
    reconstruction only supplies the transitions *between* authentic stages.
    """
    if count <= 0:
        raise InvalidPlanError(
            "Real Intermediate Frames needs at least one uploaded progress image.",
            details={"intermediate_count": count},
        )
    hold = max(0.0, min(hold, total * 0.4))
    budget = max(0.5, total - hold)
    opening = min(0.5, budget * 0.08)
    # The uploaded stages plus one closing stage for the finished artwork.
    per_stage = (budget - opening) / float(count + 1)

    stages = [
        Stage(
            stage_type="blank_canvas",
            order_index=0,
            duration=round(opening, 3),
            label=STAGE_LABELS["blank_canvas"],
            settings={},
        )
    ]
    for position in range(count):
        stages.append(
            Stage(
                stage_type="real_intermediate",
                order_index=position + 1,
                duration=round(per_stage, 3),
                label=f"Artist stage {position + 1}",
                settings={"intermediate_index": position, "reveal": "dissolve"},
            )
        )
    stages.append(
        Stage(
            stage_type="texture_details",
            order_index=count + 1,
            duration=round(per_stage, 3),
            label="Finished artwork",
            settings={"reveal": "dissolve"},
        )
    )
    stages.append(
        Stage(
            stage_type="final_hold",
            order_index=count + 2,
            duration=round(hold, 3),
            label=STAGE_LABELS["final_hold"],
            settings={},
        )
    )
    return stages


def normalise_plan(stages: list[Stage], *, total_seconds: float | None = None) -> list[Stage]:
    """Sort, renumber and (optionally) rescale a plan to a target duration."""
    active = [stage for stage in stages if stage.enabled and stage.duration > 0]
    if not active:
        raise InvalidPlanError("The timeline has no enabled stages.")
    active.sort(key=lambda stage: stage.order_index)

    if total_seconds is not None:
        target = float(max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, total_seconds)))
        current = sum(stage.duration for stage in active)
        if current <= 0:
            raise InvalidPlanError("The timeline has no duration.")
        scale = target / current
        for stage in active:
            stage.duration = round(stage.duration * scale, 4)

    for index, stage in enumerate(active):
        stage.order_index = index
        if not stage.label:
            stage.label = STAGE_LABELS.get(stage.stage_type, stage.stage_type)
    return active


def plan_duration(stages: list[Stage]) -> float:
    return round(sum(stage.duration for stage in stages if stage.enabled), 4)


def describe_plan(stages: list[Stage]) -> list[dict]:
    """The exact progress-stage list that produced a video.

    Exported alongside every render so the reconstruction is inspectable rather
    than a black box.
    """
    elapsed = 0.0
    described: list[dict] = []
    for stage in stages:
        entry = stage.to_dict()
        entry["starts_at"] = round(elapsed, 3)
        elapsed += stage.duration
        entry["ends_at"] = round(elapsed, 3)
        described.append(entry)
    return described
