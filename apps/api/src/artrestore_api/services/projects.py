"""Project access control and lifecycle."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import not_found
from ..models import Asset, Export, Mask, ProcessingJob, Project, TimelapseStage, User


def get_owned_project(db: Session, project_id: str, user: User) -> Project:
    """Fetch a project, or raise 404 when it is not this user's.

    A missing project and someone else's project return the same 404: a
    different status for the second case would leak the existence of other
    users' work.
    """
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id or project.deleted_at is not None:
        raise not_found("That project does not exist.")
    return project


def compute_delete_after(retention_days: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=retention_days)


def create_project(
    db: Session, *, user: User, name: str, project_type: str, retention_days: int | None = None
) -> Project:
    days = retention_days or user.retention_days or get_settings().default_retention_days
    project = Project(
        user_id=user.id,
        name=name.strip(),
        project_type=project_type,
        status="draft",
        retention_days=days,
        delete_after=compute_delete_after(days),
        settings={},
    )
    db.add(project)
    db.flush()
    return project


def duplicate_project(db: Session, project: Project, storage) -> Project:
    """Copy a project's settings, source assets, masks and stages.

    Derived artefacts (processed images, exports, job history) are not copied -
    the duplicate is a fresh starting point, not a claim that the same result
    already exists.
    """
    from ..storage import build_object_key

    clone = Project(
        user_id=project.user_id,
        name=f"{project.name} (copy)"[:200],
        project_type=project.project_type,
        status="draft",
        settings=dict(project.settings or {}),
        retention_days=project.retention_days,
        delete_after=compute_delete_after(project.retention_days),
    )
    db.add(clone)
    db.flush()

    copied_types = {"source", "intermediate", "line_art", "audio"}
    for asset in project.assets:
        if asset.type not in copied_types or not asset.upload_complete:
            continue
        filename = asset.storage_key.rsplit("/", 1)[-1]
        new_key = build_object_key(project.user_id, clone.id, asset.type, filename)
        storage.put_bytes(new_key, storage.get_bytes(asset.storage_key), asset.mime_type)
        db.add(
            Asset(
                project_id=clone.id,
                type=asset.type,
                storage_key=new_key,
                mime_type=asset.mime_type,
                width=asset.width,
                height=asset.height,
                byte_size=asset.byte_size,
                checksum=asset.checksum,
                asset_metadata=dict(asset.asset_metadata or {}),
                order_index=asset.order_index,
                upload_complete=True,
            )
        )

    for mask in project.masks:
        db.add(
            Mask(
                project_id=clone.id,
                version=mask.version,
                storage_key=None,
                editor_state=dict(mask.editor_state or {}),
            )
        )

    for stage in project.stages:
        db.add(
            TimelapseStage(
                project_id=clone.id,
                stage_type=stage.stage_type,
                label=stage.label,
                order_index=stage.order_index,
                duration=stage.duration,
                enabled=stage.enabled,
                settings=dict(stage.settings or {}),
            )
        )

    db.flush()
    return clone


def latest_mask(db: Session, project_id: str) -> Mask | None:
    return db.execute(
        select(Mask).where(Mask.project_id == project_id).order_by(Mask.version.desc()).limit(1)
    ).scalar_one_or_none()


def active_job(db: Session, project_id: str) -> ProcessingJob | None:
    return db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status.in_(("queued", "running")),
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def storage_usage(db: Session, user_id: str) -> dict:
    project_ids = [
        row[0]
        for row in db.execute(
            select(Project.id).where(Project.user_id == user_id, Project.deleted_at.is_(None))
        )
    ]
    if not project_ids:
        return {
            "total_bytes": 0,
            "asset_count": 0,
            "project_count": 0,
            "export_bytes": 0,
            "by_project_type": {},
        }

    asset_bytes, asset_count = db.execute(
        select(func.coalesce(func.sum(Asset.byte_size), 0), func.count(Asset.id)).where(
            Asset.project_id.in_(project_ids)
        )
    ).one()
    export_bytes = db.execute(
        select(func.coalesce(func.sum(Export.byte_size), 0)).where(
            Export.project_id.in_(project_ids)
        )
    ).scalar_one()

    by_type: dict[str, int] = {}
    rows = db.execute(
        select(Project.project_type, func.coalesce(func.sum(Asset.byte_size), 0))
        .join(Asset, Asset.project_id == Project.id, isouter=True)
        .where(Project.id.in_(project_ids))
        .group_by(Project.project_type)
    )
    for project_type, total in rows:
        by_type[project_type] = int(total or 0)

    return {
        "total_bytes": int(asset_bytes or 0) + int(export_bytes or 0),
        "asset_count": int(asset_count or 0),
        "project_count": len(project_ids),
        "export_bytes": int(export_bytes or 0),
        "by_project_type": by_type,
    }


def delete_project(db: Session, project: Project, storage) -> int:
    """Delete a project and every byte it owns, immediately."""
    prefix = f"users/{project.user_id}/projects/{project.id}/"
    removed = storage.delete_prefix(prefix)
    db.delete(project)
    db.flush()
    return removed
