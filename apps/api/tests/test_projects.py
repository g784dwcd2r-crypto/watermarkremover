"""Project CRUD and the authorization boundary between accounts."""

from __future__ import annotations

import pytest


def test_create_and_fetch_project(api):
    project = api.create_project(name="Client retouch", project_type="cleanup")
    assert project["project_type"] == "cleanup"
    assert project["status"] == "draft"
    assert project["retention_days"] in (1, 7, 30)
    assert project["delete_after"] is not None
    assert project["ownership_confirmed"] is False

    fetched = api.get(f"/v1/projects/{project['id']}").json()
    assert fetched["id"] == project["id"]


def test_list_projects_with_filters(api):
    api.create_project(name="Cleanup one", project_type="cleanup")
    api.create_project(name="Timelapse one", project_type="timelapse")

    everything = api.get("/v1/projects").json()
    assert everything["total"] == 2

    cleanups = api.get("/v1/projects?project_type=cleanup").json()
    assert cleanups["total"] == 1
    assert cleanups["items"][0]["name"] == "Cleanup one"

    searched = api.get("/v1/projects?search=timelapse").json()
    assert searched["total"] == 1


def test_list_projects_paginates(api):
    for index in range(5):
        api.create_project(name=f"Project {index}")
    page = api.get("/v1/projects?limit=2&offset=2").json()
    assert page["total"] == 5
    assert len(page["items"]) == 2


def test_rename_project(api):
    project = api.create_project()
    response = api.patch(f"/v1/projects/{project['id']}", json={"name": "Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_change_retention_updates_delete_after(api):
    project = api.create_project()
    response = api.patch(f"/v1/projects/{project['id']}", json={"retention_days": 1})
    assert response.status_code == 200
    assert response.json()["retention_days"] == 1


def test_invalid_retention_is_rejected(api):
    project = api.create_project()
    response = api.patch(f"/v1/projects/{project['id']}", json={"retention_days": 3})
    assert response.status_code == 422


def test_delete_project_removes_stored_objects(api, demo_images):
    from artrestore_api.storage import get_storage

    project = api.create_project()
    asset_id, complete = api.upload_image(project["id"], demo_images["stamped_png"])
    assert complete.status_code == 200

    storage = get_storage()
    prefix = f"users/{api.user['id']}/projects/{project['id']}/"
    assert storage.delete_prefix.__self__ is storage  # backend is the local one

    assert api.delete(f"/v1/projects/{project['id']}").status_code == 204
    assert api.get(f"/v1/projects/{project['id']}").status_code == 404
    # Nothing is left behind under the project prefix.
    assert storage.delete_prefix(prefix) == 0


def test_duplicate_copies_sources_but_not_results(api, demo_images):
    project = api.create_project(name="Original")
    api.upload_image(project["id"], demo_images["stamped_png"])
    api.save_mask(project["id"], {"image": {"width": 320, "height": 240}, "regions": []})

    response = api.post(f"/v1/projects/{project['id']}/duplicate")
    assert response.status_code == 201
    clone = response.json()
    assert clone["name"] == "Original (copy)"
    assert clone["id"] != project["id"]
    assert clone["export_count"] == 0

    source_assets = [asset for asset in clone["assets"] if asset["type"] == "source"]
    assert len(source_assets) == 1
    assert clone["latest_mask_version"] == 1


# -- authorization boundary -------------------------------------------------


def test_other_user_cannot_read_project(api, other_api, demo_images):
    project = api.create_project()
    assert other_api.get(f"/v1/projects/{project['id']}").status_code == 404


def test_other_user_cannot_modify_project(api, other_api):
    project = api.create_project()
    assert other_api.patch(f"/v1/projects/{project['id']}", json={"name": "hijacked"}).status_code == 404
    assert other_api.delete(f"/v1/projects/{project['id']}").status_code == 404


def test_other_user_cannot_list_or_download_assets(api, other_api, demo_images):
    project = api.create_project()
    asset_id, _ = api.upload_image(project["id"], demo_images["stamped_png"])

    assert other_api.get(f"/v1/projects/{project['id']}/assets").status_code == 404
    assert (
        other_api.get(f"/v1/projects/{project['id']}/assets/{asset_id}").status_code == 404
    )


def test_other_user_cannot_queue_a_job(api, other_api, demo_images):
    project = api.create_project()
    api.upload_image(project["id"], demo_images["stamped_png"])
    response = other_api.post(
        f"/v1/projects/{project['id']}/cleanup",
        json={"mask_approved": True, "mode": "fast_fill"},
    )
    assert response.status_code == 404


def test_missing_and_foreign_projects_are_indistinguishable(api, other_api):
    """Both return 404 so the API cannot be used to probe for other users' work."""
    project = api.create_project()
    foreign = other_api.get(f"/v1/projects/{project['id']}")
    missing = other_api.get("/v1/projects/00000000-0000-4000-8000-000000000000")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["code"] == missing.json()["error"]["code"]


def test_anonymous_access_is_rejected(client, api):
    project = api.create_project()
    client.cookies.clear()
    assert client.get(f"/v1/projects/{project['id']}").status_code == 401
    assert client.get("/v1/projects").status_code == 401
