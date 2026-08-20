"""FastAPI application factory.

``/openapi.json`` and the interactive docs at ``/docs`` are generated from the
routers and schemas, so they are always in step with the implementation.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from artrestore_imaging.errors import ImagingError

from .config import get_settings
from .errors import APIError, api_error_handler
from .logging_setup import (
    configure_logging,
    log_context,
    new_request_id,
    request_id_var,
)
from .routers import account, assets, auth, exports, health, jobs, masks, projects
from .storage import get_storage

logger = logging.getLogger(__name__)

DESCRIPTION = """
ArtRestore Studio is a tool for **authorized** image work.

* **Visible watermark cleanup** removes overlays, date stamps and obsolete
  marks from images you own or have permission to edit.
* **Reconstructed timelapses** turn a finished artwork into a plausible process
  video. The result is always labelled a *reconstruction* - never a recording of
  the original creation process.

Two rules are enforced by this API rather than by policy text alone:

1. Nothing is processed until the project carries the attestation
   *"I own this image or have permission to edit it."*
2. Artist signatures, copyright lines, stock-agency watermarks, provenance
   labels and Content Credentials are detected and refused. Metadata is
   preserved on every export; there is no strip-metadata mode.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    for problem in settings.check_production_safety():
        logger.error("unsafe production configuration", extra=log_context(problem=problem))
    if settings.error_tracking_dsn:
        _init_error_tracking(settings)
    logger.info(
        "api starting",
        extra=log_context(
            environment=settings.environment,
            storage_backend=settings.storage_backend,
            eager_tasks=settings.celery_task_always_eager,
        ),
    )
    yield
    logger.info("api stopping")


def _init_error_tracking(settings) -> None:
    """Placeholder wiring for a Sentry-compatible error tracker.

    The dependency is intentionally not vendored; installing ``sentry-sdk`` and
    setting ``ARS_ERROR_TRACKING_DSN`` is all that is required.
    """
    try:  # pragma: no cover - optional dependency
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.error_tracking_dsn,
            environment=settings.environment,
            traces_sample_rate=settings.error_tracking_sample_rate,
            send_default_pii=False,  # never ship customer content to a third party
        )
        logger.info("error tracking initialised")
    except ImportError:
        logger.warning(
            "ARS_ERROR_TRACKING_DSN is set but sentry-sdk is not installed; "
            "error tracking is disabled."
        )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=health.API_VERSION,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        contact={"name": "ArtRestore Studio"},
        license_info={"name": "Proprietary"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Accept", "Last-Event-ID"],
        expose_headers=["X-Request-Id", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = int((time.perf_counter() - started) * 1000)

        response.headers["X-Request-Id"] = request_id
        # Path only: query strings can carry storage signatures.
        logger.info(
            "request",
            extra=log_context(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ),
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    app.add_exception_handler(APIError, api_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Use the same error envelope as everything else.

        FastAPI's default shape is ``{"detail": [...]}``; the client switches on
        ``error.code``, so request validation is normalised to match.
        """
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
                "message": error.get("msg", "Invalid value."),
            }
            for error in exc.errors()
        ]
        first = fields[0]["message"] if fields else "The request could not be validated."
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": first,
                    "details": {"fields": fields},
                }
            },
        )

    @app.exception_handler(ImagingError)
    async def imaging_error_handler(_request: Request, exc: ImagingError) -> JSONResponse:
        """Imaging failures surface with their own stable codes."""
        return JSONResponse(
            status_code=422,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra=log_context(error_type=type(exc).__name__))
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side. The request was not completed.",
                    "details": {},
                }
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(projects.router)
    app.include_router(assets.router)
    app.include_router(masks.router)
    app.include_router(jobs.router)
    app.include_router(exports.router)

    try:
        from .routers import timelapse

        app.include_router(timelapse.router)
    except ImportError:  # pragma: no cover - timelapse router is optional at import time
        logger.warning("timelapse router unavailable")

    if settings.storage_backend == "local":
        # The signed object gateway only exists for the filesystem backend.
        app.include_router(assets.storage_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/healthz",
        }

    return app


app = create_app()


def storage_ready() -> bool:  # pragma: no cover - used by deployment scripts
    return bool(get_storage().health().get("ok"))
