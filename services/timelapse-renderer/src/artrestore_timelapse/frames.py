"""Frame generation.

Each stage has a *target* - what the canvas looks like when the stage ends - and
a way of getting there. Frames interpolate from the previous stage's target to
this one, following either a structural reveal map or a field of simulated
strokes. Everything is seeded, so the same project renders identically twice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import cv2
import numpy as np

from .analysis import ArtworkAnalysis
from .errors import InvalidPlanError, RenderCancelledError
from .presets import (
    END_CARD_TEXT,
    MAX_DURATION_SECONDS,
    ease,
    hex_to_rgb,
    resolve_canvas,
)
from .reveal import apply_reveal, build_reveal_map
from .stages import Stage
from .strokes import generate_strokes, render_strokes

ProgressCallback = Callable[[float, str], None]


@dataclass(slots=True)
class RenderOptions:
    """Everything the user controls about a render."""

    fps: int = 30
    preset: str = "square"
    background_colour: str = "#F7F4EF"
    transition_curve: str = "ease_in_out"
    stroke_speed: float = 1.0
    stroke_density: float = 1.0
    brush_size_min: int = 6
    brush_size_max: int = 48
    seed: int = 0
    zoom_pan: bool = False
    show_cursor: bool = False
    end_card_disclosure: bool = True
    end_card_seconds: float = 1.6
    preview: bool = False
    preview_max_side: int = 480
    brand_watermark: np.ndarray | None = None
    brand_watermark_opacity: float = 0.75

    def to_dict(self) -> dict:
        return {
            "fps": self.fps,
            "preset": self.preset,
            "background_colour": self.background_colour,
            "transition_curve": self.transition_curve,
            "stroke_speed": self.stroke_speed,
            "stroke_density": self.stroke_density,
            "brush_size_min": self.brush_size_min,
            "brush_size_max": self.brush_size_max,
            "seed": self.seed,
            "zoom_pan": self.zoom_pan,
            "show_cursor": self.show_cursor,
            "end_card_disclosure": self.end_card_disclosure,
            "end_card_seconds": self.end_card_seconds,
            "preview": self.preview,
            "has_brand_watermark": self.brand_watermark is not None,
        }


@dataclass(slots=True)
class RenderPlan:
    """A plan resolved down to exact frame counts."""

    stages: list[Stage]
    frame_counts: list[int]
    end_card_frames: int
    width: int
    height: int
    fps: int

    @property
    def total_frames(self) -> int:
        return sum(self.frame_counts) + self.end_card_frames

    @property
    def duration_seconds(self) -> float:
        return round(self.total_frames / float(self.fps), 3)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "total_frames": self.total_frames,
            "duration_seconds": self.duration_seconds,
            "end_card_frames": self.end_card_frames,
            "stages": [
                {**stage.to_dict(), "frames": frames}
                for stage, frames in zip(self.stages, self.frame_counts, strict=True)
            ],
        }


class TimelapseRenderer:
    """Turns an analysis plus a stage plan into frames."""

    def __init__(
        self,
        analysis: ArtworkAnalysis,
        stages: list[Stage],
        options: RenderOptions | None = None,
        *,
        intermediates: list[np.ndarray] | None = None,
        line_art: np.ndarray | None = None,
    ) -> None:
        self.analysis = analysis
        self.options = options or RenderOptions()
        self.intermediates = intermediates or []
        self.line_art = line_art
        self.stages = [stage for stage in stages if stage.enabled and stage.duration > 0]
        if not self.stages:
            raise InvalidPlanError("The timeline has no enabled stages.")
        self.plan = self._resolve_plan()
        self._rng = np.random.default_rng(self.options.seed)
        self._graphite: np.ndarray | None = None

    # -- planning -----------------------------------------------------------

    def _resolve_plan(self) -> RenderPlan:
        options = self.options
        width, height = resolve_canvas(options.preset, self.analysis.size)
        if options.preview:
            longest = max(width, height)
            if longest > options.preview_max_side:
                scale = options.preview_max_side / float(longest)
                width = max(2, int(width * scale))
                height = max(2, int(height * scale))
        # H.264 under yuv420p needs even dimensions.
        width -= width % 2
        height -= height % 2

        fps = int(options.fps)
        total = sum(stage.duration for stage in self.stages)
        if total > MAX_DURATION_SECONDS:
            raise InvalidPlanError(
                f"The timeline is {total:.1f}s; the maximum is {MAX_DURATION_SECONDS:.0f}s.",
                details={"duration": total},
            )

        counts = [max(1, int(round(stage.duration * fps))) for stage in self.stages]
        end_card = (
            max(1, int(round(options.end_card_seconds * fps))) if options.end_card_disclosure else 0
        )
        return RenderPlan(
            stages=self.stages,
            frame_counts=counts,
            end_card_frames=end_card,
            width=width,
            height=height,
            fps=fps,
        )

    # -- stage targets ------------------------------------------------------

    def _background(self) -> np.ndarray:
        """The empty canvas, with a whisper of paper grain so it reads as a
        physical surface rather than a flat colour fill."""
        colour = hex_to_rgb(self.options.background_colour)
        height, width = self.analysis.rgb.shape[:2]
        canvas = np.zeros((height, width, 3), np.float32)
        canvas[:, :] = colour

        rng = np.random.default_rng(self.options.seed + 733)
        fine = rng.normal(0.0, 1.0, (height, width)).astype(np.float32)
        fibre = rng.normal(0.0, 1.0, (height, width)).astype(np.float32)
        fibre = cv2.GaussianBlur(fibre, (0, 0), 3.5)
        fibre_scale = 4.5 / (float(np.abs(fibre).max()) or 1.0)
        grain = (fine * 1.6 + fibre * fibre_scale)[:, :, None]
        return np.clip(canvas + grain, 0, 255).astype(np.uint8)

    def _lines_over(self, base: np.ndarray, *, strength: float, jitter: float = 0.0) -> np.ndarray:
        """Composite the artwork's line structure over a base image.

        The ink is broken up with a graphite texture - pencil never deposits
        evenly - so the sketch stages read as hand-drawn rather than printed.
        """
        lines = self.line_art if self.line_art is not None else self.analysis.line_art
        lines = lines.astype(np.float32) / 255.0
        if jitter > 0:
            # A construction sketch is deliberately imprecise.
            shift = self._sketch_jitter(lines.shape, jitter)
            lines = cv2.remap(lines, shift[0], shift[1], cv2.INTER_LINEAR)
            lines = cv2.GaussianBlur(lines, (0, 0), 1.2 * jitter)
        alpha = np.clip(lines * strength, 0.0, 1.0) * self._graphite_texture(lines.shape)
        alpha = alpha[:, :, None]
        ink = np.zeros_like(base, np.float32)
        ink[:, :] = (46, 44, 52)
        return np.clip(ink * alpha + base.astype(np.float32) * (1.0 - alpha), 0, 255).astype(
            np.uint8
        )

    def _graphite_texture(self, shape: tuple[int, int]) -> np.ndarray:
        """A 0.55..1.0 multiplier that breaks lines up like pencil on tooth."""
        if self._graphite is None or self._graphite.shape != shape:
            rng = np.random.default_rng(self.options.seed + 577)
            speck = rng.random(shape).astype(np.float32)
            speck = cv2.GaussianBlur(speck, (0, 0), 0.7)
            drag = rng.random(shape).astype(np.float32)
            drag = cv2.GaussianBlur(drag, (0, 0), sigmaX=2.6, sigmaY=0.6)
            for field in (speck, drag):
                low, high = float(field.min()), float(field.max())
                field -= low
                field /= (high - low) or 1.0
            self._graphite = np.clip(0.55 + speck * 0.28 + drag * 0.24, 0.0, 1.0)
        return self._graphite

    def _sketch_jitter(self, shape: tuple[int, int], amount: float):
        height, width = shape
        rng = np.random.default_rng(self.options.seed + 991)
        noise_x = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 24)
        noise_y = cv2.GaussianBlur(rng.normal(0, 1, (height, width)).astype(np.float32), (0, 0), 24)
        scale = 6.0 * amount / (float(np.abs(noise_x).max()) or 1.0)
        grid_x, grid_y = np.meshgrid(
            np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
        )
        return (grid_x + noise_x * scale, grid_y + noise_y * scale)

    def _stage_target(self, stage: Stage, previous: np.ndarray) -> np.ndarray:
        analysis = self.analysis
        kind = stage.stage_type

        if kind == "blank_canvas":
            return self._background()
        if kind == "hold":
            # A deliberate pause: the canvas stays exactly as it is, the way an
            # artist stops to look the sketch over before committing to colour.
            return previous
        if kind == "construction_sketch":
            return self._lines_over(
                self._background(), strength=0.45, jitter=float(stage.settings.get("jitter", 1.0))
            )
        if kind == "refined_lines":
            return self._lines_over(self._background(), strength=0.9)
        if kind == "base_colours":
            return self._lines_over(analysis.flat_colours, strength=0.55)
        if kind == "shadows":
            shaded = self._apply_tonal(analysis.flat_colours, analysis.shadows, factor=-0.35)
            return self._lines_over(shaded, strength=0.45)
        if kind == "highlights":
            lifted = self._apply_tonal(previous, analysis.highlights, factor=0.30)
            return self._lines_over(lifted, strength=0.3)
        if kind in ("texture_details", "colour_correction", "polish", "final_hold"):
            return np.ascontiguousarray(analysis.rgb)
        if kind == "background":
            mask = analysis.background_mask[:, :, None]
            return np.clip(
                analysis.rgb.astype(np.float32) * mask
                + self._background().astype(np.float32) * (1.0 - mask),
                0,
                255,
            ).astype(np.uint8)
        if kind == "silhouette":
            return self._silhouette(previous)
        if kind == "colour_groups":
            return analysis.flat_colours
        if kind == "focal_details":
            weight = np.clip(analysis.saliency * 1.5, 0.0, 1.0)[:, :, None]
            return np.clip(
                analysis.rgb.astype(np.float32) * weight
                + previous.astype(np.float32) * (1.0 - weight),
                0,
                255,
            ).astype(np.uint8)
        if kind in ("broad_forms", "secondary_forms", "detail_pass"):
            level = int(stage.settings.get("pyramid_level", 2))
            level = max(0, min(level, len(analysis.pyramid) - 1))
            return np.ascontiguousarray(analysis.pyramid[level])
        if kind == "stroke_pass":
            # Successive passes paint toward successively sharper versions of
            # the artwork, so a strokes video keeps visibly evolving instead of
            # being finished by the end of the first pass.
            pass_levels = {"structure": 1, "mass": 3}
            pass_name = str(stage.settings.get("pass", "detail"))
            if pass_name in pass_levels and analysis.pyramid:
                level = min(pass_levels[pass_name], len(analysis.pyramid) - 1)
                return np.ascontiguousarray(analysis.pyramid[level])
            return np.ascontiguousarray(analysis.rgb)
        if kind == "real_intermediate":
            index = int(stage.settings.get("intermediate_index", 0))
            if 0 <= index < len(self.intermediates):
                return self._fit_to_analysis(self.intermediates[index])
            # Missing upload: hold the previous stage rather than substituting a
            # generated frame in place of an authentic one.
            return previous
        return np.ascontiguousarray(analysis.rgb)

    def _apply_tonal(self, base: np.ndarray, mask: np.ndarray, *, factor: float) -> np.ndarray:
        weight = np.clip(mask, 0.0, 1.0)[:, :, None]
        adjusted = base.astype(np.float32) * (1.0 + factor * weight)
        return np.clip(adjusted, 0, 255).astype(np.uint8)

    def _silhouette(self, previous: np.ndarray) -> np.ndarray:
        analysis = self.analysis
        mask = (analysis.subject_mask > 0.45).astype(np.float32)
        mask = cv2.GaussianBlur(mask, (0, 0), 2.0)[:, :, None]
        subject_pixels = analysis.rgb[analysis.subject_mask > 0.45]
        colour = (
            subject_pixels.mean(axis=0) if subject_pixels.size else np.array([120.0, 120.0, 120.0])
        )
        block = np.zeros_like(analysis.rgb, np.float32)
        block[:, :] = colour * 0.85
        return np.clip(block * mask + previous.astype(np.float32) * (1.0 - mask), 0, 255).astype(
            np.uint8
        )

    def _fit_to_analysis(self, image: np.ndarray) -> np.ndarray:
        height, width = self.analysis.rgb.shape[:2]
        if image.shape[0] == height and image.shape[1] == width:
            return np.ascontiguousarray(image)
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    # -- frames -------------------------------------------------------------

    def iter_frames(
        self,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterator[np.ndarray]:
        """Yield every frame of the reconstruction, in order."""
        options = self.options
        previous = self._background()
        emitted = 0
        total = self.plan.total_frames

        for stage_index, (stage, frame_count) in enumerate(
            zip(self.plan.stages, self.plan.frame_counts, strict=True)
        ):
            if should_cancel and should_cancel():
                raise RenderCancelledError("The render was cancelled.")

            target = self._stage_target(stage, previous)
            reveal_kind = str(stage.settings.get("reveal", "organic"))
            stage_rng = np.random.default_rng(options.seed * 7919 + stage_index)

            stroke_field = None
            reveal_map = None
            if stage.stage_type == "stroke_pass":
                stroke_field = generate_strokes(
                    self.analysis,
                    pass_name=str(stage.settings.get("pass", "structure")),
                    density=options.stroke_density,
                    brush_min=float(options.brush_size_min)
                    * float(stage.settings.get("brush_scale", 1.0)),
                    brush_max=float(options.brush_size_max)
                    * float(stage.settings.get("brush_scale", 1.0)),
                    seed=options.seed + stage_index,
                )
            elif stage.stage_type not in ("hold", "final_hold"):
                reveal_map = build_reveal_map(reveal_kind, self.analysis, rng=stage_rng)

            for frame_index in range(frame_count):
                if should_cancel and should_cancel() and frame_index % 8 == 0:
                    raise RenderCancelledError("The render was cancelled.")

                raw = (frame_index + 1) / float(frame_count)
                eased = ease(options.transition_curve, raw)

                if stroke_field is not None:
                    canvas = render_strokes(
                        previous, target, stroke_field, eased * options.stroke_speed
                    )
                    # Strokes never cover every pixel; wash the remainder in
                    # over the stage's last moments so the cut to the next
                    # stage does not pop.
                    if raw > 0.85:
                        wash = ((raw - 0.85) / 0.15) ** 2
                        canvas = np.clip(
                            target.astype(np.float32) * wash
                            + canvas.astype(np.float32) * (1.0 - wash),
                            0,
                            255,
                        ).astype(np.uint8)
                elif reveal_map is not None:
                    canvas = apply_reveal(previous, target, reveal_map, eased)
                else:
                    canvas = target

                frame = self._present(canvas, emitted / float(max(1, total - 1)))
                if options.show_cursor and stroke_field is not None:
                    frame = self._draw_cursor(frame, stroke_field, eased * options.stroke_speed)
                yield frame

                emitted += 1
                if progress is not None and emitted % 5 == 0:
                    progress(
                        emitted / float(total),
                        f"Rendering {stage.label or stage.stage_type} "
                        f"({emitted}/{total} frames)",
                    )

            previous = target

        for index in range(self.plan.end_card_frames):
            frame = self._present(previous, 1.0)
            fade = min(1.0, (index + 1) / max(1.0, self.plan.end_card_frames * 0.25))
            yield self._draw_end_card(frame, fade)
            emitted += 1
        if progress is not None:
            progress(1.0, "Frames complete")

    # -- presentation -------------------------------------------------------

    def _present(self, canvas: np.ndarray, timeline_position: float) -> np.ndarray:
        """Fit the artwork onto the output canvas, with optional camera move."""
        width, height = self.plan.width, self.plan.height
        source = canvas
        if self.options.zoom_pan:
            source = self._camera_move(source, timeline_position)

        source_height, source_width = source.shape[:2]
        scale = min(width / float(source_width), height / float(source_height))
        new_size = (max(1, int(source_width * scale)), max(1, int(source_height * scale)))
        resized = cv2.resize(source, new_size, interpolation=cv2.INTER_AREA)

        frame = np.zeros((height, width, 3), np.uint8)
        frame[:, :] = hex_to_rgb(self.options.background_colour)
        offset_x = (width - new_size[0]) // 2
        offset_y = (height - new_size[1]) // 2
        frame[offset_y : offset_y + new_size[1], offset_x : offset_x + new_size[0]] = resized

        if self.options.brand_watermark is not None:
            frame = self._apply_brand(frame)
        return frame

    def _camera_move(self, canvas: np.ndarray, position: float) -> np.ndarray:
        """A slow push-in toward the focal point."""
        height, width = canvas.shape[:2]
        zoom = 1.0 + 0.08 * position
        crop_w = int(width / zoom)
        crop_h = int(height / zoom)
        centre_y, centre_x = _weighted_centre(self.analysis.saliency)
        x0 = int(np.clip(centre_x - crop_w / 2, 0, width - crop_w))
        y0 = int(np.clip(centre_y - crop_h / 2, 0, height - crop_h))
        return canvas[y0 : y0 + crop_h, x0 : x0 + crop_w]

    def _apply_brand(self, frame: np.ndarray) -> np.ndarray:
        """Overlay the user's own brand mark, bottom-right, with a margin."""
        mark = self.options.brand_watermark
        if mark is None:
            return frame
        height, width = frame.shape[:2]
        target_width = max(24, int(width * 0.18))
        scale = target_width / float(mark.shape[1])
        resized = cv2.resize(
            mark, (target_width, max(1, int(mark.shape[0] * scale))), interpolation=cv2.INTER_AREA
        )

        if resized.shape[2] == 4:
            alpha = resized[:, :, 3:4].astype(np.float32) / 255.0
            rgb = resized[:, :, :3]
        else:
            alpha = np.ones((*resized.shape[:2], 1), np.float32)
            rgb = resized
        alpha = alpha * float(np.clip(self.options.brand_watermark_opacity, 0.0, 1.0))

        margin = int(min(width, height) * 0.04)
        y1 = height - margin
        y0 = max(0, y1 - resized.shape[0])
        x1 = width - margin
        x0 = max(0, x1 - resized.shape[1])
        region = frame[y0:y1, x0:x1].astype(np.float32)
        overlay = rgb[: y1 - y0, : x1 - x0].astype(np.float32)
        alpha = alpha[: y1 - y0, : x1 - x0]
        frame[y0:y1, x0:x1] = np.clip(overlay * alpha + region * (1.0 - alpha), 0, 255).astype(
            np.uint8
        )
        return frame

    def _draw_cursor(self, frame: np.ndarray, stroke_field, progress: float) -> np.ndarray:
        """A brush marker at the stroke currently being drawn.

        Decorative only. Exports state that cursor motion is simulated, never
        that it is recorded input history.
        """
        active = [stroke for stroke in stroke_field.strokes if stroke.order <= progress]
        if not active:
            return frame
        stroke = active[-1]
        local = float(np.clip((progress - stroke.order) * max(0.2, stroke.speed) * 6.0, 0.0, 1.0))
        point_index = min(len(stroke.points) - 1, int(len(stroke.points) * local))
        x, y = stroke.points[point_index]

        height, width = frame.shape[:2]
        source_h, source_w = self.analysis.rgb.shape[:2]
        scale = min(width / float(source_w), height / float(source_h))
        offset_x = (width - int(source_w * scale)) // 2
        offset_y = (height - int(source_h * scale)) // 2
        centre = (int(x * scale) + offset_x, int(y * scale) + offset_y)

        overlay = frame.copy()
        radius = max(4, int(stroke.width * scale * 0.5))
        cv2.circle(overlay, centre, radius, (250, 250, 250), -1, cv2.LINE_AA)
        cv2.circle(overlay, centre, radius, (40, 40, 44), 2, cv2.LINE_AA)
        return cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)

    def _draw_end_card(self, frame: np.ndarray, fade: float) -> np.ndarray:
        """The default-on disclosure card.

        The artwork dims gently and the statement sits in a soft chip near the
        bottom - present and legible without shouting over the piece.
        """
        height, width = frame.shape[:2]
        dimmed = np.clip(frame.astype(np.float32) * (1.0 - 0.38 * fade), 0, 255).astype(np.uint8)

        font = _end_card_font(max(15, int(width / 34)))
        if font is None:
            return self._draw_end_card_fallback(dimmed, fade)

        from PIL import Image, ImageDraw

        image = Image.fromarray(dimmed).convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        left, top, right, bottom = draw.textbbox((0, 0), END_CARD_TEXT, font=font)
        text_width, text_height = right - left, bottom - top
        pad_x = max(14, text_height)
        pad_y = max(10, text_height // 2)
        chip_width = min(width - 16, text_width + pad_x * 2)
        chip_height = text_height + pad_y * 2
        chip_x = (width - chip_width) // 2
        chip_y = int(height * 0.82) - chip_height // 2
        chip_y = max(8, min(chip_y, height - chip_height - 8))

        draw.rounded_rectangle(
            (chip_x, chip_y, chip_x + chip_width, chip_y + chip_height),
            radius=chip_height // 2,
            fill=(16, 15, 20, int(190 * fade)),
        )
        draw.text(
            (chip_x + (chip_width - text_width) // 2 - left, chip_y + pad_y - top),
            END_CARD_TEXT,
            font=font,
            fill=(246, 244, 239, int(255 * fade)),
        )
        return np.asarray(Image.alpha_composite(image, overlay).convert("RGB"))

    def _draw_end_card_fallback(self, dimmed: np.ndarray, fade: float) -> np.ndarray:
        """cv2-only card for deployments without a usable TrueType font."""
        height, width = dimmed.shape[:2]
        band_height = max(48, int(height * 0.12))
        overlay = dimmed.copy()
        cv2.rectangle(overlay, (0, height - band_height), (width, height), (16, 15, 20), -1)
        frame = cv2.addWeighted(overlay, 0.7 * fade, dimmed, 1.0 - 0.7 * fade, 0)

        scale = max(0.45, width / 1400.0)
        thickness = max(1, int(round(scale * 1.6)))
        (text_width, text_height), _ = cv2.getTextSize(
            END_CARD_TEXT, cv2.FONT_HERSHEY_DUPLEX, scale, thickness
        )
        origin = (max(8, (width - text_width) // 2), height - band_height // 2 + text_height // 2)
        colour = int(245 * fade + 18 * (1 - fade))
        cv2.putText(
            frame,
            END_CARD_TEXT,
            origin,
            cv2.FONT_HERSHEY_DUPLEX,
            scale,
            (colour, colour, colour),
            thickness,
            cv2.LINE_AA,
        )
        return frame


_END_CARD_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_end_card_font_cache: dict[int, object] = {}


def _end_card_font(size: int):
    """A TrueType font for the end card, or None to fall back to cv2 text."""
    if size in _end_card_font_cache:
        return _end_card_font_cache[size]
    font = None
    try:
        from PIL import ImageFont

        for path in _END_CARD_FONT_PATHS:
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    except ImportError:  # pragma: no cover - PIL is a hard dependency in practice
        font = None
    _end_card_font_cache[size] = font
    return font


def _weighted_centre(field: np.ndarray) -> tuple[float, float]:
    total = float(field.sum()) or 1.0
    yy, xx = np.mgrid[0 : field.shape[0], 0 : field.shape[1]].astype(np.float32)
    return float((yy * field).sum() / total), float((xx * field).sum() / total)
