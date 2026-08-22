"""Inpainting backends.

Importing this package registers every backend that can be imported without
optional heavy dependencies. Model-backed adapters register too, but report
themselves unavailable until an operator configures a local checkpoint.
"""

from . import (
    diffusion_backend,  # noqa: F401
    lama_backend,  # noqa: F401
    opencv_backend,  # noqa: F401
    patchmatch,  # noqa: F401
)
from .base import (
    InpaintBackend,
    InpaintRequest,
    available_backends,
    get_backend,
    register_backend,
)

__all__ = [
    "InpaintBackend",
    "InpaintRequest",
    "available_backends",
    "get_backend",
    "register_backend",
]
