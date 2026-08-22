"""API test harness.

Everything runs against SQLite and a temporary filesystem storage root, with
Celery in eager mode, so the full request -> job -> result path is exercised in
process without Postgres, Redis or MinIO.
"""

from __future__ import annotations

import base64
import os
import pathlib

import pytest

SCRATCH = pathlib.Path(os.environ.get("PYTEST_TMP_ROOT", "/tmp")).resolve()


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory):
    """Point the process at throwaway infrastructure before anything imports settings."""
    root = tmp_path_factory.mktemp("artrestore")
    os.environ.update(
        {
            "ARS_ENVIRONMENT": "test",
            "ARS_DEBUG": "true",
            "ARS_SECRET_KEY": "test-secret-key-that-is-long-enough-for-the-checks-0123456789",
            "ARS_DATABASE_URL": f"sqlite:///{root / 'test.db'}",
            "ARS_STORAGE_BACKEND": "local",
            "ARS_LOCAL_STORAGE_DIR": str(root / "storage"),
            "ARS_CELERY_TASK_ALWAYS_EAGER": "true",
            "ARS_RATE_LIMIT_ENABLED": "false",
            "ARS_COOKIE_SECURE": "false",
            "ARS_PUBLIC_API_URL": "http://testserver",
            "ARS_LOG_LEVEL": "ERROR",
            "ARS_REDIS_URL": "",
        }
    )
    from artrestore_api.config import reset_settings_cache

    reset_settings_cache()
    yield


@pytest.fixture(scope="session")
def app(_environment):
    from artrestore_api import models  # noqa: F401 - registers tables on Base.metadata
    from artrestore_api.config import get_settings
    from artrestore_api.db import Base, configure_engine, get_engine
    from artrestore_api.storage import build_storage, set_storage

    settings = get_settings()
    configure_engine(settings.database_url)
    Base.metadata.create_all(get_engine())
    set_storage(build_storage(settings))

    # Registering the worker tasks lets eager mode execute them in-process.
    import artrestore_worker.tasks  # noqa: F401
    from artrestore_api.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clean_database(app):
    """Truncate between tests so ordering never matters."""
    from artrestore_api import models
    from artrestore_api.db import get_engine, session_scope
    from sqlalchemy import delete

    yield
    with session_scope() as session:
        for model in (
            models.ConsentRecord,
            models.Export,
            models.TimelapseStage,
            models.ProcessingJob,
            models.Mask,
            models.Asset,
            models.Project,
            models.EmailToken,
            models.UserSession,
            models.User,
        ):
            session.execute(delete(model))
    _ = get_engine


