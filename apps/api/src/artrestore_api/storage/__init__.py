"""Object storage backends and the process-wide accessor."""

from __future__ import annotations

from ..config import get_settings
from .base import (  # noqa: F401
    ObjectNotFoundError,
    SignedUpload,
    Storage,
    StorageError,
    build_object_key,
)
from .local import LocalStorage  # noqa: F401
from .s3 import S3Storage  # noqa: F401

_storage: Storage | None = None


def build_storage(settings=None) -> Storage:
    settings = settings or get_settings()
    if settings.storage_backend == "local":
        return LocalStorage(
            settings.local_storage_dir,
            secret=settings.secret_key,
            public_base_url=settings.public_api_url,
        )
    return S3Storage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
        use_path_style=settings.s3_use_path_style,
    )


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Override the process storage (used by tests)."""
    global _storage
    _storage = storage
