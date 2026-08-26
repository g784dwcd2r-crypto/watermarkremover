/**
 * The API contract, mirrored for the client.
 *
 * These types match the Pydantic schemas in `apps/api`. They are kept by hand
 * rather than generated so that the client can also carry the small amount of
 * shared vocabulary the UI needs (mode labels, editor state, protection
 * severities) in one place.
 */

// -- primitives -------------------------------------------------------------

export type ProjectType = "cleanup" | "timelapse";
export type ProjectStatus = "draft" | "ready" | "processing" | "complete" | "failed";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobType =
  "cleanup" | "timelapse_analyze" | "timelapse_preview" | "timelapse_render" | "export";
export type RetentionDays = 1 | 7 | 30;

export type CleanupMode = "fast_fill" | "texture_restore" | "edge_aware" | "art_mode";

export type TimelapseMode =
  "sketch_to_colour" | "paint_reveal" | "layer_build" | "hand_drawn_strokes" | "real_intermediates";

export type CanvasPresetKey =
  "square" | "portrait_4x5" | "vertical_9x16" | "landscape_16x9" | "source";

export type AssetType =
  | "source"
  | "source_preview"
  | "editor_preview"
  | "mask"
  | "processed"
  | "processed_preview"
  | "difference"
  | "intermediate"
  | "line_art"
  | "audio"
  | "brand"
  | "frame"
  | "poster"
  | "export";

/** Region kinds the product refuses to reconstruct over. */
export type ProtectedKind =
  "signature" | "copyright_notice" | "stock_watermark" | "agency_mark" | "provenance_label";

/**
 * `block` cannot be overridden. `review` pauses for an explicit attestation,
 * because some shapes (a corner date stamp, a patterned artwork) are genuinely
 * ambiguous without reading the content.
 */
export type ProtectionSeverity = "block" | "review";

// -- errors -----------------------------------------------------------------

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

// -- auth and account -------------------------------------------------------

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
  retention_preferences: { retention_days?: RetentionDays } & Record<string, unknown>;
}

export interface SessionResponse {
  user: User;
  csrf_token: string;
  expires_at: string;
}

export interface StorageUsage {
  total_bytes: number;
  limit_bytes: number;
  asset_count: number;
  project_count: number;
  export_bytes: number;
  by_project_type: Record<string, number>;
}

export interface ConsentRecord {
  id: string;
  consent_type: string;
  policy_version: string;
  statement: string;
  confirmed_at: string;
  project_id: string | null;
}

// -- projects and assets ----------------------------------------------------

export interface Project {
  id: string;
  name: string;
  project_type: ProjectType;
  status: ProjectStatus;
  settings: Record<string, unknown>;
  retention_days: number;
  delete_after: string | null;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  type: AssetType;
  mime_type: string;
  width: number | null;
  height: number | null;
  byte_size: number;
  order_index: number;
  upload_complete: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
  download_url?: string | null;
  expires_in?: number | null;
}

export interface ProjectDetail extends Project {
  assets: Asset[];
  latest_mask_version: number | null;
  active_job: Job | null;
  ownership_confirmed: boolean;
  stage_count: number;
  export_count: number;
}

export interface ProjectList {
  items: Project[];
  total: number;
  limit: number;
  offset: number;
}

export interface AssetAnalysis {
  width: number;
  height: number;
  color_mode: string;
  has_alpha: boolean;
  megapixels: number;
  mime_type: string;
  byte_size: number;
  estimated_output_bytes: number;
  orientation_corrected: boolean;
  provenance: {
    has_c2pa?: boolean;
    has_xmp_rights?: boolean;
    has_iptc?: boolean;
    exif_rights?: Record<string, string>;
    has_any?: boolean;
    notes?: string[];
  };
  warnings: string[];
}

export interface SignedUpload {
  url: string;
  method: string;
  headers: Record<string, string>;
  fields: Record<string, string>;
  storage_key: string;
  expires_in: number;
  max_bytes: number;
}

export interface UploadInit {
  asset_id: string;
  storage_key: string;
  upload: SignedUpload;
  max_bytes: number;
  retention_days: number;
  retention_notice: string;
}

// -- masks ------------------------------------------------------------------

export type MaskRegionKind = "brush" | "eraser" | "rect" | "polygon" | "lasso";

export interface MaskPoint {
  x: number;
  y: number;
}

export interface MaskRegion {
  id: string;
  type: MaskRegionKind;
  mode?: "add" | "subtract";
  points?: MaskPoint[];
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  size?: number;
  hardness?: number;
  opacity?: number;
}

export interface MaskAdjustments {
  expand: number;
  feather: number;
  blur: number;
}

/** The declarative document the editor saves and the server re-rasterises. */
export interface MaskEditorState {
  version: number;
  image: { width: number; height: number };
  regions: MaskRegion[];
  adjustments: MaskAdjustments;
}

export interface MaskVersion {
  id: string;
  version: number;
  editor_state: MaskEditorState;
  created_at: string;
}

export interface DetectedRegion {
  kind: ProtectedKind | "overlay_candidate";
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
  reason: string;
  severity?: ProtectionSeverity;
  evidence?: Record<string, unknown>;
}

export interface ProtectionOverlap {
  kind: ProtectedKind;
  severity: ProtectionSeverity;
  confidence: number;
  share_of_mask: number;
  share_of_region: number;
  acknowledged: boolean;
  reason: string;
}

