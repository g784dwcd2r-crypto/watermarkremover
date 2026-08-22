"""Exemplar-based (PatchMatch-style) texture synthesis fill.

An isophote-driven exemplar filler in the Criminisi tradition: the hole is
eroded patch by patch, always starting where the surrounding structure is
strongest, and each patch is copied from the best-matching known neighbourhood.
Unlike diffusion inpainting it reproduces *texture* (canvas weave, foliage,
fabric, paper grain) instead of smearing it, which makes it the dependable
fallback when no neural weights are deployed.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import InpaintBackend, InpaintRequest, register_backend

#: Above this many masked pixels the fill runs on a downscaled copy and the
#: result is upsampled, keeping worst-case runtime bounded.
DOWNSCALE_PIXEL_BUDGET = 120_000


@register_backend
class PatchMatchBackend(InpaintBackend):
    name = "patchmatch"
    description = (
        "Exemplar-based texture synthesis; reproduces repeating texture rather than blurring it."
    )

    def run(self, request: InpaintRequest) -> np.ndarray:
        rgb = request.rgb
        mask = (request.mask > 0).astype(np.uint8)
        if not mask.any():
            return rgb.copy()

        masked_pixels = int(mask.sum())
        scale = 1.0
        if masked_pixels > DOWNSCALE_PIXEL_BUDGET:
            scale = float(np.sqrt(DOWNSCALE_PIXEL_BUDGET / masked_pixels))

        if scale < 1.0:
            height, width = rgb.shape[:2]
            small_size = (max(8, int(width * scale)), max(8, int(height * scale)))
            small_rgb = cv2.resize(rgb, small_size, interpolation=cv2.INTER_AREA)
            small_mask = cv2.resize(mask * 255, small_size, interpolation=cv2.INTER_NEAREST)
            filled_small = self._fill(small_rgb, (small_mask > 0).astype(np.uint8), request)
            upscaled = cv2.resize(filled_small, (width, height), interpolation=cv2.INTER_CUBIC)
            result = rgb.copy()
            result[mask > 0] = upscaled[mask > 0]
            return result

        return self._fill(rgb, mask, request)

    # -- core ---------------------------------------------------------------

    def _fill(self, rgb: np.ndarray, mask: np.ndarray, request: InpaintRequest) -> np.ndarray:
        options = request.options or {}
        patch_radius = int(options.get("patch_radius", 4))
        search_radius = int(options.get("search_radius", 48))
        patch_size = patch_radius * 2 + 1

        working = rgb.astype(np.float32).copy()
        unknown = mask.astype(bool).copy()
        confidence = (~unknown).astype(np.float32)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0

        total_unknown = float(unknown.sum()) or 1.0
        height, width = unknown.shape
        rng = np.random.default_rng(request.seed)
        max_iterations = int(total_unknown / max(1, patch_size)) + 64

        for iteration in range(max_iterations):
            if not unknown.any():
                break
            if iteration % 16 == 0:
                request.check_cancelled()
                remaining = float(unknown.sum())
                request.emit(
                    1.0 - remaining / total_unknown,
                    f"Synthesising texture ({int(total_unknown - remaining)}/{int(total_unknown)} px)",
                )

            target = self._select_target(unknown, confidence, gray, patch_radius, rng)
            if target is None:
                break
            ty, tx = target

            y0, y1 = max(0, ty - patch_radius), min(height, ty + patch_radius + 1)
            x0, x1 = max(0, tx - patch_radius), min(width, tx + patch_radius + 1)
            template = working[y0:y1, x0:x1]
            template_known = (~unknown[y0:y1, x0:x1]).astype(np.uint8) * 255
            if template_known.sum() == 0:
                # Nothing to match against yet; seed with a local mean.
                working[y0:y1, x0:x1] = self._local_mean(working, unknown, ty, tx, search_radius)
                unknown[y0:y1, x0:x1] = False
                confidence[y0:y1, x0:x1] = 0.05
                continue

            source = self._best_source(
                working, unknown, template, template_known, (ty, tx), search_radius, patch_radius
            )
            if source is None:
                working[y0:y1, x0:x1] = self._local_mean(working, unknown, ty, tx, search_radius)
                unknown[y0:y1, x0:x1] = False
                continue

            sy, sx = source
            patch = working[sy : sy + (y1 - y0), sx : sx + (x1 - x0)]
            if patch.shape != template.shape:
                unknown[y0:y1, x0:x1] = False
                continue

            hole = unknown[y0:y1, x0:x1]
            filled_confidence = (
                float(confidence[y0:y1, x0:x1][~hole].mean()) if (~hole).any() else 0.1
            )
            working[y0:y1, x0:x1][hole] = patch[hole]
            confidence[y0:y1, x0:x1][hole] = filled_confidence
            unknown[y0:y1, x0:x1] = False

        if unknown.any():
            # Anything the exemplar pass could not reach falls back to Telea so
            # the result never contains an unfilled hole.
            leftover = (unknown.astype(np.uint8)) * 255
            bgr = cv2.cvtColor(np.clip(working, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
            patched = cv2.inpaint(bgr, leftover, 3, cv2.INPAINT_TELEA)
            working = cv2.cvtColor(patched, cv2.COLOR_BGR2RGB).astype(np.float32)

        request.emit(1.0, "Texture synthesis complete")
        return np.clip(working, 0, 255).astype(np.uint8)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _select_target(
        unknown: np.ndarray,
        confidence: np.ndarray,
        gray: np.ndarray,
        patch_radius: int,
        rng: np.random.Generator,
    ) -> tuple[int, int] | None:
        """Pick the boundary pixel with the highest Criminisi priority."""
        unknown_u8 = unknown.astype(np.uint8)
        eroded = cv2.erode(unknown_u8, np.ones((3, 3), np.uint8))
        boundary = unknown_u8 - eroded
        ys, xs = np.nonzero(boundary)
        if ys.size == 0:
            ys, xs = np.nonzero(unknown_u8)
            if ys.size == 0:
                return None
            index = int(rng.integers(0, ys.size))
            return int(ys[index]), int(xs[index])

        kernel = np.ones((patch_radius * 2 + 1, patch_radius * 2 + 1), np.float32)
        kernel /= kernel.size
        confidence_term = cv2.filter2D(confidence, -1, kernel)

        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        ny = cv2.Sobel(unknown.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
        nx = cv2.Sobel(unknown.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
        # Isophote (gradient rotated 90 degrees) projected onto the fill front normal.
        data_term = np.abs(-gy * nx + gx * ny)
        data_term /= float(data_term.max()) or 1.0

        priority = confidence_term[ys, xs] * (0.05 + data_term[ys, xs])
        best = int(np.argmax(priority))
        return int(ys[best]), int(xs[best])

    @staticmethod
    def _best_source(
        working: np.ndarray,
        unknown: np.ndarray,
        template: np.ndarray,
        template_known: np.ndarray,
        target: tuple[int, int],
        search_radius: int,
        patch_radius: int,
    ) -> tuple[int, int] | None:
        height, width = unknown.shape
        ty, tx = target
        sy0 = max(0, ty - search_radius)
        sy1 = min(height, ty + search_radius + 1)
        sx0 = max(0, tx - search_radius)
        sx1 = min(width, tx + search_radius + 1)

        window = np.clip(working[sy0:sy1, sx0:sx1], 0, 255).astype(np.uint8)
        th, tw = template.shape[:2]
        if window.shape[0] <= th or window.shape[1] <= tw:
            return None

        template_u8 = np.clip(template, 0, 255).astype(np.uint8)
        mask3 = cv2.cvtColor(template_known, cv2.COLOR_GRAY2BGR)
        try:
            scores = cv2.matchTemplate(window, template_u8, cv2.TM_SQDIFF, mask=mask3)
        except cv2.error:
            return None

        # Reject source patches that themselves overlap the hole.
        hole_window = unknown[sy0:sy1, sx0:sx1].astype(np.float32)
        integral = cv2.boxFilter(
            hole_window, -1, (tw, th), normalize=False, borderType=cv2.BORDER_ISOLATED
        )
        valid_h, valid_w = scores.shape
        offset_y, offset_x = th // 2, tw // 2
        overlap = integral[offset_y : offset_y + valid_h, offset_x : offset_x + valid_w]
        scores = np.where(overlap > 0.5, np.inf, scores)
        scores = np.where(np.isfinite(scores), scores, np.inf)
        if not np.isfinite(scores).any():
            return None

        index = int(np.argmin(scores))
        by, bx = divmod(index, scores.shape[1])
        return sy0 + by, sx0 + bx

    @staticmethod
    def _local_mean(
        working: np.ndarray, unknown: np.ndarray, ty: int, tx: int, radius: int
    ) -> np.ndarray:
        height, width = unknown.shape
        y0, y1 = max(0, ty - radius), min(height, ty + radius + 1)
        x0, x1 = max(0, tx - radius), min(width, tx + radius + 1)
        window = working[y0:y1, x0:x1]
        known = ~unknown[y0:y1, x0:x1]
        if known.any():
            return window[known].mean(axis=0)
        return np.array([127.0, 127.0, 127.0], dtype=np.float32)
