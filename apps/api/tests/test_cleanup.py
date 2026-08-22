"""End-to-end cleanup: masks, safeguards, job lifecycle and export."""

from __future__ import annotations

import numpy as np
import pytest


def _stamp_box(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return (
        int(xs.min()) - 3,
        int(ys.min()) - 3,
        int(xs.max() - xs.min()) + 6,
        int(ys.max() - ys.min()) + 6,
    )


@pytest.fixture
def cleanup_project(api, demo_images, rect_editor_state):
    """A project with a stamped source image and a mask over the stamp."""
    project = api.create_project(name="Date stamp removal")
    api.upload_image(project["id"], demo_images["stamped_png"])
    width, height = demo_images["size"]
    box = _stamp_box(demo_images["stamp_mask"])
    mask = api.save_mask(project["id"], rect_editor_state(*box, width=width, height=height))
    return project, mask


# -- mask versions ----------------------------------------------------------


def test_masks_are_versioned(api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    first = api.save_mask(project["id"], {"image": {"width": 320, "height": 240}, "regions": []})
    second = api.save_mask(project["id"], {"image": {"width": 320, "height": 240}, "regions": []})
    assert first["version"] == 1
    assert second["version"] == 2

    listing = api.get(f"/v1/projects/{project['id']}/masks").json()
    assert [item["version"] for item in listing] == [2, 1]


def test_mask_preview_reports_coverage_and_mode(api, cleanup_project):
    project, mask = cleanup_project
    response = api.post(f"/v1/projects/{project['id']}/masks/{mask['version']}/preview")
    assert response.status_code == 200
    body = response.json()
    assert 0 < body["coverage"] < 0.2
    assert body["region_count"] >= 1
    assert body["suggested_mode"] in ("fast_fill", "texture_restore", "edge_aware", "art_mode")
    assert "protection" in body


def test_detect_overlays_returns_suggestions(api, cleanup_project):
    project, _ = cleanup_project
    response = api.post(f"/v1/projects/{project['id']}/detect-overlays", json={"limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["candidates"], list)
    assert "approve the mask" in body["notice"]


def test_assisted_segmentation(api, cleanup_project, demo_images):
    project, _ = cleanup_project
    box = _stamp_box(demo_images["stamp_mask"])
    response = api.post(
        f"/v1/projects/{project['id']}/segment",
        json={"mode": "text", "box": list(box)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "text_strokes"
    assert body["selected_pixels"] > 0
    assert body["mask_png_base64"]


# -- job lifecycle ----------------------------------------------------------


def test_cleanup_job_runs_and_produces_a_result(api, cleanup_project):
    project, mask = cleanup_project
    response = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mode": "fast_fill",
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()

    # Eager mode runs the worker inline, so the job is already terminal.
    final = api.get(f"/v1/projects/{project['id']}/jobs/{job['id']}").json()
    assert final["status"] == "succeeded", final
    assert final["progress"] == 1.0
    assert final["result"]["mode"] == "fast_fill"
    assert final["result"]["region_count"] >= 1

    assets = api.get(f"/v1/projects/{project['id']}/assets").json()
    kinds = {asset["type"] for asset in assets}
    assert {"processed", "processed_preview", "difference"} <= kinds


def test_cleanup_actually_changes_the_masked_pixels(api, cleanup_project, demo_images):
    from artrestore_api.storage import get_storage
    from artrestore_imaging import load_safe_raster

    project, mask = cleanup_project
    api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mode": "fast_fill",
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    )
    assets = api.get(f"/v1/projects/{project['id']}/assets").json()
    processed = next(asset for asset in assets if asset["type"] == "processed")

    storage = get_storage()
    from artrestore_api.db import session_scope
    from artrestore_api.models import Asset

    with session_scope() as session:
        row = session.get(Asset, processed["id"])
        data = storage.get_bytes(row.storage_key)

    cleaned = load_safe_raster(data).rgb
    original = load_safe_raster(demo_images["stamped_png"]).rgb
    stamp = demo_images["stamp_mask"] > 0

    changed = np.abs(cleaned.astype(int) - original.astype(int)).mean(axis=2)
    assert changed[stamp].mean() > changed[~stamp].mean() * 3
    assert cleaned.shape == original.shape


def test_cleanup_requires_ownership_confirmation(api, demo_images, rect_editor_state):
    project = api.create_project()
    # Upload without confirming.
    api.upload_image(project["id"], demo_images["stamped_png"], confirm=False)
    api.save_mask(project["id"], rect_editor_state(10, 10, 40, 20, width=320, height=240))

    response = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={"mask_approved": True, "mode": "fast_fill"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "consent_required"


def test_cleanup_requires_mask_approval(api, cleanup_project):
    project, mask = cleanup_project
    response = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={"mask_version": mask["version"], "mask_approved": False},
    )
    assert response.status_code == 422


def test_cleanup_without_a_mask_is_rejected(api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    response = api.post(f"/v1/projects/{project['id']}/cleanup", json={"mask_approved": True})
    assert response.status_code == 422


def test_idempotency_key_returns_the_same_job(api, cleanup_project):
    project, mask = cleanup_project
    payload = {
        "mask_version": mask["version"],
        "mask_approved": True,
        "mode": "fast_fill",
        "idempotency_key": "abc-123",
        "acknowledged_protected_kinds": ["copyright_notice"],
    }
    first = api.post(f"/v1/projects/{project['id']}/cleanup", json=payload).json()
    second = api.post(f"/v1/projects/{project['id']}/cleanup", json=payload).json()
    assert first["id"] == second["id"]

    jobs = api.get(f"/v1/projects/{project['id']}/jobs").json()
    assert jobs["total"] == 1


def test_cancelling_a_finished_job_is_rejected(api, cleanup_project):
    project, mask = cleanup_project
    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    ).json()
    response = api.post(f"/v1/projects/{project['id']}/jobs/{job['id']}/cancel")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_cancellable"


def test_retry_is_only_allowed_for_failed_jobs(api, cleanup_project):
    project, mask = cleanup_project
    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    ).json()
    response = api.post(f"/v1/projects/{project['id']}/jobs/{job['id']}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_retryable"


def test_failed_job_can_be_retried(api, cleanup_project):
    """A failure leaves a retryable job rather than a dead end."""
    from artrestore_api.db import session_scope
    from artrestore_api.models import ProcessingJob

    project, mask = cleanup_project
    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    ).json()

    with session_scope() as session:
        row = session.get(ProcessingJob, job["id"])
        row.status = "failed"
        row.error_code = "internal_error"
        row.error_message = "simulated failure"

    response = api.post(f"/v1/projects/{project['id']}/jobs/{job['id']}/retry")
    assert response.status_code == 202
    assert api.get(f"/v1/projects/{project['id']}/jobs/{job['id']}").json()["status"] == "succeeded"


def test_job_events_stream_reports_completion(api, cleanup_project):
    project, mask = cleanup_project
    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    ).json()

    with api.client.stream(
        "GET",
        f"/v1/projects/{project['id']}/jobs/{job['id']}/events",
        headers={"X-CSRF-Token": api.csrf_token},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: done" in body
    assert "succeeded" in body


# -- safeguards -------------------------------------------------------------


def test_masking_a_signature_is_refused(api, demo_images, rect_editor_state):
    project = api.create_project(name="Signed artwork")
    api.upload_image(project["id"], demo_images["signed_png"], filename="signed.png")
    x, y, w, h = demo_images["signature_box"]
    mask = api.save_mask(project["id"], rect_editor_state(x, y, w, h, width=360, height=260))

    preview = api.post(f"/v1/projects/{project['id']}/masks/{mask['version']}/preview").json()
    assert preview["protection"]["blocked"] is True

    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={"mask_version": mask["version"], "mask_approved": True},
    ).json()
    final = api.get(f"/v1/projects/{project['id']}/jobs/{job['id']}").json()
    assert final["status"] == "failed"
    assert final["error_code"] == "protected_region"
    assert "attribution" in final["error_message"]


def test_signature_refusal_cannot_be_acknowledged_away(api, demo_images, rect_editor_state):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["signed_png"], filename="signed.png")
    x, y, w, h = demo_images["signature_box"]
    mask = api.save_mask(project["id"], rect_editor_state(x, y, w, h, width=360, height=260))

    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": [
                "signature",
                "copyright_notice",
                "stock_watermark",
            ],
        },
    ).json()
    final = api.get(f"/v1/projects/{project['id']}/jobs/{job['id']}").json()
    assert final["status"] == "failed"
    assert final["error_code"] == "protected_region"


