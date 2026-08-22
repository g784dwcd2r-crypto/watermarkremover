"""Probes, policy metadata, the OpenAPI document and log hygiene."""

from __future__ import annotations

from artrestore_api.logging_setup import scrub, truncate_key


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["version"]


def test_readyz_reports_backends(client):
    body = client.get("/readyz").json()
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["storage"]["ok"] is True
    assert "rate_limiter" in body["checks"]


def test_policies_endpoint_exposes_the_ownership_statement(client):
    body = client.get("/v1/policies").json()
    assert body["ownership_statement"] == "I own this image or have permission to edit it."
    assert body["retention_options"] == [1, 7, 30]
    assert set(body["cleanup_modes"]) == {
        "fast_fill",
        "texture_restore",
        "edge_aware",
        "art_mode",
    }
    assert body["reconstruction_disclosure"] == "AI-assisted reconstructed artwork timelapse"
    assert body["authorized_use_policy_version"]


def test_openapi_document_is_generated(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"]
    assert "/v1/projects" in spec["paths"]
    assert "/v1/projects/{project_id}/cleanup" in spec["paths"]
    # Endpoints carry summaries so the generated reference is usable.
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method in ("get", "post", "patch", "delete", "put"):
                assert operation.get("summary"), f"{method.upper()} {path} has no summary"


def test_security_headers_are_set(client):
    response = client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Request-Id"]


def test_unknown_route_returns_the_error_envelope(client):
    response = client.get("/v1/does-not-exist")
    assert response.status_code == 404


# -- log hygiene ------------------------------------------------------------


def test_signed_urls_are_scrubbed_from_logs():
    message = (
        "fetching https://storage.example.com/users/u1/file.png"
        "?expires=123&signature=abcdef0123456789"
    )
    cleaned = scrub(message)
    assert "abcdef0123456789" not in cleaned
    assert "redacted-signature" in cleaned


def test_amazon_signatures_are_scrubbed():
    message = "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=deadbeefcafe&X-Amz-Expires=300"
    assert "deadbeefcafe" not in scrub(message)


def test_email_addresses_are_scrubbed():
    assert "artist@example.com" not in scrub("login failed for artist@example.com")


def test_storage_keys_are_truncated():
    key = "users/abc-123/projects/def-456/source/secret-filename.png"
    truncated = truncate_key(key)
    assert "secret-filename" not in truncated
    assert truncated.startswith("users/abc-123/projects")


def test_production_safety_checks_flag_insecure_configuration(monkeypatch):
    from artrestore_api.config import Settings

    settings = Settings(
        environment="production",
        debug=True,
        cookie_secure=False,
        secret_key="dev-only-insecure-secret-key-change-me-please-0123456789",
        storage_backend="local",
    )
    problems = settings.check_production_safety()
    assert any("SECRET_KEY" in problem for problem in problems)
    assert any("COOKIE_SECURE" in problem for problem in problems)
    assert any("DEBUG" in problem for problem in problems)
    assert any("local" in problem for problem in problems)


def test_production_safety_checks_pass_for_a_sane_configuration():
    from artrestore_api.config import Settings

    settings = Settings(
        environment="production",
        debug=False,
        cookie_secure=True,
        secret_key="x" * 64,
        storage_backend="s3",
        s3_access_key_id="AKIAREAL",
        cookie_domain=".example.com",
    )
    assert settings.check_production_safety() == []


def test_production_safety_flags_a_missing_cookie_domain():
    from artrestore_api.config import Settings

    settings = Settings(
        environment="production",
        debug=False,
        cookie_secure=True,
        secret_key="x" * 64,
        storage_backend="s3",
        s3_access_key_id="AKIAREAL",
        cookie_domain=None,
    )
    problems = settings.check_production_safety()
    assert any("COOKIE_DOMAIN" in problem for problem in problems)

    settings_with_domain = Settings(
        environment="production",
        debug=False,
        cookie_secure=True,
        secret_key="x" * 64,
        storage_backend="s3",
        s3_access_key_id="AKIAREAL",
        cookie_domain=".example.com",
    )
    assert settings_with_domain.check_production_safety() == []
