"""Worker test harness.

The worker shares the API's models, storage and settings, so the fixtures mirror
the API suite: SQLite, a temporary storage root, and Celery in eager mode.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory):
    root = tmp_path_factory.mktemp("artrestore-worker")
    os.environ.update(
        {
            "ARS_ENVIRONMENT": "test",
            "ARS_SECRET_KEY": "worker-test-secret-key-long-enough-for-the-checks-0123456789",
            "ARS_DATABASE_URL": f"sqlite:///{root / 'worker.db'}",
            "ARS_STORAGE_BACKEND": "local",
            "ARS_LOCAL_STORAGE_DIR": str(root / "storage"),
            "ARS_CELERY_TASK_ALWAYS_EAGER": "true",
            "ARS_RATE_LIMIT_ENABLED": "false",
            "ARS_LOG_LEVEL": "CRITICAL",
            "ARS_REDIS_URL": "",
        }
    )
    from artrestore_api.config import reset_settings_cache

    reset_settings_cache()

    from artrestore_api import models  # noqa: F401
    from artrestore_api.config import get_settings
    from artrestore_api.db import Base, configure_engine, get_engine
    from artrestore_api.storage import build_storage, set_storage

    settings = get_settings()
    configure_engine(settings.database_url)
    Base.metadata.create_all(get_engine())
    set_storage(build_storage(settings))
    yield


@pytest.fixture
def project():
    """A user and a cleanup project, cleaned up afterwards."""
    from artrestore_api.db import session_scope
    from artrestore_api.models import Project, User
    from artrestore_api.services import projects as project_service

    with session_scope() as session:
        user = User(email="worker@example.com", name="Worker", password_hash="x")
        session.add(user)
        session.flush()
        created = project_service.create_project(
            session, user=user, name="Worker project", project_type="cleanup"
        )
        ids = (created.id, user.id)

    yield ids

    with session_scope() as session:
        row = session.get(Project, ids[0])
        if row is not None:
            session.delete(row)
        owner = session.get(User, ids[1])
        if owner is not None:
            session.delete(owner)


@pytest.fixture
def job(project):
    """A queued cleanup job attached to that project."""
    from artrestore_api.db import session_scope
    from artrestore_api.models import ProcessingJob

    project_id, _ = project
    with session_scope() as session:
        row = ProcessingJob(
            project_id=project_id,
            job_type="cleanup",
            status="queued",
            parameters={"mode": "fast_fill"},
        )
        session.add(row)
        session.flush()
        return row.id