export interface ProtectionAssessment {
  blocked: boolean;
  requires_acknowledgement: boolean;
  unacknowledged_kinds: ProtectedKind[];
  regions: DetectedRegion[];
  overlaps: ProtectionOverlap[];
  explanation: string;
}

export interface MaskPreview {
  version: number;
  coverage: number;
  region_count: number;
  regions: Array<Record<string, number | number[]>>;
  protection: ProtectionAssessment;
  suggested_mode: CleanupMode;
  analysis: Record<string, unknown>;
}

export interface OverlayDetection {
  candidates: DetectedRegion[];
  protected_regions: DetectedRegion[];
  notice: string;
}

export interface SegmentResult {
  mask_png_base64: string;
  method: string;
  confidence: number;
  selected_pixels: number;
}

// -- jobs -------------------------------------------------------------------

export interface Job {
  id: string;
  project_id: string;
  job_type: JobType;
  status: JobStatus;
  progress: number;
  progress_message: string;
  parameters: Record<string, unknown>;
  result: Record<string, unknown>;
  error_message: string | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobProgressEvent {
  job_id: string;
  status: JobStatus;
  progress: number;
  message: string;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
  error_message?: string | null;
}

// -- timelapse --------------------------------------------------------------

export interface TimelapseStage {
  id: string;
  stage_type: string;
  label: string;
  order_index: number;
  duration: number;
  enabled: boolean;
  settings: Record<string, unknown>;
}

export interface StageList {
  items: TimelapseStage[];
  total_duration: number;
}

export interface CanvasPreset {
  key: CanvasPresetKey;
  label: string;
  width: number;
  height: number;
  note: string;
}

export interface TimelapseOptions {
  modes: Array<{ key: TimelapseMode; label: string; requires_uploads: boolean }>;
  stage_types: Array<{ key: string; label: string }>;
  presets: CanvasPreset[];
  fps_options: number[];
  transition_curves: string[];
  duration_seconds: { min: number; max: number };
  speeds: Array<{ value: number; label: string }>;
  speed_range: { min: number; max: number };
  disclosure: {
    reconstruction_type: string;
    end_card_text: string;
    end_card_default: boolean;
    note: string;
  };
}

export interface TimelapseRenderRequest {
  mode: TimelapseMode;
  duration_seconds: number;
  fps: 24 | 30 | 60;
  preset: CanvasPresetKey;
  formats: Array<"mp4" | "webm" | "gif" | "poster" | "frames" | "project_json" | "svg">;
  seed: number;
  background_colour: string;
  speed: number;
  stroke_speed: number;
  stroke_density: number;
  brush_size_min: number;
  brush_size_max: number;
  transition_curve: string;
  hold_final_seconds: number;
  zoom_pan: boolean;
  show_cursor: boolean;
  brand_watermark_asset_id?: string | null;
  audio_asset_id?: string | null;
  audio_start_seconds: number;
  audio_volume: number;
  end_card_disclosure: boolean;
  gif_fps: number;
  gif_max_width: number;
  idempotency_key?: string | null;
}

// -- exports ----------------------------------------------------------------

export interface ExportRecord {
  id: string;
  format: string;
  byte_size: number;
  settings: Record<string, unknown>;
  disclosure_metadata: Record<string, unknown>;
  created_at: string;
  download_url?: string;
  expires_in?: number;
}

export interface ExportList {
  items: ExportRecord[];
  total: number;
}

// -- policy -----------------------------------------------------------------

export interface PolicyInfo {
  authorized_use_policy_version: string;
  privacy_policy_version: string;
  terms_version: string;
  ownership_statement: string;
  retention_options: number[];
  max_upload_bytes: number;
  allowed_mime_types: string[];
  cleanup_modes: CleanupMode[];
  timelapse_modes: TimelapseMode[];
  reconstruction_disclosure: string;
}

// -- shared vocabulary ------------------------------------------------------

export const CLEANUP_MODE_LABELS: Record<CleanupMode, string> = {
  fast_fill: "Fast Fill",
  texture_restore: "Texture Restore",
  edge_aware: "Edge-Aware Restore",
  art_mode: "Art Mode",
};

export const CLEANUP_MODE_DESCRIPTIONS: Record<CleanupMode, string> = {
  fast_fill: "Small marks on smooth or simple backgrounds. Fastest.",
  texture_restore: "Patterned or textured areas that need real texture, not a blur.",
  edge_aware: "Keeps lines, borders and object contours continuous through the repair.",
  art_mode: "Preserves brushwork, paper grain and illustration edges.",
};

export const TIMELAPSE_MODE_LABELS: Record<TimelapseMode, string> = {
  sketch_to_colour: "Sketch to Colour",
  paint_reveal: "Paint Reveal",
  layer_build: "Layer Build",
  hand_drawn_strokes: "Hand-Drawn Stroke Simulation",
  real_intermediates: "Real Intermediate Frames",
};

export const PROTECTED_KIND_LABELS: Record<ProtectedKind, string> = {
  signature: "artist signature",
  copyright_notice: "copyright or credit line",
  stock_watermark: "stock-provider watermark",
  agency_mark: "agency mark",
  provenance_label: "provenance or Content Credentials label",
};

export const OWNERSHIP_STATEMENT = "I own this image or have permission to edit it.";

export const RECONSTRUCTION_DISCLOSURE = "AI-assisted reconstructed artwork timelapse";

export const END_CARD_TEXT = "Timelapse reconstructed from finished artwork.";
