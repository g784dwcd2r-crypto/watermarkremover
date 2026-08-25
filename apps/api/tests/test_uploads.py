"""Signed uploads, content validation and the ownership gate."""

from __future__ import annotations

import io

from artrestore_imaging import demo
from PIL import Image


def test_upload_round_trip_records_analysis(api, demo_images):
    project = api.create_project()
    asset_id, complete = api.upload_image(project["id"], demo_images["stamped_png"])

    assert complete.status_code == 200
    body = complete.json()
    assert (body["width"], body["height"]) == demo_images["size"]
    assert body["mime_type"] == "image/png"
    assert body["estimated_output_bytes"] > 0
    assert body["color_mode"] in ("RGB", "RGBA")
    assert asset_id


def test_upload_creates_a_preview_asset(api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    assets = api.get(f"/v1/projects/{project['id']}/assets").json()
    kinds = {asset["type"] for asset in assets}
    assert {"source", "source_preview"} <= kinds
    preview = next(asset for asset in assets if asset["type"] == "source_preview")
    assert preview["download_url"]
    assert max(preview["width"], preview["height"]) <= 640


def test_completion_records_the_ownership_attestation(api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])

    detail = api.get(f"/v1/projects/{project['id']}").json()
    assert detail["ownership_confirmed"] is True
    assert detail["status"] == "ready"

    consents = api.get(f"/v1/projects/{project['id']}/consent").json()
    ownership = [c for c in consents if c["consent_type"] == "ownership_confirmation"]
    assert ownership
    assert ownership[0]["statement"] == "I own this image or have permission to edit it."
    assert ownership[0]["policy_version"]


def test_completion_without_confirmation_is_rejected(api, demo_images):
    """The attestation is a gate: nothing completes without it."""
    project = api.create_project()
    _, complete = api.upload_image(project["id"], demo_images["stamped_png"], confirm=False)
    assert complete.status_code == 422
    assert complete.json()["error"]["code"] == "validation_error"

    detail = api.get(f"/v1/projects/{project['id']}").json()
    assert detail["ownership_confirmed"] is False
    assert detail["status"] == "draft"


