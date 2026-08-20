"""S3-compatible object storage (AWS S3, MinIO, R2, Spaces...).

Uploads and downloads are presigned so image bytes never pass through the API
process. URLs are minted with a short TTL and are never written to logs.
"""

from __future__ import annotations

import functools
from typing import Any

from .base import ObjectNotFoundError, SignedUpload, Storage, StorageError


class S3Storage(Storage):
    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        use_path_style: bool = True,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._use_path_style = use_path_style

    @functools.cached_property
    def client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url or None,
            aws_access_key_id=self._access_key_id or None,
            aws_secret_access_key=self._secret_access_key or None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if self._use_path_style else "auto"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    # -- object operations --------------------------------------------------

    def put_bytes(self, key: str, data: bytes, content_type: str) -> int:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return len(data)

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - botocore raises dynamic classes
            if "NoSuchKey" in str(exc) or "404" in str(exc):
                raise ObjectNotFoundError(key) from exc
            raise StorageError(str(exc)) from exc
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        paginator = self.client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": item["Key"]} for item in contents]},
            )
            deleted += len(contents)
        return deleted

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:  # noqa: BLE001
            return False
        return True

    def size(self, key: str) -> int:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise ObjectNotFoundError(key) from exc
        return int(response["ContentLength"])

    # -- signed URLs --------------------------------------------------------

    def signed_download_url(
        self, key: str, *, expires_in: int = 300, filename: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in
        )

    def signed_upload(
        self, key: str, *, content_type: str, expires_in: int = 300, max_bytes: int = 0
    ) -> SignedUpload:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ServerSideEncryption": "AES256",
            },
            ExpiresIn=expires_in,
        )
        return SignedUpload(
            url=url,
            method="PUT",
            headers={"Content-Type": content_type, "x-amz-server-side-encryption": "AES256"},
            storage_key=key,
            expires_in=expires_in,
            max_bytes=max_bytes,
        )

    def health(self) -> dict:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:  # noqa: BLE001
            return {"backend": self.name, "ok": False, "error": type(exc).__name__}
        return {"backend": self.name, "ok": True, "bucket": self.bucket}

    def ensure_bucket(self) -> None:
        """Create the bucket when it is missing (development convenience)."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001
            kwargs: dict[str, Any] = {"Bucket": self.bucket}
            if self.region and self.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.client.create_bucket(**kwargs)
