"""Filesystem storage for local development and tests.

Signed URLs are HMAC-signed and served by the API's storage router, so the
same short-expiry, no-listing behaviour as S3 is exercised in development.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time
from urllib.parse import quote, urlencode

from ..security.tokens import constant_time_equals, sign_payload
from .base import ObjectNotFoundError, SignedUpload, Storage, StorageError


class LocalStorage(Storage):
    name = "local"

    def __init__(self, root: str, *, secret: str, public_base_url: str) -> None:
        self.root = pathlib.Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._secret = secret
        self._public_base_url = public_base_url.rstrip("/")

    # -- path safety --------------------------------------------------------

    def _path(self, key: str) -> pathlib.Path:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise StorageError(f"Refusing unsafe storage key: {key!r}")
        candidate = (self.root / key).resolve()
        if not str(candidate).startswith(str(self.root)):
            raise StorageError("Storage key escapes the storage root.")
        return candidate

    # -- object operations --------------------------------------------------

    def put_bytes(self, key: str, data: bytes, content_type: str) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        (path.parent / f".{path.name}.type").write_text(content_type, encoding="utf-8")
        return len(data)

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def content_type(self, key: str) -> str:
        path = self._path(key)
        marker = path.parent / f".{path.name}.type"
        if marker.is_file():
            return marker.read_text(encoding="utf-8").strip()
        return "application/octet-stream"

    def delete(self, key: str) -> None:
        path = self._path(key)
        marker = path.parent / f".{path.name}.type"
        for target in (path, marker):
            try:
                target.unlink()
            except FileNotFoundError:
                pass

    def delete_prefix(self, prefix: str) -> int:
        path = self._path(prefix)
        if not path.exists():
            return 0
        count = sum(1 for item in path.rglob("*") if item.is_file() and not item.name.startswith("."))
        shutil.rmtree(path, ignore_errors=True)
        return count

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.stat().st_size

    # -- signed URLs --------------------------------------------------------

    def _signature(self, key: str, expires: int, method: str) -> str:
        return sign_payload(self._secret, f"{method}:{key}:{expires}")

    def signed_download_url(
        self, key: str, *, expires_in: int = 300, filename: str | None = None
    ) -> str:
        expires = int(time.time()) + expires_in
        params = {"expires": expires, "signature": self._signature(key, expires, "GET")}
        if filename:
            params["filename"] = filename
        return f"{self._public_base_url}/v1/storage/{quote(key)}?{urlencode(params)}"

    def signed_upload(
        self, key: str, *, content_type: str, expires_in: int = 300, max_bytes: int = 0
    ) -> SignedUpload:
        expires = int(time.time()) + expires_in
        params = {"expires": expires, "signature": self._signature(key, expires, "PUT")}
        return SignedUpload(
            url=f"{self._public_base_url}/v1/storage/{quote(key)}?{urlencode(params)}",
            method="PUT",
            headers={"Content-Type": content_type},
            storage_key=key,
            expires_in=expires_in,
            max_bytes=max_bytes,
        )

    def verify_signature(self, key: str, expires: int, signature: str, method: str) -> bool:
        if expires < int(time.time()):
            return False
        return constant_time_equals(self._signature(key, expires, method), signature)
