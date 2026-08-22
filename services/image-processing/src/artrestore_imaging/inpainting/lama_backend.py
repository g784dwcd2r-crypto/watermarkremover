"""LaMa (large-mask) inpainting adapter.

The model itself is **not** bundled: no weights are downloaded at build or run
time, and nothing is sent to a third-party service. An operator deploys a LaMa
checkpoint locally and points ``ARS_LAMA_MODEL_PATH`` at it. Both a TorchScript
export (``.pt``/``.pth``) and an ONNX export (``.onnx``) are supported; when
neither is configured the backend reports itself unavailable and the pipeline
falls back to the exemplar-based filler.
"""

from __future__ import annotations

import os
from functools import lru_cache

import cv2
import numpy as np

from ..errors import InpaintBackendUnavailableError
from .base import InpaintBackend, InpaintRequest, register_backend

#: LaMa's fully-convolutional architecture requires side lengths divisible by 8.
SIZE_MULTIPLE = 8
#: Inference resolution ceiling; larger images are processed as a padded crop
#: around the mask so quality does not depend on total canvas size.
MAX_INFERENCE_SIDE = 1024


def _model_path(settings: dict | None) -> str | None:
    settings = settings or {}
    path = settings.get("lama_model_path") or os.environ.get("ARS_LAMA_MODEL_PATH") or ""
    return path or None


@lru_cache(maxsize=2)
def _load_torchscript(path: str):  # pragma: no cover - requires a local checkpoint
    import torch

    model = torch.jit.load(path, map_location="cpu")
    model.eval()
    return model


@lru_cache(maxsize=2)
def _load_onnx(path: str):  # pragma: no cover - requires a local checkpoint
    import onnxruntime

    return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])


@register_backend
class LamaBackend(InpaintBackend):
    name = "lama"
    description = "Locally deployed LaMa large-mask inpainting model."

    @classmethod
    def is_available(cls, settings: dict | None = None) -> bool:
        path = _model_path(settings)
        if not path or not os.path.exists(path):
            return False
        if path.endswith(".onnx"):
            try:
                import onnxruntime  # noqa: F401
            except Exception:
                return False
            return True
        try:
            import torch  # noqa: F401
        except Exception:
            return False
        return True

    def run(self, request: InpaintRequest) -> np.ndarray:
        path = _model_path(request.options.get("settings"))
        if not path or not os.path.exists(path):
            raise InpaintBackendUnavailableError(
                "No local LaMa checkpoint is configured (set ARS_LAMA_MODEL_PATH).",
            )

        request.check_cancelled()
        request.emit(0.1, "Preparing tiles for the inpainting model")

        rgb = request.rgb
        mask = (request.mask > 0).astype(np.uint8) * 255
        crop_box = self._inference_box(mask, rgb.shape[:2])
        y0, y1, x0, x1 = crop_box
        rgb_crop = rgb[y0:y1, x0:x1]
        mask_crop = mask[y0:y1, x0:x1]

        padded_rgb, padded_mask, pad = self._pad(rgb_crop, mask_crop)
        request.emit(0.35, "Running the inpainting model")
        predicted = self._infer(path, padded_rgb, padded_mask)
        request.check_cancelled()

        ph, pw = padded_rgb.shape[:2]
        predicted = predicted[: ph - pad[0], : pw - pad[1]]
        predicted = cv2.resize(
            predicted, (rgb_crop.shape[1], rgb_crop.shape[0]), interpolation=cv2.INTER_CUBIC
        )

        result = rgb.copy()
        region = result[y0:y1, x0:x1]
        selection = mask_crop > 0
        region[selection] = predicted[selection]
        result[y0:y1, x0:x1] = region
        request.emit(1.0, "Model inference complete")
        return result

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _inference_box(mask: np.ndarray, shape: tuple[int, int]) -> tuple[int, int, int, int]:
        height, width = shape
        ys, xs = np.nonzero(mask)
        if ys.size == 0:
            return 0, height, 0, width
        margin = 96
        y0 = max(0, int(ys.min()) - margin)
        y1 = min(height, int(ys.max()) + margin)
        x0 = max(0, int(xs.min()) - margin)
        x1 = min(width, int(xs.max()) + margin)
        return y0, y1, x0, x1

    @staticmethod
    def _pad(rgb: np.ndarray, mask: np.ndarray):
        height, width = rgb.shape[:2]
        scale = min(1.0, MAX_INFERENCE_SIDE / float(max(height, width)))
        if scale < 1.0:
            new_size = (max(8, int(width * scale)), max(8, int(height * scale)))
            rgb = cv2.resize(rgb, new_size, interpolation=cv2.INTER_AREA)
            mask = cv2.resize(mask, new_size, interpolation=cv2.INTER_NEAREST)
            height, width = rgb.shape[:2]

        pad_h = (SIZE_MULTIPLE - height % SIZE_MULTIPLE) % SIZE_MULTIPLE
        pad_w = (SIZE_MULTIPLE - width % SIZE_MULTIPLE) % SIZE_MULTIPLE
        if pad_h or pad_w:
            rgb = cv2.copyMakeBorder(rgb, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT_101)
            mask = cv2.copyMakeBorder(mask, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=0)
        return rgb, mask, (pad_h, pad_w)

    @staticmethod
    def _infer(path: str, rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:  # pragma: no cover
        image = rgb.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        binary = (mask.astype(np.float32) > 0).astype(np.float32)[None, None]

        if path.endswith(".onnx"):
            session = _load_onnx(path)
            names = [i.name for i in session.get_inputs()]
            outputs = session.run(None, {names[0]: image, names[1]: binary})
            predicted = outputs[0]
        else:
            import torch

            model = _load_torchscript(path)
            with torch.no_grad():
                tensor = model(torch.from_numpy(image), torch.from_numpy(binary))
            predicted = tensor.detach().cpu().numpy()

        array = np.asarray(predicted)[0].transpose(1, 2, 0)
        if array.max() <= 1.01:
            array = array * 255.0
        return np.clip(array, 0, 255).astype(np.uint8)
