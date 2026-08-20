"""Optional diffusion inpainting adapter for difficult textures.

Like the LaMa adapter this ships as an *adapter only*: it drives a locally
deployed diffusion inpainting pipeline when ``ARS_DIFFUSION_MODEL_PATH`` points
at one. Nothing is downloaded automatically and no image ever leaves the
deployment. Runs are seeded so a given project reproduces its own result.
"""

from __future__ import annotations

import os
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

from ..errors import InpaintBackendUnavailableError
from .base import InpaintBackend, InpaintRequest, register_backend

MAX_SIDE = 1024
SIZE_MULTIPLE = 8


def _model_path(settings: dict | None) -> str | None:
    settings = settings or {}
    path = settings.get("diffusion_model_path") or os.environ.get("ARS_DIFFUSION_MODEL_PATH") or ""
    return path or None


@lru_cache(maxsize=1)
def _load_pipeline(path: str):  # pragma: no cover - requires local weights
    import torch
    from diffusers import StableDiffusionInpaintPipeline

    pipeline = StableDiffusionInpaintPipeline.from_pretrained(
        path, torch_dtype=torch.float32, local_files_only=True, safety_checker=None
    )
    pipeline.set_progress_bar_config(disable=True)
    return pipeline


@register_backend
class DiffusionBackend(InpaintBackend):
    name = "diffusion"
    description = "Locally deployed diffusion inpainting adapter for difficult textures."

    @classmethod
    def is_available(cls, settings: dict | None = None) -> bool:
        path = _model_path(settings)
        if not path or not os.path.isdir(path):
            return False
        try:
            import diffusers  # noqa: F401
            import torch  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def run(self, request: InpaintRequest) -> np.ndarray:  # pragma: no cover - optional path
        path = _model_path(request.options.get("settings"))
        if not path or not os.path.isdir(path):
            raise InpaintBackendUnavailableError(
                "No local diffusion inpainting model is configured "
                "(set ARS_DIFFUSION_MODEL_PATH).",
            )
        import torch

        request.check_cancelled()
        request.emit(0.1, "Preparing diffusion inpainting")

        rgb = request.rgb
        mask = (request.mask > 0).astype(np.uint8) * 255
        height, width = rgb.shape[:2]
        scale = min(1.0, MAX_SIDE / float(max(height, width)))
        work_size = (
            int(round(width * scale)) // SIZE_MULTIPLE * SIZE_MULTIPLE or SIZE_MULTIPLE,
            int(round(height * scale)) // SIZE_MULTIPLE * SIZE_MULTIPLE or SIZE_MULTIPLE,
        )
        small_rgb = cv2.resize(rgb, work_size, interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(mask, work_size, interpolation=cv2.INTER_NEAREST)

        pipeline = _load_pipeline(path)
        generator = torch.Generator(device="cpu").manual_seed(int(request.seed))
        prompt = str(
            request.options.get(
                "prompt",
                "seamless continuation of the surrounding surface, matching texture and lighting",
            )
        )
        request.emit(0.4, "Running diffusion inpainting")
        output = pipeline(
            prompt=prompt,
            image=Image.fromarray(small_rgb),
            mask_image=Image.fromarray(small_mask),
            num_inference_steps=int(request.options.get("steps", 30)),
            guidance_scale=float(request.options.get("guidance_scale", 7.0)),
            generator=generator,
        )
        generated = np.array(output.images[0].convert("RGB"), dtype=np.uint8)
        generated = cv2.resize(generated, (width, height), interpolation=cv2.INTER_CUBIC)

        result = rgb.copy()
        selection = mask > 0
        result[selection] = generated[selection]
        request.emit(1.0, "Diffusion inpainting complete")
        return result