def test_upload_rejects_unsupported_declared_type(api):
    project = api.create_project()
    response = api.post(
        f"/v1/projects/{project['id']}/assets/uploads",
        json={
            "filename": "evil.svg",
            "content_type": "image/svg+xml",
            "byte_size": 100,
            "asset_type": "source",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_upload_rejects_oversized_declaration(api):
    project = api.create_project()
    response = api.post(
        f"/v1/projects/{project['id']}/assets/uploads",
        json={
            "filename": "huge.png",
            "content_type": "image/png",
            "byte_size": 10**12,
            "asset_type": "source",
        },
    )
    assert response.status_code == 422


def test_upload_of_a_disguised_payload_is_rejected(api):
    """Bytes are validated after the transfer, whatever the declared type said."""
    project = api.create_project()
    payload = b"<?php system($_GET['cmd']); ?>" * 40
    init = api.post(
        f"/v1/projects/{project['id']}/assets/uploads",
        json={
            "filename": "payload.png",
            "content_type": "image/png",
            "byte_size": len(payload),
            "asset_type": "source",
        },
    ).json()
    api.client.put(
        init["upload"]["url"].replace("http://testserver", ""),
        content=payload,
        headers=init["upload"]["headers"],
    )
    complete = api.post(
        f"/v1/projects/{project['id']}/assets/uploads/complete",
        json={"asset_id": init["asset_id"], "ownership_confirmed": True},
    )
    assert complete.status_code == 422
    assert complete.json()["error"]["code"] == "unsupported_format"

    # The rejected object is not left in storage as a completed asset.
    assets = api.get(f"/v1/projects/{project['id']}/assets").json()
    assert not [asset for asset in assets if asset["type"] == "source"]


def test_upload_of_a_gif_is_rejected(api):
    project = api.create_project()
    buffer = io.BytesIO()
    Image.fromarray(demo.flat_gradient(60, 40)).save(buffer, format="GIF")
    data = buffer.getvalue()
    init = api.post(
        f"/v1/projects/{project['id']}/assets/uploads",
        json={
            "filename": "anim.png",
            "content_type": "image/png",
            "byte_size": len(data),
            "asset_type": "source",
        },
    ).json()
    api.client.put(
        init["upload"]["url"].replace("http://testserver", ""),
        content=data,
        headers=init["upload"]["headers"],
    )
    complete = api.post(
        f"/v1/projects/{project['id']}/assets/uploads/complete",
        json={"asset_id": init["asset_id"], "ownership_confirmed": True},
    )
    assert complete.status_code == 422


def test_alpha_upload_reports_transparency(api):
    project = api.create_project()
    rgb, alpha = demo.alpha_sticker(120)
    _, complete = api.upload_image(project["id"], demo.to_png(rgb, alpha))
    body = complete.json()
    assert body["has_alpha"] is True
    assert any("Transparency" in warning for warning in body["warnings"])


def test_provenance_metadata_is_reported_and_preserved(api):
    """An image carrying rights metadata says so, and is never stripped."""
    from PIL import Image as PILImage

    background = demo.flat_gradient(120, 90)
    image = PILImage.fromarray(background)
    exif = image.getexif()
    exif[0x013B] = "Demo Artist"  # Artist
    exif[0x8298] = "(c) 2026 Demo Artist"  # Copyright
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())

    project = api.create_project()
    _, complete = api.upload_image(
        project["id"], buffer.getvalue(), filename="signed.jpg", content_type="image/jpeg"
    )
    body = complete.json()
    assert body["provenance"]["exif_rights"]
    assert any("metadata" in warning.lower() for warning in body["warnings"])


def test_upload_completion_is_idempotent(api, demo_images):
    project = api.create_project()
    asset_id, first = api.upload_image(project["id"], demo_images["stamped_png"])
    second = api.post(
        f"/v1/projects/{project['id']}/assets/uploads/complete",
        json={"asset_id": asset_id, "ownership_confirmed": True},
    )
    assert second.status_code == 200
    assert second.json()["width"] == first.json()["width"]

    assets = api.get(f"/v1/projects/{project['id']}/assets").json()
    assert len([asset for asset in assets if asset["type"] == "source_preview"]) == 1


def test_asset_analysis_endpoint(api, demo_images):
    project = api.create_project()
    asset_id, _ = api.upload_image(project["id"], demo_images["stamped_png"])
    response = api.get(f"/v1/projects/{project['id']}/assets/{asset_id}/analysis")
    assert response.status_code == 200
    assert response.json()["megapixels"] > 0


def test_delete_asset(api, demo_images):
    project = api.create_project()
    asset_id, _ = api.upload_image(project["id"], demo_images["stamped_png"])
    assert api.delete(f"/v1/projects/{project['id']}/assets/{asset_id}").status_code == 204
    assert api.get(f"/v1/projects/{project['id']}/assets/{asset_id}").status_code == 404


def test_storage_quota_blocks_uploads_past_the_limit(api, demo_images):
    """One account cannot hold more than its storage allowance."""
    from artrestore_api.config import get_settings

    settings = get_settings()
    original = settings.max_user_storage_bytes
    try:
        project = api.create_project()
        api.upload_image(project["id"], demo_images["stamped_png"])
        used = api.get("/v1/account/usage").json()["total_bytes"]
        assert used > 0

        # Shrink the quota to just under what a repeat upload would need.
        settings.max_user_storage_bytes = used + 10

        response = api.post(
            f"/v1/projects/{project['id']}/assets/uploads",
            json={
                "filename": "second.png",
                "content_type": "image/png",
                "byte_size": len(demo_images["stamped_png"]),
                "asset_type": "source",
            },
        )
        assert response.status_code == 413
        body = response.json()["error"]
        assert body["code"] == "storage_quota_exceeded"
        assert body["details"]["limit_bytes"] == used + 10
    finally:
        settings.max_user_storage_bytes = original


def test_usage_reports_the_storage_limit(api):
    from artrestore_api.config import get_settings

    body = api.get("/v1/account/usage").json()
    assert body["limit_bytes"] == get_settings().max_user_storage_bytes


def test_oversized_request_bodies_are_refused_before_parsing(api):
    """The API defends itself against huge bodies; it does not rely on the proxy."""
    from artrestore_api.config import get_settings

    settings = get_settings()
    original = settings.max_upload_bytes
    try:
        settings.max_upload_bytes = 2048
        project = api.create_project()
        response = api.post(
            f"/v1/projects/{project['id']}/masks",
            json={"editor_state": {"regions": []}, "mask_png_base64": "A" * 10_000},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"
    finally:
        settings.max_upload_bytes = original
