"""Object storage contract.

Image bytes never live in the database. They live in object storage under keys
that embed the owning user and project, and they are only ever handed out
through short-lived signed URLs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class StorageError(Exception):
    """A storage operation failed."""


class ObjectNotFoundError(StorageError):
    """The requested key does not exist."""


@dataclass(slots=True)
class SignedUpload:
    """Everything a browser needs to upload directly to storage."""

    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    storage_key: str = ""
    expires_in: int = 300
    max_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "method": self.method,
            "headers": self.headers,
            "fields": self.fields,
            "storage_key": self.storage_key,
            "expires_in": self.expires_in,
            "max_bytes": self.max_bytes,
        }


class Storage(ABC):
    """Backend-agnostic object storage."""

    name: str = "base"

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str) -> int: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def signed_download_url(
        self, key: str, *, expires_in: int = 300, filename: str | None = None
    ) -> str: ...

    @abstractmethod
    def signed_upload(
        self, key: str, *, content_type: str, expires_in: int = 300, max_bytes: int = 0
    ) -> SignedUpload: ...

    def health(self) -> dict:
        return {"backend": self.name, "ok": True}


def build_object_key(
    user_id: str, project_id: str, asset_type: str, filename: str, *, version: int | None = None
) -> str:
    """Compose a storage key.

    The user id is the first path segment so a bucket policy can scope access
    per tenant, and so a deletion request maps to a single prefix.
    """
    safe = "".join(
        character if character.isalnum() or character in "._-" else "_" for character in filename
    )[:120]
    suffix = f"v{version}-" if version is not None else ""
    return f"users/{user_id}/projects/{project_id}/{asset_type}/{suffix}{safe}"
