"""Post-fill correction: seams, colour drift, structure and grain.

Inpainting alone rarely looks right. A fill can be locally plausible and still
read as a patch because its mean colour drifts from the surroundings, because it
is smoother than the film grain or canvas texture around it, or because a strong
edge stops at the mask boundary. These helpers address each of those, and they
are shared by every processing mode.
"""

from __future__ import annotations

import cv2
import numpy as np


def boundary_ring(binary: np.ndarray, width: int = 12) -> np.ndarray:
    """The band of known pixels immediately surrounding the mask."""
    size = max(1, int(width))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size * 2 + 1, size * 2 + 1))
    dilated = cv2.dilate((binary > 0).astype(np.uint8), kernel)
    ring = np.logical_and(dilated > 0, binary == 0)
    return ring.astype(np.uint8) * 255


def decompose(rgb: np.ndarray, *, sigma_space: float = 9.0, sigma_color: float = 40.0):
    """Split an image into an edge-preserving structure layer and a texture residual.

    Structure carries flat regions and hard edges; texture carries grain,
    brushwork and weave. Filling them separately keeps contours crisp without
    smearing texture, which is the basis of the Edge-Aware and Art modes.
    """
    structure = cv2.bilateralFilter(rgb, d=-1, sigmaColor=sigma_color, sigmaSpace=sigma_space)
    texture = rgb.astype(np.float32) - structure.astype(np.float32)
    return structure, texture


def recombine(structure: np.ndarray, texture: np.ndarray) -> np.ndarray:
    combined = structure.astype(np.float32) + texture
    return np.clip(combined, 0, 255).astype(np.uint8)


def feather_composite(original: np.ndarray, filled: np.ndarray, soft_mask: np.ndarray) -> np.ndarray:
    """Blend the reconstruction into the original using the feathered mask.

    Pixels outside the soft mask are returned bit-for-bit unchanged, so a
    cleanup never silently rewrites the rest of the image.
    """
    alpha = (soft_mask.astype(np.float32) / 255.0)[:, :, None]
    blended = filled.astype(np.float32) * alpha + original.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)


def match_local_colour(
    filled: np.ndarray,
    original: np.ndarray,
    binary: np.ndarray,
    *,
    ring_width: int = 14,
    max_shift: float = 12.0,
) -> np.ndarray:
    """Nudge the filled region so its colour statistics match the surrounding ring.

    The correction is clamped: it removes visible drift without inventing a
    different colour from the one the fill produced.
    """
    ring = boundary_ring(binary, ring_width) > 0
    hole = binary > 0
    if not ring.any() or not hole.any():
        return filled

    result = filled.astype(np.float32).copy()
    for channel in range(3):
        ring_values = original[:, :, channel][ring].astype(np.float32)
        hole_values = result[:, :, channel][hole]
        shift = float(ring_values.mean() - hole_values.mean())
        shift = float(np.clip(shift, -max_shift, max_shift))

        ring_std = float(ring_values.std()) or 1.0
        hole_std = float(hole_values.std()) or 1.0
        gain = float(np.clip(ring_std / hole_std, 0.85, 1.18))

        centred = (hole_values - hole_values.mean()) * gain + hole_values.mean() + shift
        result[:, :, channel][hole] = centred

    return np.clip(result, 0, 255).astype(np.uint8)


def estimate_grain(original: np.ndarray, ring: np.ndarray) -> float:
    """Estimate the high-frequency noise amplitude in the surrounding ring."""
    mask = ring > 0
    if not mask.any():
        return 0.0
    gray = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY).astype(np.float32)
    high_frequency = gray - cv2.GaussianBlur(gray, (0, 0), 1.2)
    return float(np.std(high_frequency[mask]))


def restore_grain(
    filled: np.ndarray,
    original: np.ndarray,
    binary: np.ndarray,
    *,
    strength: float = 1.0,
    seed: int = 0,
    ring_width: int = 14,
) -> np.ndarray:
    """Add grain to the fill so it matches the noise floor of its surroundings.

    Deterministic for a given ``seed`` so a project re-renders identically.
    """
    if strength <= 0:
        return filled
    ring = boundary_ring(binary, ring_width)
    sigma = estimate_grain(original, ring)
    if sigma < 0.6:
        return filled

    rng = np.random.default_rng(seed)
    hole = binary > 0
    noise = rng.normal(0.0, sigma * strength, size=filled.shape[:2]).astype(np.float32)
    # Grain in real captures is correlated at ~1px; a light blur avoids the
    # obviously synthetic look of per-pixel white noise.
    noise = cv2.GaussianBlur(noise, (0, 0), 0.6)
    noise *= sigma / (float(noise.std()) or 1.0)

    result = filled.astype(np.float32)
    for channel in range(3):
        layer = result[:, :, channel]
        layer[hole] = layer[hole] + noise[hole]
    return np.clip(result, 0, 255).astype(np.uint8)


def continue_edges(
    filled: np.ndarray,
    original: np.ndarray,
    binary: np.ndarray,
    *,
    strength: float = 0.6,
) -> np.ndarray:
    """Sharpen structure that crosses the mask boundary.

    Detects edges that enter the hole from the known side and re-asserts local
    contrast along their continuation, so borders, panel lines and object
    contours do not fade out mid-repair.
    """
    if strength <= 0:
        return filled
    hole = (binary > 0).astype(np.uint8)
    if not hole.any():
        return filled

    ring = boundary_ring(binary, 6) > 0
    gray_original = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray_original, 60, 150)
    entering = np.logical_and(edges > 0, ring)
    if not entering.any():
        return filled

    # Propagate the entering edge directions a short distance into the hole.
    seeds = (entering.astype(np.uint8)) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    propagated = cv2.dilate(seeds, kernel, iterations=3)
    zone = np.logical_and(propagated > 0, hole > 0)
    if not zone.any():
        return filled

    sharpened = cv2.addWeighted(
        filled.astype(np.float32),
        1.0 + strength,
        cv2.GaussianBlur(filled, (0, 0), 1.6).astype(np.float32),
        -strength,
        0.0,
    )
    weight = cv2.GaussianBlur(zone.astype(np.float32), (0, 0), 1.5)[:, :, None]
    blended = sharpened * weight + filled.astype(np.float32) * (1.0 - weight)
    return np.clip(blended, 0, 255).astype(np.uint8)


def preserve_alpha(
    alpha: np.ndarray | None, binary: np.ndarray, *, fill_transparent: bool = True
) -> np.ndarray | None:
    """Keep the alpha channel consistent with a cleanup.

    Cleaning an overlay that sat on transparent pixels should not turn them
    opaque, so alpha inside the mask is inpainted rather than overwritten.
    """
    if alpha is None:
        return None
    if not fill_transparent:
        return alpha
    hole = (binary > 0).astype(np.uint8) * 255
    if not hole.any():
        return alpha
    three = cv2.cvtColor(alpha, cv2.COLOR_GRAY2BGR)
    repaired = cv2.inpaint(three, hole, 3, cv2.INPAINT_TELEA)
    return cv2.cvtColor(repaired, cv2.COLOR_BGR2GRAY)