class ApiClient:
    """A signed-in client that carries the CSRF header automatically.

    Each instance owns its own ``TestClient`` so two accounts in one test have
    independent cookie jars - otherwise the second sign-in would silently
    overwrite the first account's session.
    """

    def __init__(self, client, email: str, password: str) -> None:
        self._client = client
        self.client = client
        self.email = email
        self.password = password
        self.csrf_token = ""
        self.user: dict = {}

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"X-CSRF-Token": self.csrf_token} if self.csrf_token else {}
        headers.update(extra or {})
        return headers

    def register(self, **overrides):
        payload = {
            "email": self.email,
            "name": "Test Artist",
            "password": self.password,
            "accept_terms": True,
            "accept_authorized_use_policy": True,
        }
        payload.update(overrides)
        response = self._client.post("/v1/auth/register", json=payload)
        if response.status_code == 201:
            self.csrf_token = response.json()["csrf_token"]
            self.user = response.json()["user"]
        return response

    def login(self):
        response = self._client.post(
            "/v1/auth/login", json={"email": self.email, "password": self.password}
        )
        if response.status_code == 200:
            self.csrf_token = response.json()["csrf_token"]
            self.user = response.json()["user"]
        return response

    def get(self, url, **kwargs):
        return self._client.get(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def post(self, url, **kwargs):
        return self._client.post(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def patch(self, url, **kwargs):
        return self._client.patch(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def delete(self, url, **kwargs):
        return self._client.delete(
            url, headers=self._headers(kwargs.pop("headers", None)), **kwargs
        )

    def put(self, url, **kwargs):
        return self._client.put(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    # -- workflow helpers ---------------------------------------------------

    def create_project(self, name="Test project", project_type="cleanup", **kwargs):
        response = self.post(
            "/v1/projects",
            json={"name": name, "project_type": project_type, **kwargs},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def upload_image(
        self,
        project_id: str,
        data: bytes,
        *,
        filename="demo.png",
        content_type="image/png",
        asset_type="source",
        confirm=True,
    ):
        """Run the full signed-upload handshake and return the completion response."""
        init = self.post(
            f"/v1/projects/{project_id}/assets/uploads",
            json={
                "filename": filename,
                "content_type": content_type,
                "byte_size": len(data),
                "asset_type": asset_type,
            },
        )
        assert init.status_code == 201, init.text
        body = init.json()
        upload = body["upload"]
        put = self._client.put(
            upload["url"].replace("http://testserver", ""),
            content=data,
            headers=upload.get("headers") or {},
        )
        assert put.status_code == 200, put.text
        complete = self.post(
            f"/v1/projects/{project_id}/assets/uploads/complete",
            json={"asset_id": body["asset_id"], "ownership_confirmed": confirm},
        )
        return body["asset_id"], complete

    def save_mask(self, project_id: str, editor_state: dict, png: bytes | None = None):
        payload: dict = {"editor_state": editor_state}
        if png is not None:
            payload["mask_png_base64"] = base64.b64encode(png).decode("ascii")
        response = self.post(f"/v1/projects/{project_id}/masks", json=payload)
        assert response.status_code == 201, response.text
        return response.json()


def _account(app, email: str, password: str):
    from fastapi.testclient import TestClient

    test_client = TestClient(app)
    account = ApiClient(test_client, email, password)
    assert account.register().status_code == 201, "account registration failed"
    return account


@pytest.fixture
def api(app):
    account = _account(app, "artist@example.com", "correct-horse-battery-staple")
    yield account
    account.client.close()


@pytest.fixture
def other_api(app):
    """A second account, used by the authorization-boundary tests."""
    account = _account(app, "intruder@example.com", "another-long-password-value")
    yield account
    account.client.close()


# -- image fixtures ---------------------------------------------------------


@pytest.fixture(scope="session")
def demo_images():
    from artrestore_imaging import demo

    background = demo.flat_gradient(320, 240)
    stamped, stamp_mask = demo.add_date_stamp(background)
    painting = demo.painted_illustration(360, 260)
    signed, signature_box = demo.add_signature(painting)
    return {
        "clean_png": demo.to_png(background),
        "stamped_png": demo.to_png(stamped),
        "stamp_mask": stamp_mask,
        "painting_png": demo.to_png(painting),
        "signed_png": demo.to_png(signed),
        "signature_box": signature_box,
        "stock_png": demo.to_png(demo.add_stock_watermark(painting)),
        "size": (320, 240),
    }


def _assert_job_succeeded(job: dict) -> dict:
    """Assert a job finished, surfacing the worker's error instead of a dict dump."""
    if job.get("status") != "succeeded":
        raise AssertionError(
            f"job {job.get('job_type')} ended as {job.get('status')}: "
            f"{job.get('error_code')} - {job.get('error_message')} "
            f"result={job.get('result')}"
        )
    return job


def _rect_editor_state(x, y, w, h, *, width, height, feather=2, expand=1):
    return {
        "version": 1,
        "image": {"width": width, "height": height},
        "regions": [{"id": "r1", "type": "rect", "x": x, "y": y, "width": w, "height": h}],
        "adjustments": {"feather": feather, "expand": expand, "blur": 0},
    }


@pytest.fixture(scope="session")
def assert_job_succeeded():
    """A fixture rather than an import: two suites cannot both own ``conftest``."""
    return _assert_job_succeeded


@pytest.fixture(scope="session")
def rect_editor_state():
    return _rect_editor_state
