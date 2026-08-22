"""Decompose a finished artwork into the layers a process video moves through.

The renderer never simply fades the finished image in. It needs to know where
the background is, which colour masses dominate, where the line structure runs,
which pixels are shadow and which are highlight, and where the fine detail
lives - so that forms can appear before details, and strokes can follow the
artwork's own directions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

#: Number of colour clusters used for the flat "base colours" stage.
DEFAULT_PALETTE_SIZE = 8
#: Analysis runs at this longest side; results are scaled back up on demand.
ANALYSIS_MAX_SIDE = 900


@dataclass(slots=True)
class ArtworkAnalysis:
    """Everything the stage renderers need, computed once per artwork."""

    rgb: np.ndarray
    luminance: np.ndarray
    background_colour: tuple[int, int, int]
    palette: np.ndarray  # (k, 3) uint8
    palette_labels: np.ndarray  # HxW int32
    palette_shares: np.ndarray  # (k,) float
    flat_colours: np.ndarray  # HxW x3 uint8, the quantised painting
    edges: np.ndarray  # HxW uint8
    line_art: np.ndarray  # HxW uint8, thinned structure
    orientation: np.ndarray  # HxW float32 radians, local edge direction
    detail_map: np.ndarray  # HxW float32 0..1 high-frequency energy
    scale_map: np.ndarray  # HxW float32 0..1, 0 = broad form, 1 = fine detail
    shadows: np.ndarray  # HxW float32 0..1
    highlights: np.ndarray  # HxW float32 0..1
    saliency: np.ndarray  # HxW float32 0..1
    background_mask: np.ndarray  # HxW float32 0..1
    subject_mask: np.ndarray  # HxW float32 0..1
    pyramid: list[np.ndarray] = field(default_factory=list)  # coarse -> fine

    @property
    def size(self) -> tuple[int, int]:
        return self.rgb.shape[1], self.rgb.shape[0]

    def summary(self) -> dict:
        """A JSON-serialisable description, stored on the analysis job."""
        return {
            "width": int(self.rgb.shape[1]),
            "height": int(self.rgb.shape[0]),
            "background_colour": [int(value) for value in self.background_colour],
            "palette": [[int(channel) for channel in colour] for colour in self.palette],
            "palette_shares": [round(float(share), 4) for share in self.palette_shares],
            "edge_density": round(float((self.edges > 0).mean()), 4),
            "detail_energy": round(float(self.detail_map.mean()), 4),
            "shadow_share": round(float((self.shadows > 0.5).mean()), 4),
            "highlight_share": round(float((self.highlights > 0.5).mean()), 4),
            "background_share": round(float((self.background_mask > 0.5).mean()), 4),
            "subject_share": round(float((self.subject_mask > 0.5).mean()), 4),
            "pyramid_levels": len(self.pyramid),
        }


def analyse_artwork(
    rgb: np.ndarray, *, palette_size: int = DEFAULT_PALETTE_SIZE, seed: int = 0
) -> ArtworkAnalysis:
    """Analyse a finished artwork. Deterministic for a given ``seed``."""
    working = _fit_for_analysis(rgb)
    height, width = working.shape[:2]
    luminance = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY).astype(np.float32)

    palette, labels, shares = _quantise_colours(working, palette_size, seed)
    flat_colours = palette[labels].astype(np.uint8)

    edges = cv2.Canny(cv2.GaussianBlur(working, (3, 3), 0), 60, 150)
    line_art = _thin_lines(edges)
    orientation = _edge_orientation(luminance)

    detail_map = _detail_energy(luminance)
    scale_map = _scale_map(luminance)

    shadows, highlights = _tonal_masks(luminance)
    saliency = _spectral_saliency(luminance)
    background_mask, subject_mask = _background_and_subject(working, saliency, labels, shares)

    pyramid = _build_pyramid(working)
    background_colour = _dominant_border_colour(working)

    return ArtworkAnalysis(
        rgb=working,
        luminance=luminance,
        background_colour=background_colour,
        palette=palette,
        palette_labels=labels,
        palette_shares=shares,
        flat_colours=flat_colours,
        edges=edges,
        line_art=line_art,
        orientation=orientation,
        detail_map=detail_map,
        scale_map=scale_map,
        shadows=shadows,
        highlights=highlights,
        saliency=saliency,
        background_mask=background_mask,
        subject_mask=subject_mask,
        pyramid=pyramid,
    )


# ---------------------------------------------------------------------------


def _fit_for_analysis(rgb: np.ndarray) -> np.ndarray:
    height, width = rgb.shape[:2]
    longest = max(height, width)
    if longest <= ANALYSIS_MAX_SIDE:
        return np.ascontiguousarray(rgb)
    scale = ANALYSIS_MAX_SIDE / float(longest)
    return cv2.resize(
        rgb, (max(2, int(width * scale)), max(2, int(height * scale))), interpolation=cv2.INTER_AREA
    )


def _quantise_colours(rgb: np.ndarray, k: int, seed: int):
    """k-means over Lab so clusters follow perceived colour, not raw RGB."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    k = max(2, min(int(k), 16))

    rng = np.random.default_rng(seed)
    sample_count = min(len(lab), 40_000)
    sample_index = rng.choice(len(lab), size=sample_count, replace=False)
    samples = lab[sample_index]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 24, 1.0)
    cv2.setRNGSeed(int(seed) & 0x7FFFFFFF)
    _, _, centres = cv2.kmeans(samples, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)

    # Assign every pixel to its nearest centre.
    distances = ((lab[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
    labels = np.argmin(distances, axis=1).astype(np.int32)

    centres_rgb = cv2.cvtColor(
        centres.reshape(1, -1, 3).astype(np.uint8), cv2.COLOR_LAB2RGB
    ).reshape(-1, 3)

    counts = np.bincount(labels, minlength=k).astype(np.float64)
    shares = counts / counts.sum()

    # Order the palette from most to least of the image so "main colour groups"
    # means what it says.
    order = np.argsort(-shares)
    remap = np.zeros(k, dtype=np.int32)
    remap[order] = np.arange(k)
    labels = remap[labels].reshape(rgb.shape[:2])

    return centres_rgb[order].astype(np.uint8), labels, shares[order]


def _thin_lines(edges: np.ndarray) -> np.ndarray:
    """A one-pixel-ish line layer for the sketch and line-art stages."""
    closed = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    return cv2.erode(closed, np.ones((2, 2), np.uint8), iterations=1)


def _edge_orientation(luminance: np.ndarray) -> np.ndarray:
    """Local edge direction; strokes follow this instead of a fixed angle."""
    gx = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=5)
    gx = cv2.GaussianBlur(gx, (0, 0), 3.0)
    gy = cv2.GaussianBlur(gy, (0, 0), 3.0)
    # Rotate the gradient by 90 degrees to get the direction *along* the edge.
    return np.arctan2(gx, -gy).astype(np.float32)


def _detail_energy(luminance: np.ndarray) -> np.ndarray:
    high_frequency = np.abs(luminance - cv2.GaussianBlur(luminance, (0, 0), 1.5))
    energy = cv2.GaussianBlur(high_frequency, (0, 0), 3.0)
    peak = float(energy.max()) or 1.0
    return np.clip(energy / peak, 0.0, 1.0).astype(np.float32)


def _scale_map(luminance: np.ndarray) -> np.ndarray:
    """0 where content is a broad form, 1 where it is fine detail.

    Built by comparing successively blurred versions: pixels that survive heavy
    blurring belong to large forms, pixels that only exist at fine scales are
    detail. This is what lets a reveal show masses before specifics.
    """
    coarse = cv2.GaussianBlur(luminance, (0, 0), 12.0)
    medium = cv2.GaussianBlur(luminance, (0, 0), 4.0)
    broad_energy = np.abs(medium - coarse)
    fine_energy = np.abs(luminance - medium)
    total = broad_energy + fine_energy + 1e-3
    ratio = fine_energy / total
    ratio = cv2.GaussianBlur(ratio, (0, 0), 2.0)
    return np.clip(ratio, 0.0, 1.0).astype(np.float32)


def _tonal_masks(luminance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    smooth = cv2.GaussianBlur(luminance, (0, 0), 2.0)
    dark_threshold = float(np.percentile(smooth, 28))
    light_threshold = float(np.percentile(smooth, 82))
    span = max(1.0, float(smooth.max() - smooth.min()))

    shadows = np.clip((dark_threshold - smooth) / (span * 0.35) + 0.5, 0.0, 1.0)
    highlights = np.clip((smooth - light_threshold) / (span * 0.35) + 0.5, 0.0, 1.0)
    shadows = np.where(smooth <= dark_threshold, shadows, 0.0)
    highlights = np.where(smooth >= light_threshold, highlights, 0.0)
    return shadows.astype(np.float32), highlights.astype(np.float32)


def _spectral_saliency(luminance: np.ndarray) -> np.ndarray:
    """Spectral-residual saliency: cheap, deterministic, no model required."""
    small = cv2.resize(luminance, (128, 128), interpolation=cv2.INTER_AREA)
    spectrum = np.fft.fft2(small)
    log_amplitude = np.log(np.abs(spectrum) + 1e-6)
    phase = np.angle(spectrum)
    smoothed = cv2.blur(log_amplitude, (3, 3))
    residual = log_amplitude - smoothed
    reconstructed = np.abs(np.fft.ifft2(np.exp(residual + 1j * phase))) ** 2
    reconstructed = cv2.GaussianBlur(reconstructed, (0, 0), 3.0)
    peak = float(reconstructed.max()) or 1.0
    saliency = cv2.resize(
        (reconstructed / peak).astype(np.float32),
        (luminance.shape[1], luminance.shape[0]),
        interpolation=cv2.INTER_CUBIC,
    )
    return np.clip(saliency, 0.0, 1.0)


def _background_and_subject(
    rgb: np.ndarray, saliency: np.ndarray, labels: np.ndarray, shares: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Split the canvas into background and subject.

    Colour clusters that dominate the frame edges are background; the salient
    remainder is the subject. Good enough to make "background first, subject
    second" read correctly, without a segmentation model.
    """
    height, width = labels.shape
    border = np.zeros((height, width), dtype=bool)
    margin = max(2, int(min(height, width) * 0.06))
    border[:margin, :] = True
    border[-margin:, :] = True
    border[:, :margin] = True
    border[:, -margin:] = True

    border_labels = labels[border]
    counts = np.bincount(border_labels, minlength=len(shares)).astype(np.float64)
    border_share = counts / max(1.0, counts.sum())
    background_clusters = {
        index for index, value in enumerate(border_share) if value >= 0.15
    }
    if not background_clusters:
        background_clusters = {int(np.argmax(border_share))}

    background = np.isin(labels, list(background_clusters)).astype(np.float32)
    background = cv2.GaussianBlur(background, (0, 0), 3.0)

    subject = np.clip(1.0 - background, 0.0, 1.0)
    subject = np.clip(subject * 0.7 + saliency * 0.6, 0.0, 1.0)
    return background.astype(np.float32), subject.astype(np.float32)


def _build_pyramid(rgb: np.ndarray, levels: int = 5) -> list[np.ndarray]:
    """Coarse-to-fine versions of the artwork used by the paint-reveal mode."""
    pyramid: list[np.ndarray] = []
    for level in range(levels, 0, -1):
        sigma = 1.6 * (2 ** (level - 1))
        pyramid.append(cv2.GaussianBlur(rgb, (0, 0), sigma))
    pyramid.append(np.ascontiguousarray(rgb))
    return pyramid


def _dominant_border_colour(rgb: np.ndarray) -> tuple[int, int, int]:
    height, width = rgb.shape[:2]
    margin = max(1, int(min(height, width) * 0.03))
    strips = np.concatenate(
        [
            rgb[:margin, :].reshape(-1, 3),
            rgb[-margin:, :].reshape(-1, 3),
            rgb[:, :margin].reshape(-1, 3),
            rgb[:, -margin:].reshape(-1, 3),
        ]
    )
    median = np.median(strips, axis=0)
    return int(median[0]), int(median[1]), int(median[2])
