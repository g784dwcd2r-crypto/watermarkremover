"""Retention sweep and account erasure.

Retention is enforced by deleting bytes, not by hiding rows: the sweep removes
the storage prefix for every expired project and then the database rows.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logging_setup import log_context
from ..models import ConsentRecord, Project, User
from ..storage import Storage

logger = logging.getLogger(__name__)


def expired_projects(db: Session, *, now: dt.datetime | None = None, limit: int = 200) -> list[Project]:
    moment = now or dt.datetime.now(dt.timezone.utc)
    return list(
        db.execute(
            select(Project)
            .where(Project.delete_after.is_not(None), Project.delete_after <= moment)
            .order_by(Project.delete_after.asc())
            .limit(limit)
        ).scalars()
    )


def sweep(db: Session, storage: Storage, *, now: dt.datetime | None = None) -> dict:
    """Delete every project whose retention window has closed."""
    deleted_projects = 0
    deleted_objects = 0
    for project in expired_projects(db, now=now):
        prefix = f"users/{project.user_id}/projects/{project.id}/"
        try:
            deleted_objects += storage.delete_prefix(prefix)
        except Exception:  # noqa: BLE001 - a storage hiccup must not stall the sweep
            logger.exception("retention sweep could not clear storage", extra=log_context(project_id=project.id))
            continue
        db.delete(project)
        deleted_projects += 1
    db.flush()
    logger.info(
        "retention sweep complete",
        extra=log_context(projects=deleted_projects, objects=deleted_objects),
    )
    return {"projects_deleted": deleted_projects, "objects_deleted": deleted_objects}


def apply_retention_preference(db: Session, user: User, retention_days: int) -> None:
    """Update the account default and re-date every existing project."""
    preferences = dict(user.retention_preferences or {})
    preferences["retention_days"] = retention_days
    user.retention_preferences = preferences

    for project in user.projects:
        project.retention_days = retention_days
        base = project.created_at or dt.datetime.now(dt.timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=dt.timezone.utc)
        project.delete_after = base + dt.timedelta(days=retention_days)
    db.flush()


def delete_account(db: Session, user: User, storage: Storage) -> dict:
    """Erase a user: every object, every project, and the account row.

    Consent records are removed with the account. They exist to prove the user
    made an attestation about their own content; once that content is gone,
    keeping the record would mean retaining data about a deleted person.
    """
    prefix = f"users/{user.id}/"
    objects = 0
    try:
        objects = storage.delete_prefix(prefix)
    except Exception:  # noqa: BLE001
        logger.exception("account deletion could not clear storage")

    project_count = len(user.projects)
    consent_count = db.query(ConsentRecord).filter(ConsentRecord.user_id == user.id).count()
    db.delete(user)
    db.flush()
    logger.info(
        "account deleted",
        extra=log_context(projects=project_count, objects=objects, consents=consent_count),
    )
    return {
        "projects_deleted": project_count,
        "objects_deleted": objects,
        "consent_records_deleted": consent_count,
    }


def export_account_data(db: Session, user: User) -> dict:
    """A portable JSON export of everything the account holds.

    Image bytes are referenced by asset id, not embedded: the user downloads
    those through the normal signed-URL endpoints.
    """
    from .projects import storage_usage

    return {
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "retention_preferences": user.retention_preferences,
        },
        "storage_usage": storage_usage(db, user.id),
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "project_type": project.project_type,
                "status": project.status,
                "retention_days": project.retention_days,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "assets": [
                    {
                        "id": asset.id,
                        "type": asset.type,
                        "mime_type": asset.mime_type,
                        "width": asset.width,
                        "height": asset.height,
                        "byte_size": asset.byte_size,
                        "metadata": asset.asset_metadata,
                    }
                    for asset in project.assets
                ],
                "masks": [
                    {"version": mask.version, "editor_state": mask.editor_state}
                    for mask in project.masks
                ],
                "stages": [
                    {
                        "stage_type": stage.stage_type,
                        "order_index": stage.order_index,
                        "duration": stage.duration,
                        "settings": stage.settings,
                    }
                    for stage in project.stages
                ],
                "exports": [
                    {
                        "id": export.id,
                        "format": export.format,
                        "byte_size": export.byte_size,
                        "settings": export.settings,
                        "disclosure_metadata": export.disclosure_metadata,
                        "created_at": export.created_at.isoformat() if export.created_at else None,
                    }
                    for export in project.exports
                ],
                "jobs": [
                    {
                        "id": job.id,
                        "job_type": job.job_type,
                        "status": job.status,
                        "parameters": job.parameters,
                        "result": job.result,
                        "created_at": job.created_at.isoformat() if job.created_at else None,
                    }
                    for job in project.jobs
                ],
            }
            for project in user.projects
        ],
        "consent_records": [
            {
                "consent_type": record.consent_type,
                "policy_version": record.policy_version,
                "statement": record.statement,
                "project_id": record.project_id,
                "confirmed_at": record.confirmed_at.isoformat() if record.confirmed_at else None,
            }
            for record in user.consents
        ],
    }
