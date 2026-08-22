"""Project CRUD, consent capture and deletion."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from ..deps import CSRFProtected, CurrentUser, DbSession, DefaultRateLimit, StorageDep
from ..logging_setup import log_context
from ..models import Export, Project, TimelapseStage
from ..schemas import (
    ConsentOut,
    ConsentRequest,
    ProjectCreateRequest,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectUpdateRequest,
)
from ..services import consent as consent_service
from ..services import projects as project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _detail(db, project: Project) -> ProjectDetailOut:
    latest = project_service.latest_mask(db, project.id)
    running = project_service.active_job(db, project.id)
    stage_count = db.execute(
        select(func.count(TimelapseStage.id)).where(TimelapseStage.project_id == project.id)
    ).scalar_one()
    export_count = db.execute(
        select(func.count(Export.id)).where(Export.project_id == project.id)
    ).scalar_one()

    detail = ProjectDetailOut.model_validate(project)
    detail.assets = sorted(  # type: ignore[assignment]
        project.assets, key=lambda item: (item.type, item.order_index)
    )
    detail.latest_mask_version = latest.version if latest else None
    detail.active_job = running  # type: ignore[assignment]
    detail.ownership_confirmed = consent_service.has_consent(
        db,
        user_id=project.user_id,
        consent_type="ownership_confirmation",
        project_id=project.id,
    )
    detail.stage_count = int(stage_count)
    detail.export_count = int(export_count)
    return detail


@router.get(
    "", response_model=ProjectListOut, dependencies=[DefaultRateLimit], summary="List projects"
)
def list_projects(
    user: CurrentUser,
    db: DbSession,
    project_type: str | None = Query(None, pattern="^(cleanup|timelapse)$"),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ProjectListOut:
    """The dashboard listing, filterable by type, status and name."""
    conditions = [Project.user_id == user.id, Project.deleted_at.is_(None)]
    if project_type:
        conditions.append(Project.project_type == project_type)
    if status_filter:
        conditions.append(Project.status == status_filter)
    if search:
        conditions.append(Project.name.ilike(f"%{search.strip()}%"))

    total = db.execute(select(func.count(Project.id)).where(*conditions)).scalar_one()
    rows = db.execute(
        select(Project)
        .where(*conditions)
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars()
    return ProjectListOut(
        items=[ProjectOut.model_validate(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ProjectDetailOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected, DefaultRateLimit],
    summary="Create a project",
)
def create_project(
    payload: ProjectCreateRequest, user: CurrentUser, db: DbSession
) -> ProjectDetailOut:
    project = project_service.create_project(
        db,
        user=user,
        name=payload.name,
        project_type=payload.project_type,
        retention_days=payload.retention_days,
    )
    db.commit()
    logger.info(
        "project created",
        extra=log_context(project_id=project.id, project_type=project.project_type),
    )
    return _detail(db, project)


@router.get("/{project_id}", response_model=ProjectDetailOut, summary="Get a project")
def get_project(project_id: str, user: CurrentUser, db: DbSession) -> ProjectDetailOut:
    project = project_service.get_owned_project(db, project_id, user)
    return _detail(db, project)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetailOut,
    dependencies=[CSRFProtected],
    summary="Rename a project or change its retention",
)
def update_project(
    project_id: str, payload: ProjectUpdateRequest, user: CurrentUser, db: DbSession
) -> ProjectDetailOut:
    project = project_service.get_owned_project(db, project_id, user)
    if payload.name is not None:
        project.name = payload.name.strip()[:200]
    if payload.retention_days is not None:
        project.retention_days = payload.retention_days
        project.delete_after = project_service.compute_delete_after(payload.retention_days)
    if payload.settings is not None:
        project.settings = {**(project.settings or {}), **payload.settings}
    db.commit()
    return _detail(db, project)


@router.post(
    "/{project_id}/duplicate",
    response_model=ProjectDetailOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected],
    summary="Duplicate a project",
)
def duplicate_project(
    project_id: str, user: CurrentUser, db: DbSession, storage: StorageDep
) -> ProjectDetailOut:
    """Copy sources, masks and stages into a fresh project.

    Processed results and exports are not copied: a duplicate is a new starting
    point, not a claim that the same output already exists.
    """
    project = project_service.get_owned_project(db, project_id, user)
    clone = project_service.duplicate_project(db, project, storage)
    if consent_service.has_consent(
        db, user_id=user.id, consent_type="ownership_confirmation", project_id=project.id
    ):
        consent_service.record_consent(
            db,
            user=user,
            consent_type="ownership_confirmation",
            project=clone,
            context={"inherited_from_project": project.id},
        )
    db.commit()
    return _detail(db, clone)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CSRFProtected],
    summary="Delete a project and all of its files",
)
def delete_project(project_id: str, user: CurrentUser, db: DbSession, storage: StorageDep) -> None:
    """Immediate and irreversible: every stored object under the project is removed."""
    project = project_service.get_owned_project(db, project_id, user)
    removed = project_service.delete_project(db, project, storage)
    db.commit()
    logger.info("project deleted", extra=log_context(project_id=project_id, objects=removed))


@router.post(
    "/{project_id}/consent",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CSRFProtected],
    summary="Record an attestation for this project",
)
def record_project_consent(
    project_id: str, payload: ConsentRequest, user: CurrentUser, db: DbSession
) -> ConsentOut:
    """Record the ownership confirmation or another project-scoped attestation.

    Nothing can be processed until an ``ownership_confirmation`` exists for the
    project.
    """
    project = project_service.get_owned_project(db, project_id, user)
    record = consent_service.record_consent(
        db,
        user=user,
        consent_type=payload.consent_type,
        project=project,
        statement=payload.statement,
        context=payload.context,
    )
    if payload.consent_type == "ownership_confirmation" and project.status == "draft":
        project.status = "ready"
    db.commit()
    return ConsentOut.model_validate(record)


@router.get(
    "/{project_id}/consent",
    response_model=list[ConsentOut],
    summary="List attestations for this project",
)
def list_project_consent(project_id: str, user: CurrentUser, db: DbSession) -> list[ConsentOut]:
    project = project_service.get_owned_project(db, project_id, user)
    records = [
        record
        for record in consent_service.list_consents(db, user.id)
        if record.project_id == project.id
    ]
    return [ConsentOut.model_validate(record) for record in records]
