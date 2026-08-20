"""Database models.

Ownership is modelled explicitly: every row that can hold image data hangs off a
``Project``, and every project hangs off a ``User``. There is no path to an
asset that does not pass through a project the caller owns, which is what the
authorization-boundary tests assert.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import GUID, Base, JSONType, new_id

# -- enumerations (stored as strings so both PostgreSQL and SQLite work) ----

PROJECT_TYPES = ("cleanup", "timelapse")
PROJECT_STATUSES = ("draft", "ready", "processing", "complete", "failed")

ASSET_TYPES = (
    "source",  # the untouched upload; never overwritten
    "source_preview",
    "mask",
    "processed",
    "processed_preview",
    "difference",
    "intermediate",  # user-supplied progress stages for a timelapse
    "line_art",
    "audio",
    "frame",
    "poster",
    "export",
)

JOB_TYPES = ("cleanup", "timelapse_analyze", "timelapse_preview", "timelapse_render", "export")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

STAGE_TYPES = (
    "blank_canvas",
    "construction_sketch",
    "refined_lines",
    "base_colours",
    "shadows",
    "highlights",
    "texture_details",
    "background",
    "silhouette",
    "colour_groups",
    "focal_details",
    "polish",
    "broad_forms",
    "secondary_forms",
    "detail_pass",
    "colour_correction",
    "stroke_pass",
    "real_intermediate",
    "final_hold",
)

EXPORT_FORMATS = ("png", "jpeg", "webp", "tiff", "mp4", "webm", "gif", "zip", "json")

CONSENT_TYPES = (
    "ownership_confirmation",  # "I own this image or have permission to edit it."
    "authorized_use_policy",
    "protected_region_attestation",
    "timelapse_disclosure",
    "terms",
    "privacy",
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: {"retention_days": 7, "auto_delete_exports": false}
    retention_preferences: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    consents: Mapped[list["ConsentRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def retention_days(self) -> int:
        try:
            value = int((self.retention_preferences or {}).get("retention_days", 7))
        except (TypeError, ValueError):
            return 7
        return value if value in (1, 7, 30) else 7


class UserSession(Base):
    """A logged-in session.

    Only a hash of the session token is stored, so a database dump cannot be
    replayed as a login. No IP address or user agent is retained.
    """

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class EmailToken(Base):
    """Single-use email tokens: password reset and passwordless sign-in."""

    __tablename__ = "email_tokens"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # reset | magic_link | verify
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    project_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    delete_after: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="projects")
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    masks: Mapped[list["Mask"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    stages: Mapped[list["TimelapseStage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    exports: Mapped[list["Export"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_projects_user_created", "user_id", "created_at"),)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    #: Descriptions only - provenance summary, colour mode, orientation.
    #: Never raw metadata blobs and never image content.
    asset_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upload_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="assets")

    __table_args__ = (Index("ix_assets_project_type", "project_id", "type"),)


class Mask(Base):
    __tablename__ = "masks"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512))
    #: The declarative editor document. The server re-rasterises from this, so a
    #: job is reproducible from stored state alone.
    editor_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="masks")

    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_mask_project_version"),)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    progress_message: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    #: Repeating a request with the same key returns the original job rather
    #: than queueing duplicate work.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    queue_task_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_job_project_idempotency"),
        Index("ix_jobs_project_status", "project_id", "status"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")


class TimelapseStage(Base):
    __tablename__ = "timelapse_stages"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stage_type: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Seconds of screen time for this stage.
    duration: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="stages")

    __table_args__ = (Index("ix_stages_project_order", "project_id", "order_index"),)


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    #: The reconstruction disclosure written into the file's own metadata.
    disclosure_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    project: Mapped[Project] = relationship(back_populates="exports")


class ConsentRecord(Base):
    """An immutable record that a user made a specific attestation.

    Written before any processing starts and never updated in place, so the
    audit trail reflects what was actually agreed and under which policy
    version.
    """

    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    consent_type: Mapped[str] = mapped_column(String(48), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    confirmed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="consents")

    __table_args__ = (Index("ix_consent_user_project", "user_id", "project_id"),)
