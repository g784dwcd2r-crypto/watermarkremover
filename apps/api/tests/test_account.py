"""Account settings, retention, data export and deletion."""

from __future__ import annotations

import datetime as dt

import pytest


def test_storage_usage_reflects_uploads(api, demo_images):
    empty = api.get("/v1/account/usage").json()
    assert empty["total_bytes"] == 0

    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])

    usage = api.get("/v1/account/usage").json()
    assert usage["project_count"] == 1
    assert usage["asset_count"] >= 2  # source plus preview
    assert usage["total_bytes"] > 0
    assert usage["by_project_type"]["cleanup"] > 0


def test_update_name(api):
    response = api.patch("/v1/account", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


@pytest.mark.parametrize("days", [1, 7, 30])
def test_retention_options(api, days):
    response = api.patch("/v1/account", json={"retention_days": days})
    assert response.status_code == 200
    assert response.json()["retention_preferences"]["retention_days"] == days


def test_invalid_retention_is_rejected(api):
    assert api.patch("/v1/account", json={"retention_days": 14}).status_code == 422


def test_changing_retention_redates_existing_projects(api):
    """Shortening retention applies to work already uploaded, not only to new work."""
    project = api.create_project()
    before = api.get(f"/v1/projects/{project['id']}").json()["delete_after"]

    api.patch("/v1/account", json={"retention_days": 1})
    after = api.get(f"/v1/projects/{project['id']}").json()
    assert after["retention_days"] == 1
    assert after["delete_after"] < before


def test_retention_sweep_deletes_expired_projects(api, demo_images):
    from artrestore_api.db import session_scope
    from artrestore_api.models import Project
    from artrestore_api.services import retention as retention_service
    from artrestore_api.storage import get_storage

    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    prefix = f"users/{api.user['id']}/projects/{project['id']}/"

    with session_scope() as session:
        row = session.get(Project, project["id"])
        row.delete_after = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)

    storage = get_storage()
    with session_scope() as session:
        summary = retention_service.sweep(session, storage)

    assert summary["projects_deleted"] == 1
    assert summary["objects_deleted"] > 0
    assert api.get(f"/v1/projects/{project['id']}").status_code == 404
    assert storage.delete_prefix(prefix) == 0


def test_retention_sweep_leaves_current_projects_alone(api):
    from artrestore_api.db import session_scope
    from artrestore_api.services import retention as retention_service
    from artrestore_api.storage import get_storage

    project = api.create_project()
    with session_scope() as session:
        summary = retention_service.sweep(session, get_storage())
    assert summary["projects_deleted"] == 0
    assert api.get(f"/v1/projects/{project['id']}").status_code == 200


def test_data_export_contains_projects_and_consents(api, demo_images):
    project = api.create_project(name="Exportable")
    api.upload_image(project["id"], demo_images["stamped_png"])

    payload = api.get("/v1/account/export").json()
    assert payload["account"]["email"] == api.email
    assert payload["projects"][0]["name"] == "Exportable"
    assert payload["projects"][0]["assets"]
    assert any(
        record["consent_type"] == "ownership_confirmation" for record in payload["consent_records"]
    )
    # Image bytes are referenced, never embedded.
    serialised = str(payload)
    assert "base64" not in serialised


def test_account_deletion_requires_the_password(api):
    response = api.post("/v1/account/delete", json={"confirm": "DELETE", "password": "wrong-one"})
    assert response.status_code == 403


def test_account_deletion_removes_everything(api, demo_images):
    from artrestore_api.storage import get_storage

    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    prefix = f"users/{api.user['id']}/"

    response = api.post("/v1/account/delete", json={"confirm": "DELETE", "password": api.password})
    assert response.status_code == 204

    # The session is gone and the account cannot sign back in.
    assert api.client.get("/v1/auth/session").status_code == 401
    assert api.login().status_code == 401
    assert get_storage().delete_prefix(prefix) == 0


def test_account_deletion_requires_the_confirm_word(api):
    assert api.post("/v1/account/delete", json={"confirm": "yes"}).status_code == 422


def test_consents_are_listed(api):
    records = api.get("/v1/account/consents").json()
    assert {record["consent_type"] for record in records} >= {"terms", "authorized_use_policy"}
    assert all(record["policy_version"] for record in records)
