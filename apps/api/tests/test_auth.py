"""Authentication, session handling and CSRF."""

from __future__ import annotations


def test_register_creates_session_and_consent(api):
    assert api.user["email"] == "artist@example.com"
    session = api.client.cookies.get("ars_session")
    csrf = api.client.cookies.get("ars_csrf")
    assert session and csrf
    assert csrf == api.csrf_token

    consents = api.get("/v1/account/consents").json()
    kinds = {record["consent_type"] for record in consents}
    assert {"terms", "privacy", "authorized_use_policy"} <= kinds


def test_register_requires_policy_acceptance(client):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "nope@example.com",
            "password": "correct-horse-battery-staple",
            "accept_terms": False,
            "accept_authorized_use_policy": True,
        },
    )
    assert response.status_code == 422


def test_register_rejects_duplicate_email(api):
    response = api.client.post(
        "/v1/auth/register",
        json={
            "email": api.email,
            "password": "correct-horse-battery-staple",
            "accept_terms": True,
            "accept_authorized_use_policy": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_in_use"


def test_register_rejects_short_password(client):
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "short@example.com",
            "password": "short",
            "accept_terms": True,
            "accept_authorized_use_policy": True,
        },
    )
    assert response.status_code == 422


def test_login_and_logout(api):
    api.client.post("/v1/auth/logout", headers={"X-CSRF-Token": api.csrf_token})
    assert api.client.get("/v1/auth/session").status_code == 401

    assert api.login().status_code == 200
    assert api.client.get("/v1/auth/session").status_code == 200


def test_login_with_wrong_password_is_rejected(api):
    response = api.client.post(
        "/v1/auth/login", json={"email": api.email, "password": "wrong-password-value"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_login_for_unknown_email_gives_the_same_error(client):
    response = client.post(
        "/v1/auth/login", json={"email": "ghost@example.com", "password": "whatever-long-pass"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_session_cookie_is_http_only(api):
    response = api.client.post(
        "/v1/auth/login", json={"email": api.email, "password": api.password}
    )
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(item for item in set_cookie if item.startswith("ars_session="))
    csrf_cookie = next(item for item in set_cookie if item.startswith("ars_csrf="))
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie, "the SPA must be able to read the CSRF token"
    assert "SameSite=lax" in session_cookie.lower() or "samesite=lax" in session_cookie.lower()


def test_unsafe_request_without_csrf_header_is_rejected(api):
    response = api.client.post("/v1/projects", json={"name": "x", "project_type": "cleanup"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_unsafe_request_with_mismatched_csrf_is_rejected(api):
    response = api.client.post(
        "/v1/projects",
        json={"name": "x", "project_type": "cleanup"},
        headers={"X-CSRF-Token": "not-the-right-token"},
    )
    assert response.status_code == 403


def test_password_reset_round_trip(api):
    request = api.client.post("/v1/auth/password-reset", json={"email": api.email})
    assert request.status_code == 200
    token = request.json()["debug_token"]

    confirm = api.client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "password": "a-brand-new-long-password"},
    )
    assert confirm.status_code == 200

    # The old password no longer works, the new one does.
    assert (
        api.client.post(
            "/v1/auth/login", json={"email": api.email, "password": api.password}
        ).status_code
        == 401
    )
    assert (
        api.client.post(
            "/v1/auth/login", json={"email": api.email, "password": "a-brand-new-long-password"}
        ).status_code
        == 200
    )


def test_password_reset_token_is_single_use(api):
    token = api.client.post("/v1/auth/password-reset", json={"email": api.email}).json()[
        "debug_token"
    ]
    first = api.client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "password": "first-new-password-x"}
    )
    assert first.status_code == 200
    second = api.client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "password": "second-new-password-x"},
    )
    assert second.status_code == 422


def test_password_reset_does_not_reveal_account_existence(client):
    response = client.post("/v1/auth/password-reset", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert "debug_token" not in response.json()


def test_magic_link_sign_in(api):
    api.client.post("/v1/auth/logout", headers={"X-CSRF-Token": api.csrf_token})
    token = api.client.post("/v1/auth/magic-link", json={"email": api.email}).json()["debug_token"]
    response = api.client.post("/v1/auth/magic-link/confirm", json={"token": token})
    assert response.status_code == 200
    assert api.client.get("/v1/auth/session").status_code == 200


def test_revoke_all_sessions(api):
    assert api.post("/v1/auth/sessions/revoke-all").status_code == 204
    assert api.client.get("/v1/auth/session").status_code == 401


def test_forged_session_cookie_is_rejected(client):
    client.cookies.set("ars_session", "clearly-not-a-real-token")
    assert client.get("/v1/auth/session").status_code == 401
    client.cookies.clear()


def test_password_change_requires_the_current_password(api):
    response = api.post(
        "/v1/auth/password",
        json={"current_password": "wrong-password-here", "new_password": "a-new-long-password-x"},
    )
    assert response.status_code == 401


def test_password_change_rotates_the_credential_and_other_sessions(app, api):
    from fastapi.testclient import TestClient

    # A second signed-in session for the same account.
    other = TestClient(app)
    other.post("/v1/auth/login", json={"email": api.email, "password": api.password})
    assert other.get("/v1/auth/session").status_code == 200

    response = api.post(
        "/v1/auth/password",
        json={"current_password": api.password, "new_password": "a-brand-new-passphrase-1"},
    )
    assert response.status_code == 204

    # The session that made the change survives; the other one is revoked.
    assert api.get("/v1/auth/session").status_code == 200
    assert other.get("/v1/auth/session").status_code == 401
    other.close()

    # Old password dead, new one works.
    assert (
        api.client.post(
            "/v1/auth/login", json={"email": api.email, "password": api.password}
        ).status_code
        == 401
    )
    assert (
        api.client.post(
            "/v1/auth/login", json={"email": api.email, "password": "a-brand-new-passphrase-1"}
        ).status_code
        == 200
    )


def test_password_change_rejects_a_weak_replacement(api):
    response = api.post(
        "/v1/auth/password",
        json={"current_password": api.password, "new_password": "short"},
    )
    assert response.status_code == 422


def test_smtp_sender_is_selected_when_configured(api):
    """With an SMTP host set, tokens are no longer echoed through the API."""
    from artrestore_api.config import get_settings
    from artrestore_api.services import email as email_service

    settings = get_settings()
    sent: list = []

    class Recorder(email_service.SMTPEmailSender):
        def send(self, message):  # capture instead of opening a socket
            sent.append(message)

    original_host = settings.smtp_host
    try:
        settings.smtp_host = "mail.example.com"
        email_service.set_email_sender(None)  # rebuild from settings
        assert isinstance(email_service.get_email_sender(), email_service.SMTPEmailSender)

        email_service.set_email_sender(
            Recorder(host="mail.example.com", sender="noreply@example.com")
        )
        response = api.client.post("/v1/auth/password-reset", json={"email": api.email})
        assert response.status_code == 200
        assert "debug_token" not in response.json(), "SMTP deployments must not echo tokens"
        assert len(sent) == 1
        assert "reset" in sent[0].subject.lower() or "password" in sent[0].subject.lower()
        assert api.email == sent[0].to
    finally:
        settings.smtp_host = original_host
        email_service.set_email_sender(None)
