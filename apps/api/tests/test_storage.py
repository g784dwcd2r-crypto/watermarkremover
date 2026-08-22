"""Object storage: key scoping, signed URLs and path safety."""

from __future__ import annotations

import time

import pytest
from artrestore_api.storage import ObjectNotFoundError, StorageError, build_object_key
from artrestore_api.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(
        str(tmp_path / "objects"), secret="unit-test-secret", public_base_url="http://api.test"
    )


def test_put_get_size_and_delete(storage):
    key = "users/u1/projects/p1/source/file.png"
    assert storage.put_bytes(key, b"hello", "image/png") == 5
    assert storage.get_bytes(key) == b"hello"
    assert storage.size(key) == 5
    assert storage.exists(key) is True
    assert storage.content_type(key) == "image/png"

    storage.delete(key)
    assert storage.exists(key) is False
    with pytest.raises(ObjectNotFoundError):
        storage.get_bytes(key)


def test_delete_prefix_removes_a_whole_project(storage):
    for index in range(3):
        storage.put_bytes(f"users/u1/projects/p1/source/{index}.png", b"x", "image/png")
    storage.put_bytes("users/u1/projects/p2/source/keep.png", b"x", "image/png")

    assert storage.delete_prefix("users/u1/projects/p1/") == 3
    assert storage.exists("users/u1/projects/p2/source/keep.png") is True


def test_delete_prefix_on_missing_prefix_is_zero(storage):
    assert storage.delete_prefix("users/nobody/") == 0


@pytest.mark.parametrize(
    "key",
    ["../escape.png", "/absolute.png", "users/../../etc/passwd", "a/../../b"],
)
def test_path_traversal_is_refused(storage, key):
    with pytest.raises(StorageError):
        storage.put_bytes(key, b"x", "image/png")


def test_signed_download_url_verifies(storage):
    key = "users/u1/projects/p1/export/out.png"
    storage.put_bytes(key, b"data", "image/png")
    url = storage.signed_download_url(key, expires_in=60)
    assert url.startswith("http://api.test/v1/storage/")
    assert "signature=" in url and "expires=" in url

    expires = int(url.split("expires=")[1].split("&")[0])
    signature = url.split("signature=")[1].split("&")[0]
    assert storage.verify_signature(key, expires, signature, "GET") is True
    # The signature is scoped to the key and to the method.
    assert storage.verify_signature("users/u1/other", expires, signature, "GET") is False
    assert storage.verify_signature(key, expires, signature, "PUT") is False


def test_expired_signature_is_rejected(storage):
    key = "users/u1/projects/p1/export/out.png"
    expired = int(time.time()) - 10
    signature = storage._signature(key, expired, "GET")
    assert storage.verify_signature(key, expired, signature, "GET") is False


def test_signed_upload_descriptor(storage):
    upload = storage.signed_upload(
        "users/u1/projects/p1/source/in.png", content_type="image/png", expires_in=120, max_bytes=99
    )
    assert upload.method == "PUT"
    assert upload.headers["Content-Type"] == "image/png"
    assert upload.max_bytes == 99
    assert upload.expires_in == 120


def test_object_keys_are_scoped_per_user_and_project():
    key = build_object_key("user-1", "project-1", "source", "My Photo (final).png")
    assert key.startswith("users/user-1/projects/project-1/source/")
    assert " " not in key and "(" not in key


def test_object_key_versioning():
    key = build_object_key("u", "p", "mask", "mask.png", version=3)
    assert "/mask/v3-mask.png" in key


def test_storage_gateway_rejects_a_forged_signature(api, demo_images):
    """The development gateway enforces the signature exactly like S3 does."""
    project = api.create_project()
    asset_id, _ = api.upload_image(project["id"], demo_images["stamped_png"])
    asset = api.get(f"/v1/projects/{project['id']}/assets/{asset_id}").json()

    url = asset["download_url"].replace("http://testserver", "")
    tampered = url.split("signature=")[0] + "signature=deadbeef"
    response = api.client.get(tampered)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_signature"


def test_storage_gateway_serves_a_valid_signature(api, demo_images):
    project = api.create_project()
    asset_id, _ = api.upload_image(project["id"], demo_images["stamped_png"])
    asset = api.get(f"/v1/projects/{project['id']}/assets/{asset_id}").json()
    response = api.client.get(asset["download_url"].replace("http://testserver", ""))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
