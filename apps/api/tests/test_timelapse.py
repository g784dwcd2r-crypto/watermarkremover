"""Timelapse reconstruction, end to end through the API."""

from __future__ import annotations

import pytest

from artrestore_imaging import demo



@pytest.fixture
def timelapse_project(api):
    project = api.create_project(name="Process video", project_type="timelapse")
    artwork = demo.painted_illustration(320, 240)
    api.upload_image(project["id"], demo.to_png(artwork), filename="artwork.png")
    return project


def _render_payload(**overrides) -> dict:
    payload = {
        "mode": "paint_reveal",
        "duration_seconds": 5.0,
        "fps": 24,
        "preset": "square",
        "formats": ["mp4"],
        "seed": 21,
        "hold_final_seconds": 0.5,
    }
    payload.update(overrides)
    return payload


# -- options and analysis ---------------------------------------------------


def test_options_describe_modes_and_disclosure(api, timelapse_project):
    body = api.get(f"/v1/projects/{timelapse_project['id']}/timelapse/options").json()
    keys = {mode["key"] for mode in body["modes"]}
    assert keys == {
        "sketch_to_colour",
        "paint_reveal",
        "layer_build",
        "hand_drawn_strokes",
        "real_intermediates",
    }
    assert body["disclosure"]["end_card_default"] is True
    assert body["disclosure"]["reconstruction_type"] == "AI-assisted reconstructed artwork timelapse"
    assert "cannot be turned off" in body["disclosure"]["note"]
    assert body["fps_options"] == [24, 30, 60]


def test_analysis_creates_an_editable_timeline(api, timelapse_project, assert_job_succeeded):
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/analyze",
        json={"mode": "sketch_to_colour", "seed": 3},
    )
    assert response.status_code == 202
    job = api.get(
        f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}"
    ).json()
    assert_job_succeeded(job)
    assert job["result"]["analysis"]["palette"]

    stages = api.get(f"/v1/projects/{timelapse_project['id']}/timelapse/stages").json()
    assert len(stages["items"]) >= 5
    assert stages["items"][0]["stage_type"] == "blank_canvas"
    assert stages["total_duration"] > 0


def test_analysis_requires_ownership_confirmation(api):
    project = api.create_project(project_type="timelapse")
    api.upload_image(
        project["id"], demo.to_png(demo.flat_gradient(120, 90)), confirm=False
    )
    response = api.post(
        f"/v1/projects/{project['id']}/timelapse/analyze", json={"mode": "paint_reveal"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "consent_required"


def test_real_intermediates_requires_uploaded_stages(api, timelapse_project):
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/analyze",
        json={"mode": "real_intermediates"},
    )
    assert response.status_code == 422
    assert "progress images" in response.json()["error"]["message"]


# -- the stage timeline -----------------------------------------------------


def test_stage_timeline_can_be_reordered_and_retimed(api, timelapse_project):
    api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/analyze",
        json={"mode": "layer_build"},
    )
    stages = api.get(f"/v1/projects/{timelapse_project['id']}/timelapse/stages").json()["items"]

    reordered = [
        {
            "stage_type": stage["stage_type"],
            "label": stage["label"],
            "order_index": len(stages) - index - 1,
            "duration": 2.0,
            "enabled": index != 1,
            "settings": stage["settings"],
        }
        for index, stage in enumerate(stages)
    ]
    response = api.put(
        f"/v1/projects/{timelapse_project['id']}/timelapse/stages", json={"stages": reordered}
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["items"][0]["stage_type"] == stages[-1]["stage_type"]
    assert any(stage["enabled"] is False for stage in saved["items"])


def test_timeline_shorter_than_the_minimum_is_rejected(api, timelapse_project):
    response = api.put(
        f"/v1/projects/{timelapse_project['id']}/timelapse/stages",
        json={"stages": [{"stage_type": "final_hold", "order_index": 0, "duration": 1.0}]},
    )
    assert response.status_code == 422
    assert "minimum" in response.json()["error"]["message"]


def test_timeline_longer_than_the_maximum_is_rejected(api, timelapse_project):
    response = api.put(
        f"/v1/projects/{timelapse_project['id']}/timelapse/stages",
        json={
            "stages": [
                {"stage_type": "base_colours", "order_index": 0, "duration": 200.0},
                {"stage_type": "final_hold", "order_index": 1, "duration": 200.0},
            ]
        },
    )
    assert response.status_code == 422


def test_empty_timeline_is_rejected(api, timelapse_project):
    response = api.put(
        f"/v1/projects/{timelapse_project['id']}/timelapse/stages", json={"stages": []}
    )
    assert response.status_code == 422


# -- rendering --------------------------------------------------------------


def test_render_produces_a_video_export(api, timelapse_project, assert_job_succeeded):
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(formats=["mp4", "poster", "project_json"]),
    )
    assert response.status_code == 202, response.text
    job = api.get(
        f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}"
    ).json()
    assert_job_succeeded(job)

    result = job["result"]
    assert result["fps"] == 24
    assert result["duration_seconds"] > 0
    assert result["disclosure"]["is_original_recording"] is False
    outputs = {entry["output"] for entry in result["exports"]}
    assert {"mp4", "poster", "project_json"} <= outputs

    history = api.get(f"/v1/projects/{timelapse_project['id']}/exports").json()
    assert history["total"] >= 3
    formats = {item["format"] for item in history["items"]}
    assert "mp4" in formats


def test_render_records_the_disclosure_consent(api, timelapse_project):
    api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render", json=_render_payload()
    )
    consents = api.get(f"/v1/projects/{timelapse_project['id']}/consent").json()
    disclosures = [
        record for record in consents if record["consent_type"] == "timelapse_disclosure"
    ]
    assert disclosures
    assert "reconstruction" in disclosures[0]["statement"].lower()


