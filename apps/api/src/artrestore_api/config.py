"""Application settings.

Every value is environment-driven with an ``ARS_`` prefix so the API, the
worker and the Compose stack share one configuration surface. See
``.env.example`` at the repository root for the documented list.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RetentionDays = Literal[1, 7, 30]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARS_",
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- general ------------------------------------------------------------
    environment: str = "development"
    debug: bool = False
    app_name: str = "ArtRestore Studio"
    public_web_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"

    # -- security -----------------------------------------------------------
    secret_key: str = "dev-only-insecure-secret-key-change-me-please-0123456789"
    session_cookie_name: str = "ars_session"
    csrf_cookie_name: str = "ars_csrf"
    session_ttl_seconds: int = 60 * 60 * 24 * 14
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: str = "http://localhost:3000"

    # -- database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://artrestore:artrestore@localhost:5432/artrestore"

    # -- redis / celery -----------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_always_eager: bool = False

    # -- storage ------------------------------------------------------------
    storage_backend: Literal["s3", "local"] = "s3"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "artrestore"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_use_path_style: bool = True
    signed_url_ttl_seconds: int = 300
    local_storage_dir: str = "./storage-data"

    # -- uploads ------------------------------------------------------------
    max_upload_bytes: int = 40 * 1024 * 1024
    max_image_pixels: int = 50_000_000
    allowed_upload_mime: str = "image/jpeg,image/png,image/webp,image/tiff"
    max_audio_bytes: int = 20 * 1024 * 1024
    allowed_audio_mime: str = "audio/mpeg,audio/wav,audio/ogg"

    # -- email (transactional) ----------------------------------------------
    # Unset host = the logging sender: reset and sign-in links are logged in a
    # redacted form and, outside production, returned through the API for
    # development. Set a host to send real mail over SMTP with STARTTLS.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    # -- abuse limits ---------------------------------------------------------
    #: Total bytes one account may hold across every project (2 GiB default).
    max_user_storage_bytes: int = 2 * 1024 * 1024 * 1024
    #: Queued-plus-running jobs one account may have at once, across projects.
    max_active_jobs_per_user: int = 5
    #: Hard wall-clock limit for one worker task; the soft limit fires 60s
    #: earlier so the job row is failed cleanly instead of the process dying.
    task_time_limit_seconds: int = 3600

    # -- retention / privacy ------------------------------------------------
    default_retention_days: int = 7
    retention_sweep_minutes: int = 60
    log_level: str = "INFO"

    # -- rate limiting ------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_upload_per_minute: int = 30
    rate_limit_job_per_minute: int = 30
    rate_limit_default_per_minute: int = 120

    # -- image processing ---------------------------------------------------
    inpaint_backend: str = "auto"
    lama_model_path: str = ""
    diffusion_model_path: str = ""
    segmentation_model_path: str = ""
    protected_region_enforcement: Literal["block", "warn"] = "block"

    # -- video --------------------------------------------------------------
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    preview_max_dimension: int = 640
    max_render_seconds: int = 300

    # -- policy versions ----------------------------------------------------
    authorized_use_policy_version: str = "2026-01-15"
    privacy_policy_version: str = "2026-01-15"
    terms_version: str = "2026-01-15"

    # -- observability ------------------------------------------------------
    error_tracking_dsn: str = ""
    error_tracking_sample_rate: float = 0.1

    # -- derived ------------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_upload_mime_tuple(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.allowed_upload_mime.split(",") if item.strip())

    @property
    def allowed_audio_mime_tuple(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.allowed_audio_mime.split(",") if item.strip())

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def backend_settings(self) -> dict:
        """Model paths handed to the imaging backends."""
        return {
            "lama_model_path": self.lama_model_path,
            "diffusion_model_path": self.diffusion_model_path,
            "segmentation_model_path": self.segmentation_model_path,
        }

    @field_validator("default_retention_days")
    @classmethod
    def _validate_retention(cls, value: int) -> int:
        if value not in (1, 7, 30):
            raise ValueError("ARS_DEFAULT_RETENTION_DAYS must be one of 1, 7 or 30")
        return value

    def check_production_safety(self) -> list[str]:
        """Configuration problems that must not reach production.

        Surfaced by the readiness probe and logged at startup rather than
        silently accepted.
        """
        problems: list[str] = []
        if not self.is_production:
            return problems
        if "dev-only-insecure" in self.secret_key or len(self.secret_key) < 32:
            problems.append("ARS_SECRET_KEY is unset or too short for production.")
        if not self.cookie_secure:
            problems.append("ARS_COOKIE_SECURE must be true in production.")
        if self.debug:
            problems.append("ARS_DEBUG must be false in production.")
        if self.storage_backend == "local":
            problems.append(
                "ARS_STORAGE_BACKEND=local is a development convenience; use S3-compatible storage."
            )
        if self.s3_access_key_id == "minioadmin":
            problems.append("Default MinIO credentials are still configured.")
        if not self.smtp_host:
            problems.append(
                "No SMTP host is configured. Password reset and passwordless sign-in "
                "cannot deliver email in production; set ARS_SMTP_HOST (and credentials) "
                "or wire a provider via set_email_sender()."
            )
        if not self.cookie_domain:
            # With host-only cookies, a SPA on app.example.com cannot read the
            # CSRF cookie set by api.example.com, and every unsafe request 403s.
            problems.append(
                "ARS_COOKIE_DOMAIN is unset. When the web app and the API run on "
                "different subdomains, the CSRF cookie becomes unreadable to the "
                "app; set the shared parent domain (e.g. .example.com)."
            )
        return problems


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that manipulate the environment."""
    get_settings.cache_clear()
