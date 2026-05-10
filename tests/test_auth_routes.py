"""Integration tests for auth routes (app/auth/routes.py).

These are route-layer tests: the Flask test client is used end-to-end, but
the auth service functions are mocked — route tests verify HTTP mechanics
(status codes, redirects, session writes, CSRF enforcement), not Supabase
behaviour.  Mocking is appropriate here because the service tests in
test_auth_service.py already cover the real Supabase integration.

Routes under test:
  GET  /auth/login
  POST /auth/login
  GET  /auth/logout
  GET  /auth/signup
  POST /auth/signup
  GET  /auth/reset-password
  POST /auth/reset-password

CSRF note: the app fixture in conftest.py sets WTF_CSRF_ENABLED=False for the
main test client.  The CSRF tests in this file use a separate client with
CSRF enabled so they can assert the 400 response.

Security note: auth surface — human review required before public launch
(architecture.md cross-cutting concerns).
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUTH_SERVICE_PATH = "app.auth.services"

VALID_EMAIL = "user@example.com"
VALID_PASSWORD = "S3cur3P@ssw0rd!"


@pytest.fixture
def csrf_app():
    """App instance with CSRF enabled, used for CSRF-rejection tests."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    return app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


# ---------------------------------------------------------------------------
# GET /auth/login
# ---------------------------------------------------------------------------

class TestGetLogin:
    def test_login_page_returns_200(self, client):
        """The login page must be publicly accessible and return HTTP 200."""
        response = client.get("/auth/login")
        assert response.status_code == 200

    def test_login_page_renders_form(self, client):
        """The login page must contain an HTML form — the user must be able
        to submit credentials."""
        response = client.get("/auth/login")
        assert b"<form" in response.data


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

class TestPostLogin:
    def test_valid_credentials_sets_session_and_redirects(self, client, mock_auth_session):
        """Successful login must write user_id to the session and redirect to /."""
        with patch(f"{AUTH_SERVICE_PATH}.sign_in", return_value=mock_auth_session):
            response = client.post(
                "/auth/login",
                data={"email": VALID_EMAIL, "password": VALID_PASSWORD},
                follow_redirects=False,
            )

        assert response.status_code in (302, 301)
        assert response.headers.get("Location", "").endswith("/") or \
               response.headers.get("Location", "") == "/"

        with client.session_transaction() as sess:
            assert sess.get("user_id") == mock_auth_session.user.id

    def test_invalid_credentials_returns_200_no_session(self, client):
        """Wrong credentials must re-render the login form (200) and must NOT
        write a user_id into the session."""
        from app.auth.services import AuthError
        with patch(f"{AUTH_SERVICE_PATH}.sign_in", side_effect=AuthError("invalid")):
            response = client.post(
                "/auth/login",
                data={"email": VALID_EMAIL, "password": "wrong"},
                follow_redirects=False,
            )

        assert response.status_code == 200

        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_post_login_without_csrf_token_returns_400(self, csrf_client):
        """A POST to /auth/login without a valid CSRF token must be rejected
        with HTTP 400 (Flask-WTF enforcement per ADR-0006)."""
        response = csrf_client.post(
            "/auth/login",
            data={"email": VALID_EMAIL, "password": VALID_PASSWORD},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /auth/logout
# ---------------------------------------------------------------------------

class TestGetLogout:
    def test_logout_clears_session_and_redirects_to_login(self, authenticated_client):
        """Logout must clear the session (user_id gone) and redirect to /auth/login."""
        response = authenticated_client.get("/auth/logout", follow_redirects=False)

        assert response.status_code in (302, 301)
        assert "/auth/login" in response.headers.get("Location", "")

        with authenticated_client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_logout_works_without_active_session(self, client):
        """Logout of an already-unauthenticated client must not raise an error —
        it must redirect gracefully."""
        response = client.get("/auth/logout", follow_redirects=False)
        assert response.status_code in (302, 301)


# ---------------------------------------------------------------------------
# GET /auth/signup
# ---------------------------------------------------------------------------

class TestGetSignup:
    def test_signup_page_returns_200(self, client):
        """The sign-up page must be publicly accessible and return HTTP 200."""
        response = client.get("/auth/signup")
        assert response.status_code == 200

    def test_signup_page_renders_form(self, client):
        """The sign-up page must contain a form the user can submit."""
        response = client.get("/auth/signup")
        assert b"<form" in response.data


# ---------------------------------------------------------------------------
# POST /auth/signup
# ---------------------------------------------------------------------------

class TestPostSignup:
    def test_valid_signup_calls_sign_up_and_sign_in_sets_session_redirects(
        self, client, mock_auth_user, mock_auth_session
    ):
        """Successful signup must:
        1. Call sign_up (creates the Supabase user)
        2. Call sign_in (establishes the session)
        3. Write user_id to the session
        4. Redirect to /
        """
        with patch(f"{AUTH_SERVICE_PATH}.sign_up", return_value=mock_auth_user) as mock_up, \
             patch(f"{AUTH_SERVICE_PATH}.sign_in", return_value=mock_auth_session) as mock_in:
            response = client.post(
                "/auth/signup",
                data={
                    "email": VALID_EMAIL,
                    "password": VALID_PASSWORD,
                    "confirm_password": VALID_PASSWORD,
                },
                follow_redirects=False,
            )

        mock_up.assert_called_once()
        mock_in.assert_called_once()

        assert response.status_code in (302, 301)
        assert response.headers.get("Location", "").endswith("/") or \
               response.headers.get("Location", "") == "/"

        with client.session_transaction() as sess:
            assert sess.get("user_id") == mock_auth_session.user.id

    def test_post_signup_without_csrf_token_returns_400(self, csrf_client):
        """A POST to /auth/signup without a valid CSRF token must be rejected
        with HTTP 400 (Flask-WTF enforcement per ADR-0006)."""
        response = csrf_client.post(
            "/auth/signup",
            data={
                "email": VALID_EMAIL,
                "password": VALID_PASSWORD,
                "confirm_password": VALID_PASSWORD,
            },
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /auth/reset-password
# ---------------------------------------------------------------------------

class TestGetResetPassword:
    def test_reset_password_page_returns_200(self, client):
        """The password reset page must be publicly accessible and return 200."""
        response = client.get("/auth/reset-password")
        assert response.status_code == 200

    def test_reset_password_page_renders_form(self, client):
        """The password reset page must contain a form."""
        response = client.get("/auth/reset-password")
        assert b"<form" in response.data


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------

class TestPostResetPassword:
    def test_reset_password_calls_service_and_returns_200(self, client):
        """Posting a valid email to /auth/reset-password must call
        initiate_password_reset and return HTTP 200 with a confirmation
        message (silent — no enumeration of whether the email exists)."""
        with patch(
            f"{AUTH_SERVICE_PATH}.initiate_password_reset", return_value=None
        ) as mock_reset:
            response = client.post(
                "/auth/reset-password",
                data={"email": VALID_EMAIL},
                follow_redirects=False,
            )

        mock_reset.assert_called_once()
        assert response.status_code == 200

    def test_reset_password_confirmation_message_shown(self, client):
        """The response body must contain some indication that the reset email
        was dispatched — the user needs feedback even if the email is unknown."""
        with patch(f"{AUTH_SERVICE_PATH}.initiate_password_reset", return_value=None):
            response = client.post(
                "/auth/reset-password",
                data={"email": VALID_EMAIL},
            )

        # Accept any reasonable confirmation wording
        body_lower = response.data.lower()
        assert any(
            word in body_lower
            for word in (b"sent", b"check", b"email", b"reset", b"instruction")
        ), "Response must contain a user-visible confirmation message"