def test_stock_watermarked_image_is_refused(api, demo_images, rect_editor_state):
    """A tiled licensing overlay stops the run.

    At this image size the lattice evidence is graded 'moderate', so the refusal
    is the reviewable one - the user must state the pattern is not a watermark
    rather than the app silently cleaning it.
    """
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stock_png"], filename="stock.png")
    mask = api.save_mask(project["id"], rect_editor_state(40, 40, 90, 40, width=360, height=260))

    job = api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={"mask_version": mask["version"], "mask_approved": True},
    ).json()
    final = api.get(f"/v1/projects/{project['id']}/jobs/{job['id']}").json()
    assert final["status"] == "failed"
    assert final["error_code"] in ("protected_region", "protected_region_review")
    assert "watermark" in final["error_message"].lower()


def test_acknowledgement_is_recorded_as_consent(api, cleanup_project):
    project, mask = cleanup_project
    api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    )
    consents = api.get(f"/v1/projects/{project['id']}/consent").json()
    attestations = [
        record for record in consents if record["consent_type"] == "protected_region_attestation"
    ]
    assert attestations


# -- export -----------------------------------------------------------------


def test_export_preserves_dimensions_and_records_disclosure(api, cleanup_project, demo_images):
    project, mask = cleanup_project
    api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    )
    response = api.post(f"/v1/projects/{project['id']}/exports", json={"format": "png"})
    assert response.status_code == 201, response.text
    export = response.json()
    assert export["byte_size"] > 0
    assert export["download_url"]
    assert export["disclosure_metadata"]["provenance_preserved"] is True
    assert export["disclosure_metadata"]["source_resolution"] == list(demo_images["size"])

    history = api.get(f"/v1/projects/{project['id']}/exports").json()
    assert history["total"] == 1


def test_export_without_a_processed_image_is_rejected(api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    response = api.post(f"/v1/projects/{project['id']}/exports", json={"format": "png"})
    assert response.status_code == 422
    assert "cleanup" in response.json()["error"]["message"]


def test_export_download_link_is_short_lived(api, cleanup_project):
    project, mask = cleanup_project
    api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={
            "mask_version": mask["version"],
            "mask_approved": True,
            "acknowledged_protected_kinds": ["copyright_notice"],
        },
    )
    export = api.post(f"/v1/projects/{project['id']}/exports", json={"format": "png"}).json()
    link = api.get(f"/v1/projects/{project['id']}/exports/{export['id']}/download").json()
    assert link["expires_in"] <= 900
    assert "signature=" in link["download_url"]
