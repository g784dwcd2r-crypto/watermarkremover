import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, apiFetch, readCsrfToken, uploadToSignedUrl } from "@/lib/api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("apiFetch", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends cookies with every request", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiFetch("/v1/policies");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "include" });
  });

  it("attaches the CSRF token to unsafe methods", async () => {
    document.cookie = "ars_csrf=token-value; path=/";
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await api.post("/v1/projects", { name: "x" });

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("token-value");
  });

  it("does not attach the CSRF token to safe methods", async () => {
    document.cookie = "ars_csrf=token-value; path=/";
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await api.get("/v1/projects");

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBeNull();
  });

  it("reads the CSRF cookie", () => {
    document.cookie = "ars_csrf=abc123; path=/";
    expect(readCsrfToken()).toBe("abc123");
  });

  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch("/v1/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("throws a typed ApiError carrying the server code", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "protected_region", message: "Blocked.", details: { overlaps: [] } } },
        422,
      ),
    );

    await expect(apiFetch("/v1/projects/1/cleanup", { method: "POST" })).rejects.toMatchObject({
      code: "protected_region",
      status: 422,
    });
  });

  it("flags an unauthorized response", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: "unauthorized", message: "Sign in.", details: {} } }, 401),
    );
    try {
      await apiFetch("/v1/projects");
      expect.unreachable("should have thrown");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).isUnauthorized).toBe(true);
    }
  });

  it("distinguishes a hard refusal from one that can be acknowledged", () => {
    expect(new ApiError("protected_region", "", 422).isProtected).toBe(true);
    expect(new ApiError("protected_region", "", 422).needsAcknowledgement).toBe(false);
    expect(new ApiError("protected_region_review", "", 409).needsAcknowledgement).toBe(true);
  });

  it("uploads to a signed URL without sending cookies", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
    await uploadToSignedUrl(
      { url: "https://storage.example/x?signature=abc", method: "PUT", headers: { "Content-Type": "image/png" } },
      new Blob(["data"]),
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: "omit", method: "PUT" });
  });

  it("reports a failed storage upload", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 403 }));
    await expect(
      uploadToSignedUrl({ url: "https://storage.example/x", method: "PUT", headers: {} }, new Blob()),
    ).rejects.toMatchObject({ code: "upload_failed" });
  });
});
