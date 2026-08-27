"""Request and response models.

These drive the generated OpenAPI document at ``/openapi.json``; the docstrings
and field descriptions here are the API reference.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import (
    ASSET_TYPES,
    CONSENT_TYPES,
    EXPORT_FORMATS,
    PROJECT_TYPES,
)

RetentionDays = Literal[1, 7, 30]

#: The exact wording the user must confirm before any processing runs.
OWNERSHIP_STATEMENT = "I own this image or have permission to edit it."


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- auth -------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field("", max_length=120)
    password: str = Field(..., min_length=12, max_length=256)
    accept_terms: bool = Field(..., description="Must be true; records a consent entry.")
    accept_authorized_use_policy: bool = Field(
        ..., description="Must be true; records acceptance of the authorized-use policy."
    )

    @field_validator("accept_terms", "accept_authorized_use_policy")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must accept the terms and the authorized-use policy.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., max_length=256)
    password: str = Field(..., min_length=12, max_length=256)


class MagicLinkRequest(BaseModel):
    email: EmailStr


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., min_length=12, max_length=256)


class MagicLinkConfirm(BaseModel):
    token: str = Field(..., max_length=256)


class UserOut(ORMModel):
    id: str
    email: EmailStr
    name: str
    created_at: dt.datetime
    retention_preferences: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: dt.datetime


# -- account ----------------------------------------------------------------


class UpdateAccountRequest(BaseModel):
    name: str | None = Field(None, max_length=120)
    retention_days: RetentionDays | None = None


class DeleteAccountRequest(BaseModel):
    password: str | None = Field(None, max_length=256)
    confirm: Literal["DELETE"] = Field(
        ..., description="Type DELETE to confirm. Deletion is immediate and irreversible."
    )


class StorageUsageOut(BaseModel):
    total_bytes: int
    limit_bytes: int = 0
    asset_count: int
    project_count: int
    export_bytes: int
    by_project_type: dict[str, int] = Field(default_factory=dict)


# -- projects ---------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    project_type: Literal["cleanup", "timelapse"]
    retention_days: RetentionDays | None = None

    @field_validator("project_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in PROJECT_TYPES:
            raise ValueError(f"project_type must be one of {PROJECT_TYPES}")
        return value


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    retention_days: RetentionDays | None = None
    settings: dict[str, Any] | None = None


class ProjectOut(ORMModel):
    id: str
    name: str
    project_type: str
    status: str
    settings: dict[str, Any]
    retention_days: int
    delete_after: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ProjectDetailOut(ProjectOut):
    assets: list[AssetOut] = Field(default_factory=list)
    latest_mask_version: int | None = None
    active_job: JobOut | None = None
    ownership_confirmed: bool = False
    stage_count: int = 0
    export_count: int = 0


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


# -- consent ----------------------------------------------------------------


class ConsentRequest(BaseModel):
    consent_type: Literal[
        "ownership_confirmation",
        "authorized_use_policy",
        "protected_region_attestation",
        "timelapse_disclosure",
    ]
    confirmed: bool = Field(..., description="Must be true.")
    statement: str | None = Field(None, max_length=500)
    context: dict[str, Any] | None = None

    @field_validator("confirmed")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Confirmation is required.")
        return value

    @field_validator("consent_type")
    @classmethod
    def _known_consent(cls, value: str) -> str:
        if value not in CONSENT_TYPES:
            raise ValueError(f"consent_type must be one of {CONSENT_TYPES}")
        return value


class ConsentOut(ORMModel):
    id: str
    consent_type: str
    policy_version: str
    statement: str
    confirmed_at: dt.datetime
    project_id: str | None = None


# -- assets / uploads -------------------------------------------------------


class UploadInitRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., max_length=128)
    byte_size: int = Field(..., gt=0)
    asset_type: Literal["source", "intermediate", "line_art", "audio", "brand"] = "source"

    @field_validator("asset_type")
    @classmethod
    def _known_asset(cls, value: str) -> str:
        if value not in ASSET_TYPES:
            raise ValueError(f"asset_type must be one of {ASSET_TYPES}")
        return value


class UploadInitOut(BaseModel):
    asset_id: str
    storage_key: str
    upload: dict[str, Any] = Field(
        ..., description="Signed upload descriptor: url, method, headers, expires_in."
    )
    max_bytes: int
    retention_days: int
    retention_notice: str


class UploadCompleteRequest(BaseModel):
    asset_id: str
    ownership_confirmed: bool = Field(
        ...,
        description=(
            "Must be true. Records the attestation: "
            f'"{OWNERSHIP_STATEMENT}" Processing is refused without it.'
        ),
    )

    @field_validator("ownership_confirmed")
    @classmethod
    def _must_confirm(cls, value: bool) -> bool:
        if not value:
            raise ValueError(OWNERSHIP_STATEMENT)
        return value


class AssetOut(ORMModel):
    id: str
    type: str
    mime_type: str
    width: int | None
    height: int | None
    byte_size: int
    order_index: int
    upload_complete: bool
    created_at: dt.datetime
    metadata: dict[str, Any] = Field(default_factory=dict, alias="asset_metadata")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AssetWithUrlOut(AssetOut):
    download_url: str | None = None
    expires_in: int | None = None


class AssetAnalysisOut(BaseModel):
    """What the upload panel shows before the user commits to processing."""

    width: int
    height: int
    color_mode: str
    has_alpha: bool
    megapixels: float
    mime_type: str
    byte_size: int
    estimated_output_bytes: int
    orientation_corrected: bool
    provenance: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


# -- masks ------------------------------------------------------------------


class MaskCreateRequest(BaseModel):
    editor_state: dict[str, Any] = Field(
        ..., description="Declarative mask document: regions plus adjustments."
    )
    mask_png_base64: str | None = Field(
        None,
        description=(
            "Optional client rasterisation, stored for reference. The server "
            "re-rasterises from editor_state, which is what processing uses."
        ),
    )


class MaskOut(ORMModel):
    id: str
    version: int
    editor_state: dict[str, Any]
    created_at: dt.datetime


class MaskPreviewOut(BaseModel):
    version: int
    coverage: float
    region_count: int
    regions: list[dict[str, Any]]
    protection: dict[str, Any]
    suggested_mode: str
    analysis: dict[str, Any]


class DetectOverlaysRequest(BaseModel):
    asset_id: str | None = None
    limit: int = Field(20, ge=1, le=50)


class DetectOverlaysOut(BaseModel):
    candidates: list[dict[str, Any]]
    protected_regions: list[dict[str, Any]]
    notice: str


class SegmentRequest(BaseModel):
    asset_id: str | None = None
    mode: Literal["box", "point", "text"] = "box"
    box: list[int] | None = Field(None, min_length=4, max_length=4)
    point: list[int] | None = Field(None, min_length=2, max_length=2)


class SegmentOut(BaseModel):
    mask_png_base64: str
    method: str
    confidence: float
    selected_pixels: int


# -- jobs -------------------------------------------------------------------


class CleanupJobRequest(BaseModel):
    mask_version: int | None = Field(None, description="Defaults to the latest mask version.")
    mode: Literal["fast_fill", "texture_restore", "edge_aware", "art_mode"] = "fast_fill"
    apply_to_all_sources: bool = Field(
        False,
        description=(
            "Run the same mask against every completed source upload in the project. "
            "The mask scales to each image; protected-region checks run per image."
        ),
    )
    mask_approved: bool = Field(
        ..., description="Must be true. The user reviews and approves the mask before processing."
    )
    adjustments: dict[str, Any] | None = None
    grain_strength: float = Field(1.0, ge=0.0, le=2.0)
    edge_strength: float = Field(0.6, ge=0.0, le=2.0)
    colour_match: bool = True
    seed: int = Field(0, ge=0, le=2**31 - 1)
    acknowledged_protected_kinds: list[str] = Field(
        default_factory=list,
        description=(
            "Region kinds the user attests are not attribution content. Only clears "
            "review-severity findings; signatures and stock watermarks cannot be acknowledged."
        ),
    )
    idempotency_key: str | None = Field(None, max_length=128)

    @field_validator("mask_approved")
    @classmethod
    def _must_approve(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Approve the mask before processing.")
        return value


class JobOut(ORMModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress: float
    progress_message: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None
    error_code: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    completed_at: dt.datetime | None


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int


class JobProgressEvent(BaseModel):
    """One Server-Sent Event on the job progress stream."""

    job_id: str
    status: str
    progress: float
    message: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


# -- timelapse --------------------------------------------------------------


TimelapseMode = Literal[
    "sketch_to_colour",
    "paint_reveal",
    "layer_build",
    "hand_drawn_strokes",
    "real_intermediates",
]


class TimelapseAnalyzeRequest(BaseModel):
    asset_id: str | None = None
    mode: TimelapseMode = "sketch_to_colour"
    seed: int = Field(0, ge=0, le=2**31 - 1)
    idempotency_key: str | None = Field(None, max_length=128)


class StageIn(BaseModel):
    stage_type: str = Field(..., max_length=48)
    label: str = Field("", max_length=120)
    order_index: int = Field(..., ge=0)
    duration: float = Field(1.0, gt=0.0, le=300.0)
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class StageOut(ORMModel):
    id: str
    stage_type: str
    label: str
    order_index: int
    duration: float
    enabled: bool
    settings: dict[str, Any]


class StageListIn(BaseModel):
    stages: list[StageIn] = Field(..., max_length=64)


class StageListOut(BaseModel):
    items: list[StageOut]
    total_duration: float


class TimelapseRenderRequest(BaseModel):
    mode: TimelapseMode = "sketch_to_colour"
    duration_seconds: float = Field(12.0, ge=5.0, le=300.0)
    fps: Literal[24, 30, 60] = 30
    preset: Literal["square", "portrait_4x5", "vertical_9x16", "landscape_16x9", "source"] = (
        "square"
    )
    formats: list[Literal["mp4", "webm", "gif", "poster", "frames", "project_json", "svg"]] = Field(
        default_factory=lambda: ["mp4"]
    )
    seed: int = Field(0, ge=0, le=2**31 - 1)
    background_colour: str = Field("#F7F4EF", pattern=r"^#[0-9a-fA-F]{6}$")
    # Drawing speed: divides the timeline duration at render time, so 2.0
    # plays the same reconstruction in half the time.
    speed: float = Field(1.0, ge=0.25, le=4.0)
    stroke_speed: float = Field(1.0, ge=0.1, le=4.0)
    stroke_density: float = Field(1.0, ge=0.1, le=4.0)
    brush_size_min: int = Field(6, ge=1, le=256)
    brush_size_max: int = Field(48, ge=1, le=512)
    transition_curve: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "ease_in_out"
    hold_final_seconds: float = Field(2.5, ge=0.0, le=30.0)
    zoom_pan: bool = False
    show_cursor: bool = False
    brand_watermark_asset_id: str | None = None
    audio_asset_id: str | None = None
    audio_start_seconds: float = Field(0.0, ge=0.0)
    audio_volume: float = Field(0.8, ge=0.0, le=1.0)
    end_card_disclosure: bool = Field(
        True,
        description=(
            "Adds the visible end card 'Timelapse reconstructed from finished artwork.' "
            "Enabled by default. The metadata disclosure is written regardless."
        ),
    )
    gif_fps: int = Field(12, ge=4, le=30, description="Frame rate of the GIF preview.")
    gif_max_width: int = Field(
        480, ge=120, le=1080, description="Longest edge of the GIF preview, in pixels."
    )
    preview: bool = Field(False, description="Render a fast low-resolution preview.")
    idempotency_key: str | None = Field(None, max_length=128)

    @field_validator("brush_size_max")
    @classmethod
    def _max_above_min(cls, value: int, info) -> int:
        minimum = info.data.get("brush_size_min", 1)
        if value < minimum:
            raise ValueError("brush_size_max must be greater than or equal to brush_size_min.")
        return value


# -- exports ----------------------------------------------------------------


class ExportRequest(BaseModel):
    format: Literal["png", "jpeg", "webp", "tiff"] = "png"
    quality: int = Field(95, ge=1, le=100)

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        if value not in EXPORT_FORMATS:
            raise ValueError(f"format must be one of {EXPORT_FORMATS}")
        return value


class ExportOut(ORMModel):
    id: str
    format: str
    byte_size: int
    settings: dict[str, Any]
    disclosure_metadata: dict[str, Any]
    created_at: dt.datetime


class ExportWithUrlOut(ExportOut):
    #: Populated by the route after the record is validated from the ORM row.
    download_url: str = ""
    expires_in: int = 0


class ExportListOut(BaseModel):
    items: list[ExportOut]
    total: int


# -- system -----------------------------------------------------------------


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessOut(BaseModel):
    status: str
    checks: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class PolicyOut(BaseModel):
    authorized_use_policy_version: str
    privacy_policy_version: str
    terms_version: str
    ownership_statement: str
    retention_options: list[int]
    max_upload_bytes: int
    allowed_mime_types: list[str]
    cleanup_modes: list[str]
    timelapse_modes: list[str]
    reconstruction_disclosure: str


ProjectDetailOut.model_rebuild()
