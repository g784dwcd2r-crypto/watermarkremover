"""The project JSON: settings, seed and the exact stage list used.

Exported alongside every render. Two things make it worth shipping: a user can
reproduce a render exactly (same seed, same plan, same output), and anyone
looking at the file can see precisely which synthetic stages produced the video
rather than having to take the result on trust.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .frames import RenderOptions, RenderPlan
from .presets import DISCLOSURE_LONG, RECONSTRUCTION_TYPE
from .stages import Stage, describe_plan

PROJECT_JSON_VERSION = 1


def build_project_json(
    *,
    project_name: str,
    mode: str,
    stages: list[Stage],
    options: RenderOptions,
    plan: RenderPlan,
    analysis_summary: dict,
    source: dict[str, Any] | None = None,
    intermediates: list[dict] | None = None,
) -> dict:
    """Assemble the reproducibility document for one render."""
    return {
        "version": PROJECT_JSON_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generator": "ArtRestore Studio timelapse renderer",
        "disclosure": {
            "reconstruction_type": RECONSTRUCTION_TYPE,
            "statement": DISCLOSURE_LONG,
            "is_original_recording": False,
            "end_card_enabled": options.end_card_disclosure,
            "simulated_cursor": options.show_cursor,
            "simulated_cursor_note": (
                "Cursor movement, when enabled, is generated from the artwork's structure. "
                "It is not a recording of real input."
            ),
        },
        "project": {"name": project_name, "mode": mode},
        "seed": options.seed,
        "render": {
            **options.to_dict(),
            "width": plan.width,
            "height": plan.height,
            "total_frames": plan.total_frames,
            "duration_seconds": plan.duration_seconds,
        },
        "source": source or {},
        "authentic_intermediates": intermediates or [],
        "analysis": analysis_summary,
        "stages": describe_plan(stages),
    }


def dumps(document: dict) -> bytes:
    return json.dumps(document, indent=2, sort_keys=False).encode("utf-8")
