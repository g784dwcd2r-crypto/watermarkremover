"""Reveal-order maps.

A reveal map assigns every pixel a value in 0..1: the moment during a stage at
which that pixel switches from the previous image to this stage's target. The
maps are built from the artwork's own structure, never from screen position, so
a stage never reads as a left-to-right wipe.
"""

from __future__ import annotations

import cv2
import numpy as np

from .analysis import ArtworkAnalysis

REVEAL_KINDS = ("organic", "region", "tonal", "detail", "dissolve", "radial")


def _rank_normalise(field: np.ndarray) -> np.ndarray:
    """Map arbitrary values onto a uniform 0..1 by rank.

    Rank rather than min-max, so a stage always reveals at a steady visual pace
    whatever the distribution of the underlying field looks like.
    """
    flat = field.reshape(-1)
    order = np.argsort(flat, kind="stable")
    ranks = np.empty_like(order, dtype=np.float32)
    ranks[order] = np.linspace(0.0, 1.0, flat.size, dtype=np.float32)
    return ranks.reshape(field.shape)


def _low_frequency_noise(
    shape: tuple[int, int], rng: np.random.Generator, sigma: float
) -> np.ndarray:
    noise = rng.random(shape, dtype=np.float32)
    return cv2.GaussianBlur(noise, (0, 0), sigma)


def build_reveal_map(
    kind: str,
    analysis: ArtworkAnalysis,
    *,
    rng: np.random.Generator,
    shape: tuple[int, int] | None = None,
) -> np.ndarray:
    """Return a float32 0..1 reveal-order map."""
    height, width = shape or analysis.rgb.shape[:2]
    scale_map = _resize(analysis.scale_map, width, height)
    detail_map = _resize(analysis.detail_map, width, height)
    luminance = _resize(analysis.luminance, width, height)
    labels = _resize(analysis.palette_labels.astype(np.float32), width, height, nearest=True)
    saliency = _resize(analysis.saliency, width, height)

    if kind == "dissolve":
        field = _low_frequency_noise((height, width), rng, max(2.0, min(height, width) / 90.0))
    elif kind == "tonal":
        # Shadows are laid in before lights, the way a painter blocks in values.
        field = luminance / 255.0 + _low_frequency_noise((height, width), rng, 6.0) * 0.35
    elif kind == "detail":
        field = (
            detail_map * 0.75
            + (1.0 - saliency) * 0.15
            + _low_frequency_noise((height, width), rng, 5.0) * 0.2
        )
    elif kind == "region":
        field = _region_field(labels, analysis, rng, height, width)
    elif kind == "radial":
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        centre = _saliency_centroid(saliency)
        field = np.sqrt((yy - centre[0]) ** 2 + (xx - centre[1]) ** 2)
        field += _low_frequency_noise((height, width), rng, 8.0) * field.max() * 0.15
    else:  # organic
        angle = float(rng.uniform(0, np.pi * 2))
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        # A directional component keeps the reveal moving, but it is a minority
        # term: structure decides most of the ordering.
        sweep = (xx * np.cos(angle) + yy * np.sin(angle)) / float(max(height, width))
        field = (
            scale_map * 0.55
            + sweep * 0.10
            + _low_frequency_noise((height, width), rng, max(3.0, min(height, width) / 60.0)) * 0.60
        )

    return _rank_normalise(field.astype(np.float32))


def _region_field(
    labels: np.ndarray, analysis: ArtworkAnalysis, rng: np.random.Generator, height: int, width: int
) -> np.ndarray:
    """Reveal colour group by colour group, largest first.

    Within a group a shallow directional sweep makes each block fill in like a
    brush pass rather than appearing all at once.
    """
    field = np.zeros((height, width), dtype=np.float32)
    group_count = int(labels.max()) + 1
    angle = float(rng.uniform(0, np.pi * 2))
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    sweep = xx * np.cos(angle) + yy * np.sin(angle)
    sweep = (sweep - sweep.min()) / (float(sweep.max() - sweep.min()) or 1.0)

    for group in range(group_count):
        selection = labels == group
        if not selection.any():
            continue
        base = group / float(max(1, group_count))
        field[selection] = base + sweep[selection] * (0.85 / max(1, group_count))
    field += _low_frequency_noise((height, width), rng, 4.0) * 0.05
    return field


def _saliency_centroid(saliency: np.ndarray) -> tuple[float, float]:
    total = float(saliency.sum()) or 1.0
    yy, xx = np.mgrid[0 : saliency.shape[0], 0 : saliency.shape[1]].astype(np.float32)
    return float((yy * saliency).sum() / total), float((xx * saliency).sum() / total)


def _resize(field: np.ndarray, width: int, height: int, *, nearest: bool = False) -> np.ndarray:
    if field.shape[0] == height and field.shape[1] == width:
        return field
    return cv2.resize(
        field,
        (width, height),
        interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR,
    )


def apply_reveal(
    previous: np.ndarray,
    target: np.ndarray,
    reveal_map: np.ndarray,
    progress: float,
    *,
    softness: float = 0.06,
) -> np.ndarray:
    """Blend ``previous`` into ``target`` following the reveal order.

    ``softness`` gives the moving front a gradient instead of a hard edge, which
    is what makes the transition read as paint arriving rather than as a mask.
    """
    progress = float(np.clip(progress, 0.0, 1.0))
    if progress <= 0.0:
        return previous
    if progress >= 1.0:
        return target

    span = max(1e-3, softness)
    alpha = np.clip((progress - reveal_map) / span + 0.5, 0.0, 1.0)[:, :, None]
    blended = target.astype(np.float32) * alpha + previous.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)
