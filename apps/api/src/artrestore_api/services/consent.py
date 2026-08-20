"""Consent recording and enforcement.

The ownership attestation is a gate, not a checkbox that decorates the UI: the
upload cannot be marked complete and no job can be queued for a project until a
``ConsentRecord`` exists for it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import consent_required
from ..models import ConsentRecord, Project, User
from ..schemas import OWNERSHIP_STATEMENT

CONSENT_STATEMENTS = {
    "ownership_confirmation": OWNERSHIP_STATEMENT,
    "authorized_use_policy": "I have read and accept the authorized-use policy.",
    "protected_region_attestation": (
        "I confirm the flagged region is not an artist signature, credit line, "
        "watermark or provenance label."
    ),
    "timelapse_disclosure": (
        "I understand this video is an AI-assisted reconstruction, not a recording "
        "of the original creation process."
    ),
    "terms": "I accept the terms of service.",
    "privacy": "I have read the privacy policy.",
}


def policy_version_for(consent_type: str) -> str:
    settings = get_settings()
    return {
        "terms": settings.terms_version,
        "privacy": settings.privacy_policy_version,
    }.get(consent_type, settings.authorized_use_policy_version)


def record_consent(
    db: Session,
    *,
    user: User,
    consent_type: str,
    project: Project | None = None,
    statement: str | None = None,
    context: dict | None = None,
) -> ConsentRecord:
    """Append an immutable consent record."""
    record = ConsentRecord(
        user_id=user.id,
        project_id=project.id if project else None,
        consent_type=consent_type,
        policy_version=policy_version_for(consent_type),
        statement=statement or CONSENT_STATEMENTS.get(consent_type, ""),
        context=context or {},
    )
    db.add(record)
    db.flush()
    return record


def has_consent(db: Session, *, user_id: str, consent_type: str, project_id: str | None) -> bool:
    statement = select(ConsentRecord.id).where(
        ConsentRecord.user_id == user_id,
        ConsentRecord.consent_type == consent_type,
    )
    if project_id is not None:
        statement = statement.where(ConsentRecord.project_id == project_id)
    return db.execute(statement.limit(1)).first() is not None


def require_ownership_confirmation(db: Session, project: Project) -> None:
    """Raise unless the project carries an ownership attestation."""
    if has_consent(
        db,
        user_id=project.user_id,
        consent_type="ownership_confirmation",
        project_id=project.id,
    ):
        return
    raise consent_required(
        "Confirm that you own this image or have permission to edit it before processing.",
        details={"required_consent": "ownership_confirmation", "statement": OWNERSHIP_STATEMENT},
    )


def list_consents(db: Session, user_id: str) -> list[ConsentRecord]:
    return list(
        db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.user_id == user_id)
            .order_by(ConsentRecord.confirmed_at.desc())
        ).scalars()
    )
