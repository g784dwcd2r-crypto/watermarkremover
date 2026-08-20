"""Inpainting backends.

Importing this package registers every backend that can be imported without
optional heavy dependencies. Model-backed adapters register too, but report
themselves unavailable until an operator configures a local checkpoint.
"""

from .base import (  # noqa: F401
    InpaintBackend,
    InpaintRequest,
    available_backends,
    get_backend,
    register_backend,
)
from . import opencv_backend  # noqa: F401
from . import patchmatch  # noqa: F401
from . import lama_backend  # noqa: F401
from . import diffusion_backend  # noqa: F401

__all__ = [
    "InpaintBackend",
    "InpaintRequest",
    "available_backends",
    "get_backend",
    "register_backend",
]
