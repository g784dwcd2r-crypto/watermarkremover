"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..config import get_settings
from ..db import get_engine
from ..deps import DbSession
from ..schemas import HealthOut, PolicyOut, ReadinessOut
from ..security.ratelimit import get_rate_limiter
from ..storage import get_storage

router = APIRouter(tags=["system"])

API_VERSION = "0.1.0"


@router.get("/healthz", response_model=HealthOut, summary="Liveness probe")
def healthz() -> HealthOut:
    """Returns 200 as long as the process is serving requests."""
    settings = get_settings()
    return HealthOut(status="ok", version=API_VERSION, environment=settings.environment)


@router.get("/readyz", response_model=ReadinessOut, summary="Readiness probe")
def readyz(db: DbSession) -> ReadinessOut:
    """Checks the database, object storage and rate-limiter backends."""
    settings = get_settings()
    checks: dict = {}
    warnings = settings.check_production_safety()

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "dialect": get_engine().dialect.name}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    try:
        checks["storage"] = get_storage().health()
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = {"ok": False, "error": type(exc).__name__}

    limiter = get_rate_limiter()
    checks["rate_limiter"] = {"ok": True, "backend": limiter.backend}
    if limiter.backend == "memory" and settings.rate_limit_enabled:
        warnings.append(
            "Rate limiting is using the in-process fallback; limits are per replica, not global."
        )

    status = "ok" if all(check.get("ok") for check in checks.values()) else "degraded"
    return ReadinessOut(status=status, checks=checks, warnings=warnings)


@router.get("/v1/policies", response_model=PolicyOut, summary="Policy versions and limits")
def policies() -> PolicyOut:
    """The values the client needs to render consent copy and upload limits."""
    from artrestore_imaging import CLEANUP_MODES

    from ..schemas import OWNERSHIP_STATEMENT

    settings = get_settings()
    return PolicyOut(
        authorized_use_policy_version=settings.authorized_use_policy_version,
        privacy_policy_version=settings.privacy_policy_version,
        terms_version=settings.terms_version,
        ownership_statement=OWNERSHIP_STATEMENT,
        retention_options=[1, 7, 30],
        max_upload_bytes=settings.max_upload_bytes,
        allowed_mime_types=list(settings.allowed_upload_mime_tuple),
        cleanup_modes=list(CLEANUP_MODES),
        timelapse_modes=[
            "sketch_to_colour",
            "paint_reveal",
            "layer_build",
            "hand_drawn_strokes",
            "real_intermediates",
        ],
        reconstruction_disclosure="AI-assisted reconstructed artwork timelapse",
    )
