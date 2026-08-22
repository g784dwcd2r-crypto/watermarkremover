/**
 * The API client.
 *
 * Requests always send cookies and, for unsafe methods, the double-submit CSRF
 * token read from the readable `ars_csrf` cookie. Errors come back in one
 * envelope, so every caller can switch on a stable `code` rather than parsing
 * a message.
 */

import type { ApiErrorBody } from "@artrestore/types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const CSRF_COOKIE = "ars_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** The signed-out case, which the UI handles by redirecting rather than showing an error. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /** The mask overlaps content that can be cleared with an explicit attestation. */
  get needsAcknowledgement(): boolean {
    return this.code === "protected_region_review";
  }

  /** The mask overlaps attribution content. There is no override for this. */
  get isProtected(): boolean {
    return this.code === "protected_region";
  }
}

export function readCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Absolute URLs (signed storage links) skip the API base and the CSRF header. */
  absolute?: boolean;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, absolute = false, headers, method = "GET", ...rest } = options;
  const url = absolute ? path : `${API_BASE_URL}${path}`;

  const requestHeaders = new Headers(headers);
  if (body !== undefined && !(body instanceof FormData)) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (!absolute && UNSAFE_METHODS.has(method.toUpperCase())) {
    const token = readCsrfToken();
    if (token) requestHeaders.set(CSRF_HEADER, token);
  }

  const response = await fetch(url, {
    ...rest,
    method,
    headers: requestHeaders,
    credentials: absolute ? "omit" : "include",
    body:
      body === undefined
        ? undefined
        : body instanceof FormData || typeof body === "string"
          ? (body as BodyInit)
          : JSON.stringify(body),
  });

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text();

  if (!response.ok) {
    const envelope = payload as ApiErrorBody | null;
    const error = envelope?.error;
    throw new ApiError(
      error?.code ?? "request_failed",
      error?.message ?? `Request failed with status ${response.status}.`,
      response.status,
      error?.details ?? {},
    );
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};

/**
 * Upload bytes straight to object storage using a signed descriptor.
 *
 * The bytes never pass through this application's server, and the signed URL is
 * used once and then discarded rather than stored anywhere.
 */
export async function uploadToSignedUrl(
  upload: { url: string; method: string; headers: Record<string, string> },
  file: Blob,
): Promise<void> {
  const response = await fetch(upload.url, {
    method: upload.method || "PUT",
    headers: upload.headers,
    body: file,
    credentials: "omit",
  });
  if (!response.ok) {
    throw new ApiError(
      "upload_failed",
      "The file could not be uploaded. Check your connection and try again.",
      response.status,
    );
  }
}
