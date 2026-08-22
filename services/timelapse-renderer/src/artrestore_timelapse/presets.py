"""Canvas presets, easing curves and the disclosure strings.

The disclosure text lives here because it is not decoration: every exported
file carries it in metadata, and the visible end card is on by default.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Written into the metadata of every exported timelapse.
RECONSTRUCTION_TYPE = "AI-assisted reconstructed artwork timelapse"
#: The visible end-card line.
END_CARD_TEXT = "Timelapse reconstructed from finished artwork."
#: The short marker required in exported video metadata.
PROCESS_MARKER = "Reconstructed process"
#: Expanded wording stored alongside it.
DISCLOSURE_LONG = (
    "This video is a reconstruction generated from a finished artwork. It is not a recording "
    "of the original creation process."
)


@dataclass(frozen=True, slots=True)
class CanvasPreset:
    key: str
    label: str
    width: int
    height: int
    note: str = ""

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "note": self.note,
        }


CANVAS_PRESETS: dict[str, CanvasPreset] = {
    "square": CanvasPreset("square", "Square 1:1", 1080, 1080, "Instagram feed"),
    "portrait_4x5": CanvasPreset("portrait_4x5", "Portrait 4:5", 1080, 1350, "Instagram portrait"),
    "vertical_9x16": CanvasPreset(
        "vertical_9x16", "Vertical 9:16", 1080, 1920, "TikTok, Reels, Shorts"
    ),
    "landscape_16x9": CanvasPreset(
        "landscape_16x9", "Landscape 16:9", 1920, 1080, "YouTube and web"
    ),
    "source": CanvasPreset("source", "Source aspect ratio", 0, 0, "Matches the artwork"),
}

SUPPORTED_FPS = (24, 30, 60)
MIN_DURATION_SECONDS = 5.0
MAX_DURATION_SECONDS = 300.0


def resolve_canvas(
    preset_key: str, source_size: tuple[int, int], *, max_side: int = 1920
) -> tuple[int, int]:
    """Return the output pixel size for a preset.

    ``source`` keeps the artwork's aspect ratio, capped so a very large canvas
    does not turn into an unencodable frame size. Dimensions are forced even
    because H.264 requires it under yuv420p.
    """
    preset = CANVAS_PRESETS.get(preset_key)
    if preset is None:
        raise KeyError(f"Unknown canvas preset '{preset_key}'.")
    if preset.key != "source":
        return preset.size

    width, height = source_size
    longest = max(width, height)
    if longest > max_side:
        scale = max_side / float(longest)
        width, height = int(round(width * scale)), int(round(height * scale))
    return max(2, width - (width % 2)), max(2, height - (height % 2))


def ease(curve: str, t: float) -> float:
    """Apply a transition curve to a normalised time value."""
    t = max(0.0, min(1.0, float(t)))
    if curve == "linear":
        return t
    if curve == "ease_in":
        return t * t
    if curve == "ease_out":
        return 1.0 - (1.0 - t) ** 2
    # ease_in_out (default): smoothstep
    return t * t * (3.0 - 2.0 * t)


EASING_CURVES = ("linear", "ease_in", "ease_out", "ease_in_out")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Expected a #rrggbb colour, got {value!r}")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
