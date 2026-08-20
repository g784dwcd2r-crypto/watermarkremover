"""Inpainting backend contract.

Every backend takes RGB pixels plus a binary mask and returns RGB pixels of the
same shape. Backends are registered by name so the pipeline (and the deployment
configuration) can select one without importing optional heavy dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..errors import InpaintBackendUnavailableError

ProgressCallback = Callable[[float, str], None]


@dataclass(slots=True)
class InpaintRequest:
    """Everything a backend needs for one fill."""

    rgb: np.ndarray  # uint8 HxWx3
    mask: np.ndarray  # uint8 HxW, 255 = reconstruct
    radius: int = 5
    seed: int = 0
    options: dict = field(default_factory=dict)
    progress: ProgressCallback | None = None
    should_cancel: Callable[[], bool] | None = None

    def emit(self, fraction: float, message: str) -> None:
        if self.progress is not None:
            self.progress(max(0.0, min(1.0, float(fraction))), message)

    def check_cancelled(self) -> None:
        from ..errors import JobCancelledError

        if self.should_cancel is not None and self.should_cancel():
            raise JobCancelledError("The job was cancelled.")


class InpaintBackend(ABC):
    """Base class for all inpainting implementations."""

    name: str = "base"
    #: Human-readable note surfaced in job results so users know what ran.
    description: str = ""

    @classmethod
    def is_available(cls, settings: dict | None = None) -> bool:
        return True

    @abstractmethod
    def run(self, request: InpaintRequest) -> np.ndarray:
        """Return reconstructed RGB pixels of the same shape as ``request.rgb``."""


_REGISTRY: dict[str, type[InpaintBackend]] = {}


def register_backend(backend_cls: type[InpaintBackend]) -> type[InpaintBackend]:
    _REGISTRY[backend_cls.name] = backend_cls
    return backend_cls


def available_backends(settings: dict | None = None) -> list[str]:
    return sorted(name for name, cls in _REGISTRY.items() if cls.is_available(settings))


def get_backend(name: str, settings: dict | None = None) -> InpaintBackend:
    backend_cls = _REGISTRY.get(name)
    if backend_cls is None:
        raise InpaintBackendUnavailableError(
            f"Unknown inpainting backend '{name}'.",
            details={"available": available_backends(settings)},
        )
    if not backend_cls.is_available(settings):
        raise InpaintBackendUnavailableError(
            f"The '{name}' backend is not configured on this deployment.",
            details={"available": available_backends(settings)},
        )
    return backend_cls()
