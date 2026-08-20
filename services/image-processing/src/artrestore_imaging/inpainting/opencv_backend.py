"""Classical OpenCV inpainting backends.

These are the always-available modes. They need no model weights, run in
milliseconds on small marks, and are the right tool for date stamps and thin
overlays on smooth backgrounds.
"""

from __future__ import annotations

import cv2
import numpy as np

from .base import InpaintBackend, InpaintRequest, register_backend


def _prepare(request: InpaintRequest) -> tuple[np.ndarray, np.ndarray]:
    bgr = cv2.cvtColor(request.rgb, cv2.COLOR_RGB2BGR)
    mask = (request.mask > 0).astype(np.uint8) * 255
    return bgr, mask


@register_backend
class TeleaBackend(InpaintBackend):
    name = "opencv_telea"
    description = "OpenCV Fast Marching (Telea) inpainting."

    def run(self, request: InpaintRequest) -> np.ndarray:
        request.check_cancelled()
        request.emit(0.2, "Filling with fast-marching inpainting")
        bgr, mask = _prepare(request)
        result = cv2.inpaint(bgr, mask, request.radius, cv2.INPAINT_TELEA)
        request.emit(1.0, "Fill complete")
        return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)


@register_backend
class NavierStokesBackend(InpaintBackend):
    name = "opencv_ns"
    description = "OpenCV Navier-Stokes inpainting; better at continuing smooth gradients."

    def run(self, request: InpaintRequest) -> np.ndarray:
        request.check_cancelled()
        request.emit(0.2, "Filling with Navier-Stokes inpainting")
        bgr, mask = _prepare(request)
        result = cv2.inpaint(bgr, mask, request.radius, cv2.INPAINT_NS)
        request.emit(1.0, "Fill complete")
        return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)


@register_backend
class BlendedClassicalBackend(InpaintBackend):
    """Telea and Navier-Stokes averaged, weighted by local structure.

    Telea reconstructs edges more crisply, Navier-Stokes handles smooth
    gradients. Blending them by local edge energy avoids the characteristic
    smear each one produces on its weak case.
    """

    name = "opencv_blend"
    description = "Structure-weighted blend of Telea and Navier-Stokes."

    def run(self, request: InpaintRequest) -> np.ndarray:
        request.check_cancelled()
        bgr, mask = _prepare(request)

        request.emit(0.2, "Running fast-marching pass")
        telea = cv2.inpaint(bgr, mask, request.radius, cv2.INPAINT_TELEA)
        request.check_cancelled()
        request.emit(0.6, "Running Navier-Stokes pass")
        navier = cv2.inpaint(bgr, mask, request.radius, cv2.INPAINT_NS)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Sobel(gray, cv2.CV_32F, 1, 1, ksize=3)
        energy = cv2.GaussianBlur(np.abs(edges), (0, 0), 3.0)
        peak = float(energy.max()) or 1.0
        weight = np.clip(energy / peak, 0.0, 1.0)[:, :, None]

        request.emit(0.9, "Blending structure and gradient passes")
        blended = telea.astype(np.float32) * weight + navier.astype(np.float32) * (1.0 - weight)
        request.emit(1.0, "Fill complete")
        return cv2.cvtColor(np.clip(blended, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
