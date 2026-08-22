import type { JobStatus, ProjectStatus } from "@artrestore/types";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function relativeDays(value: string | null | undefined): string {
  if (!value) return "-";
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return "-";
  const days = Math.round((target - Date.now()) / 86_400_000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  return formatter.format(days, "day");
}

export const PROJECT_STATUS_TONE: Record<ProjectStatus, "neutral" | "info" | "success" | "danger"> = {
  draft: "neutral",
  ready: "info",
  processing: "info",
  complete: "success",
  failed: "danger",
};

export const PROJECT_STATUS_LABEL: Record<ProjectStatus, string> = {
  draft: "Draft",
  ready: "Ready",
  processing: "Processing",
  complete: "Complete",
  failed: "Failed",
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Finished",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** A stable idempotency key so a double-click cannot queue the same job twice. */
export function newIdempotencyKey(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `${prefix}-${random}`.slice(0, 128);
}
