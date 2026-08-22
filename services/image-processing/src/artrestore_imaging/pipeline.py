"""The authorized visible-watermark cleanup pipeline.

    validate -> safe raster -> normalise mask -> protected-region check ->
    background analysis -> mode selection -> inpaint -> edge/colour correction ->
    grain -> feathered composite -> previews

The source asset is never overwritten: every run produces new pixels and the
caller stores them under a new key.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import restoration
from .detection import DetectionConfig, ProtectionAssessment, assess_mask, detect_protected_regions
from .errors import MaskError, ProtectedRegionError, ProtectedRegionReviewError
from .inpainting import InpaintRequest, available_backends, get_backend
from .masks import MaskAdjustments, mask_components, mask_coverage, normalize_mask
from .raster import SafeRaster, downscale

ProgressCallback = Callable[[float, str], None]

#: The four user-facing processing modes.
CLEANUP_MODES: tuple[str, ...] = ("fast_fill", "texture_restore", "edge_aware", "art_mode")

MODE_LABELS = {
    "fast_fill": "Fast Fill",
    "texture_restore": "Texture Restore",
    "edge_aware": "Edge-Aware Restore",
    "art_mode": "Art Mode",
}


@dataclass(slots=True)
class CleanupOptions:
    """User-controlled cleanup parameters."""

    mode: str = "fast_fill"
    adjustments: MaskAdjustments = field(default_factory=MaskAdjustments)
    inpaint_radius: int = 5
    grain_strength: float = 1.0
    edge_strength: float = 0.6
    colour_match: bool = True
    seed: int = 0
    backend_override: str | None = None
    protected_enforcement: str = "block"
    #: Region kinds the user has explicitly attested are not attribution
    #: content. Only clears ``review`` severity findings - never ``block``.
    acknowledged_protected_kinds: tuple[str, ...] = ()
    detection_config: DetectionConfig = field(default_factory=DetectionConfig)
    backend_settings: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> CleanupOptions:
        data = data or {}
        mode = str(data.get("mode", "fast_fill"))
        if mode not in CLEANUP_MODES:
            mode = "fast_fill"
        return cls(
            mode=mode,
            adjustments=MaskAdjustments.from_dict(data.get("adjustments")),
            inpaint_radius=int(max(1, min(64, int(data.get("inpaint_radius", 5))))),
            grain_strength=float(max(0.0, min(2.0, float(data.get("grain_strength", 1.0))))),
            edge_strength=float(max(0.0, min(2.0, float(data.get("edge_strength", 0.6))))),
            colour_match=bool(data.get("colour_match", True)),
            seed=int(data.get("seed", 0)),
            backend_override=data.get("backend") or None,
            protected_enforcement=str(data.get("protected_enforcement", "block")),
            acknowledged_protected_kinds=tuple(
                str(kind) for kind in (data.get("acknowledged_protected_kinds") or [])
            ),
            backend_settings=dict(data.get("backend_settings") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "adjustments": self.adjustments.to_dict(),
            "inpaint_radius": self.inpaint_radius,
            "grain_strength": self.grain_strength,
            "edge_strength": self.edge_strength,
            "colour_match": self.colour_match,
            "seed": self.seed,
            "backend": self.backend_override,
            "protected_enforcement": self.protected_enforcement,
            "acknowledged_protected_kinds": list(self.acknowledged_protected_kinds),
        }


@dataclass(slots=True)
class BackgroundAnalysis:
    """What the pixels around the mask look like; drives mode selection."""

    texture_energy: float
    edge_density: float
    colour_variance: float
    is_flat: bool
    is_textured: bool
    is_structured: bool
    suggested_mode: str

    def to_dict(self) -> dict:
        return {
            "texture_energy": round(self.texture_energy, 4),
            "edge_density": round(self.edge_density, 4),
            "colour_variance": round(self.colour_variance, 4),
            "is_flat": self.is_flat,
            "is_textured": self.is_textured,
            "is_structured": self.is_structured,
            "suggested_mode": self.suggested_mode,
        }


@dataclass(slots=True)
class CleanupResult:
    """The outcome of one cleanup run."""

    raster: SafeRaster
    mode: str
    backend: str
    analysis: BackgroundAnalysis
    protection: ProtectionAssessment
    mask_coverage: float
    regions: list[dict]
    duration_ms: int
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "backend": self.backend,
            "analysis": self.analysis.to_dict(),
            "protection": self.protection.to_dict(),
            "mask_coverage": round(self.mask_coverage, 5),
            "region_count": len(self.regions),
            "regions": self.regions,
            "duration_ms": self.duration_ms,
            "notes": self.notes,
        }


def analyse_background(rgb: np.ndarray, binary: np.ndarray) -> BackgroundAnalysis:
    """Measure the surroundings of the mask to pick a sensible default mode."""
    ring = restoration.boundary_ring(binary, 18) > 0
    if not ring.any():
        ring = np.ones(binary.shape, dtype=bool)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    high_frequency = gray - cv2.GaussianBlur(gray, (0, 0), 1.5)
    texture_energy = float(np.std(high_frequency[ring]))

    edges = cv2.Canny(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 60, 150)
    edge_density = float((edges[ring] > 0).mean())

    colour_variance = float(np.mean([rgb[:, :, c][ring].std() for c in range(3)]))

    is_flat = texture_energy < 2.5 and edge_density < 0.03
    is_textured = texture_energy >= 3.5
    is_structured = edge_density >= 0.08

    if is_flat:
        suggested = "fast_fill"
    elif is_structured and not is_textured:
        suggested = "edge_aware"
    elif is_textured and edge_density >= 0.05:
        suggested = "art_mode"
    elif is_textured:
        suggested = "texture_restore"
    else:
        suggested = "fast_fill"

    return BackgroundAnalysis(
        texture_energy=texture_energy,
        edge_density=edge_density,
        colour_variance=colour_variance,
        is_flat=is_flat,
        is_textured=is_textured,
        is_structured=is_structured,
        suggested_mode=suggested,
    )


def select_backend_name(mode: str, options: CleanupOptions) -> str:
    """Map a user-facing mode to a registered backend."""
    if options.backend_override:
        return options.backend_override

    settings = options.backend_settings
    installed = set(available_backends(settings))

    if mode == "fast_fill":
        return "opencv_telea"
    if mode == "texture_restore":
        for candidate in ("lama", "diffusion", "patchmatch"):
            if candidate in installed:
                return candidate
        return "opencv_blend"
    if mode == "edge_aware":
        return "lama" if "lama" in installed else "opencv_blend"
    if mode == "art_mode":
        return "patchmatch"
    return "opencv_telea"


def run_cleanup(
    raster: SafeRaster,
    mask: np.ndarray,
    options: CleanupOptions | None = None,
    *,
    progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    provenance: dict | None = None,
) -> CleanupResult:
    """Execute the cleanup pipeline and return reconstructed pixels.

    Raises :class:`ProtectedRegionError` when the mask overlaps attribution or
    provenance content and enforcement is set to ``block``.
    """
    options = options or CleanupOptions()
    started = time.perf_counter()
    notes: list[str] = []

    def emit(fraction: float, message: str) -> None:
        if progress is not None:
            progress(max(0.0, min(1.0, fraction)), message)

    def cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    emit(0.02, "Normalising mask")
    binary, soft = normalize_mask(mask, options.adjustments)
    coverage = mask_coverage(binary)
    if coverage > 0.85:
        raise MaskError(
            "The mask covers almost the entire image. Cleanup is meant for removing "
            "specific marks, not for regenerating the whole picture."
        )
    regions = mask_components(binary)

    emit(0.08, "Checking the selection for attribution and provenance content")
    boxes = [(item["x"], item["y"], item["width"], item["height"]) for item in regions]
    detected = detect_protected_regions(
        raster.rgb,
        config=options.detection_config,
        provenance=provenance or (raster.metadata_summary or {}).get("provenance"),
        candidate_boxes=boxes,
    )
    protection = assess_mask(
        binary,
        detected,
        enforcement=options.protected_enforcement,
        acknowledged_kinds=options.acknowledged_protected_kinds,
    )
    if protection.blocking_overlaps and options.protected_enforcement == "block":
        raise ProtectedRegionError(protection.explanation, details=protection.to_dict())
    if protection.blocked:
        raise ProtectedRegionReviewError(protection.explanation, details=protection.to_dict())
    if protection.overlaps:
        notes.append(
            "Protected content was detected near the selection; processing continued in "
            "warn-only mode as configured by this deployment."
        )

    emit(0.15, "Analysing background structure")
    analysis = analyse_background(raster.rgb, binary)
    mode = options.mode
    backend_name = select_backend_name(mode, options)

    emit(0.2, f"Reconstructing with {MODE_LABELS.get(mode, mode)}")
    if cancelled():
        from .errors import JobCancelledError

        raise JobCancelledError("The job was cancelled before inpainting started.")

    def inner_progress(fraction: float, message: str) -> None:
        emit(0.2 + fraction * 0.55, message)

    filled = _run_mode(
        mode=mode,
        backend_name=backend_name,
        rgb=raster.rgb,
        binary=binary,
        options=options,
        progress=inner_progress,
        should_cancel=should_cancel,
    )

    emit(0.8, "Correcting edges and colour consistency")
    if options.edge_strength > 0 and mode in ("edge_aware", "art_mode", "texture_restore"):
        filled = restoration.continue_edges(
            filled, raster.rgb, binary, strength=options.edge_strength
        )
    if options.colour_match:
        filled = restoration.match_local_colour(filled, raster.rgb, binary)

    if options.grain_strength > 0:
        emit(0.88, "Restoring surface grain")
        filled = restoration.restore_grain(
            filled, raster.rgb, binary, strength=options.grain_strength, seed=options.seed
        )

    emit(0.94, "Compositing the repair")
    composited = restoration.feather_composite(raster.rgb, filled, soft)

    output = raster.with_rgb(composited)
    output.alpha = restoration.preserve_alpha(raster.alpha, binary)

    duration_ms = int((time.perf_counter() - started) * 1000)
    emit(1.0, "Cleanup complete")

    return CleanupResult(
        raster=output,
        mode=mode,
        backend=backend_name,
        analysis=analysis,
        protection=protection,
        mask_coverage=coverage,
        regions=regions,
        duration_ms=duration_ms,
        notes=notes,
    )


def _run_mode(
    *,
    mode: str,
    backend_name: str,
    rgb: np.ndarray,
    binary: np.ndarray,
    options: CleanupOptions,
    progress: ProgressCallback,
    should_cancel: Callable[[], bool] | None,
) -> np.ndarray:
    """Dispatch to the per-mode reconstruction strategy."""
    backend_options = {"settings": options.backend_settings}

    def make_request(
        image: np.ndarray, mask: np.ndarray, extra: dict | None = None
    ) -> InpaintRequest:
        return InpaintRequest(
            rgb=image,
            mask=mask,
            radius=options.inpaint_radius,
            seed=options.seed,
            options={**backend_options, **(extra or {})},
            progress=progress,
            should_cancel=should_cancel,
        )

    if mode in ("fast_fill", "texture_restore"):
        backend = get_backend(backend_name, options.backend_settings)
        return backend.run(make_request(rgb, binary))

    # Edge-Aware and Art Mode use structure/texture decomposition: contours are
    # reconstructed on a smoothed structure layer where diffusion methods are
    # strongest, and the residual texture is synthesised from real neighbouring
    # pixels so brushwork and grain survive.
    sigma_space, sigma_color = (7.0, 30.0) if mode == "edge_aware" else (11.0, 55.0)
    structure, texture = restoration.decompose(
        rgb, sigma_space=sigma_space, sigma_color=sigma_color
    )

    progress(0.1, "Reconstructing structure layer")
    structure_backend = get_backend(
        "opencv_blend" if mode == "edge_aware" else backend_name, options.backend_settings
    )
    filled_structure = structure_backend.run(make_request(structure, binary))

    progress(0.55, "Synthesising surface texture")
    texture_offset = np.clip(texture + 128.0, 0, 255).astype(np.uint8)
    texture_backend = get_backend("patchmatch", options.backend_settings)
    filled_texture_u8 = texture_backend.run(
        make_request(texture_offset, binary, {"patch_radius": 3 if mode == "art_mode" else 4})
    )
    filled_texture = filled_texture_u8.astype(np.float32) - 128.0

    if mode == "art_mode":
        # Painted surfaces carry more texture amplitude than photographs; keep
        # the synthesised residual at full strength inside the repair.
        weight = 1.0
    else:
        weight = 0.85

    progress(0.9, "Recombining structure and texture")
    return restoration.recombine(filled_structure, filled_texture * weight)


def build_previews(
    original: SafeRaster, processed: SafeRaster, *, max_dimension: int = 1200
) -> dict[str, SafeRaster]:
    """Preview rasters for the before/after comparison views."""
    return {
        "before": downscale(original, max_dimension),
        "after": downscale(processed, max_dimension),
    }


def difference_map(original: SafeRaster, processed: SafeRaster) -> np.ndarray:
    """A visualisation of exactly which pixels changed."""
    delta = cv2.absdiff(original.rgb, processed.rgb)
    gray = cv2.cvtColor(delta, cv2.COLOR_RGB2GRAY)
    return cv2.applyColorMap(cv2.convertScaleAbs(gray, alpha=6.0), cv2.COLORMAP_INFERNO)