def test_every_export_carries_the_reconstruction_metadata(api, timelapse_project):
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(formats=["mp4", "gif", "poster"]),
    )
    api.get(f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}")
    history = api.get(f"/v1/projects/{timelapse_project['id']}/exports").json()
    assert history["items"]
    for item in history["items"]:
        assert (
            item["disclosure_metadata"]["reconstruction_type"]
            == "AI-assisted reconstructed artwork timelapse"
        )
        assert item["disclosure_metadata"]["is_original_recording"] in ("false", False)


def test_rendered_mp4_is_valid_and_labelled(api, timelapse_project, tmp_path, assert_job_succeeded):
    from artrestore_api.db import session_scope
    from artrestore_api.models import Export
    from artrestore_api.storage import get_storage
    from artrestore_timelapse import ffmpeg_available, probe

    if not ffmpeg_available():
        pytest.skip("FFmpeg is not installed")

    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(preset="vertical_9x16", fps=30),
    )
    job = api.get(
        f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}"
    ).json()
    assert_job_succeeded(job)

    export_id = next(
        entry["export_id"] for entry in job["result"]["exports"] if entry["output"] == "mp4"
    )
    with session_scope() as session:
        export = session.get(Export, export_id)
        data = get_storage().get_bytes(export.storage_key)

    path = tmp_path / "rendered.mp4"
    path.write_bytes(data)
    info = probe(path)
    stream = next(item for item in info["streams"] if item["codec_type"] == "video")
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert stream["r_frame_rate"] == "30/1"

    tags = {key.lower(): value for key, value in info["format"]["tags"].items()}
    assert tags["title"] == "Reconstructed process"
    assert "not a recording" in tags["comment"]


def test_preview_render_is_smaller_and_faster(api, timelapse_project, assert_job_succeeded):
    preview = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/preview",
        json=_render_payload(preset="square", idempotency_key="p1"),
    )
    job = api.get(
        f"/v1/projects/{timelapse_project['id']}/jobs/{preview.json()['id']}"
    ).json()
    assert_job_succeeded(job)
    assert job["result"]["preview"] is True
    assert job["result"]["width"] <= 1080


def test_preview_does_not_record_a_publication_disclosure(api, timelapse_project):
    """Only a final render is a publishable artefact, so only it takes the attestation."""
    api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/preview", json=_render_payload()
    )
    consents = api.get(f"/v1/projects/{timelapse_project['id']}/consent").json()
    assert not [c for c in consents if c["consent_type"] == "timelapse_disclosure"]


def test_render_respects_a_saved_timeline(api, timelapse_project, assert_job_succeeded):
    api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/analyze",
        json={"mode": "paint_reveal"},
    )
    api.put(
        f"/v1/projects/{timelapse_project['id']}/timelapse/stages",
        json={
            "stages": [
                {"stage_type": "blank_canvas", "order_index": 0, "duration": 1.0},
                {"stage_type": "texture_details", "order_index": 1, "duration": 5.0,
                 "settings": {"reveal": "organic"}},
            ]
        },
    )
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(duration_seconds=6.0),
    )
    job = api.get(
        f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}"
    ).json()
    assert_job_succeeded(job)
    assert [stage["stage_type"] for stage in job["result"]["stages"]] == [
        "blank_canvas",
        "texture_details",
    ]


def test_render_is_deterministic_for_a_seed(api, timelapse_project, assert_job_succeeded):
    from artrestore_api.db import session_scope
    from artrestore_api.models import Export
    from artrestore_api.storage import get_storage

    digests = []
    for attempt in range(2):
        response = api.post(
            f"/v1/projects/{timelapse_project['id']}/timelapse/render",
            json=_render_payload(seed=99, idempotency_key=f"run-{attempt}"),
        )
        job = api.get(
            f"/v1/projects/{timelapse_project['id']}/jobs/{response.json()['id']}"
        ).json()
        assert_job_succeeded(job)
        export_id = next(
            entry["export_id"] for entry in job["result"]["exports"] if entry["output"] == "mp4"
        )
        with session_scope() as session:
            export = session.get(Export, export_id)
            digests.append(get_storage().get_bytes(export.storage_key))
    assert digests[0] == digests[1]


def test_render_requires_ownership_confirmation(api):
    project = api.create_project(project_type="timelapse")
    api.upload_image(project["id"], demo.to_png(demo.flat_gradient(120, 90)), confirm=False)
    response = api.post(
        f"/v1/projects/{project['id']}/timelapse/render", json=_render_payload()
    )
    assert response.status_code == 403


def test_render_rejects_an_asset_from_another_project(api, timelapse_project):
    other = api.create_project(project_type="timelapse")
    asset_id, _ = api.upload_image(other["id"], demo.to_png(demo.flat_gradient(120, 90)))
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(audio_asset_id=asset_id),
    )
    assert response.status_code == 422


def test_invalid_duration_is_rejected(api, timelapse_project):
    assert (
        api.post(
            f"/v1/projects/{timelapse_project['id']}/timelapse/render",
            json=_render_payload(duration_seconds=2.0),
        ).status_code
        == 422
    )
    assert (
        api.post(
            f"/v1/projects/{timelapse_project['id']}/timelapse/render",
            json=_render_payload(duration_seconds=400.0),
        ).status_code
        == 422
    )


def test_brush_range_must_be_ordered(api, timelapse_project):
    response = api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render",
        json=_render_payload(brush_size_min=40, brush_size_max=10),
    )
    assert response.status_code == 422


def test_other_user_cannot_render(api, other_api, timelapse_project):
    response = other_api.post(
        f"/v1/projects/{timelapse_project['id']}/timelapse/render", json=_render_payload()
    )
    assert response.status_code == 404
