"""Tests for home blueprint routes (Phase 2 Amendment A, Ticket 3).

Contract source: ADR-0011 — Navigation and Landing Page Contract.

The dashboard at GET / is the post-login landing surface. It is auth-gated.
The brand link in every authenticated page targets home.index. The post-login
redirect in the auth routes (login, signup, oauth_callback) lands users on /,
not on /upload.

Tests here are route-level; they assert on URLs/endpoints, not on copy.
"""

from unittest.mock import patch

import pytest


AUTH_SERVICE_PATH = "app.auth.routes"

VALID_EMAIL = "user@example.com"
VALID_PASSWORD = "S3cur3P@ssw0rd!"


# ---------------------------------------------------------------------------
# GET / (dashboard)
# ---------------------------------------------------------------------------

class TestGetDashboard:
    def test_authenticated_returns_200(self, authenticated_client):
        """Authenticated GET / must render the dashboard with HTTP 200."""
        response = authenticated_client.get("/", follow_redirects=False)
        assert response.status_code == 200

    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated GET / must redirect to /auth/login.

        Matches the redirect pattern used by /upload and other login-gated
        routes (see test_routes.test_upload_page_redirects_unauthenticated).
        """
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_dashboard_links_to_upload(self, authenticated_client):
        """The dashboard must expose a link to the Upload page.

        Asserts on the endpoint URL, not on the copy (the user may rename
        the card; the URL is the contract).
        """
        response = authenticated_client.get("/")
        # transactions.upload route URL
        assert b"/upload" in response.data

    def test_dashboard_links_to_categories(self, authenticated_client):
        """The dashboard must expose a link to the Categories list page.

        Asserts on the endpoint URL, not on the card copy.
        """
        response = authenticated_client.get("/")
        assert b"/account-settings/categories" in response.data


# ---------------------------------------------------------------------------
# Brand link in base.html targets home.index (i.e. "/")
# ---------------------------------------------------------------------------

class TestBrandLinkTargetsHome:
    """ADR-0011 point 2: the brand link in the header always points at /.

    Asserted via an authenticated page (the dashboard) so the full header
    is rendered. The check is for an <a class="brand" href="/"> shape —
    not the literal endpoint name."""

    def test_brand_link_in_authenticated_page_targets_root(self, authenticated_client):
        """The brand link href must resolve to / (home.index), not /upload."""
        response = authenticated_client.get("/")
        body = response.data
        # The brand link should target "/" — the brand class anchor's href
        # must be exactly "/" (home.index). It must NOT point at the upload
        # route the way it did pre-Amendment A.
        assert b'class="brand"' in body
        assert b'href="/"' in body, (
            "Brand link must target / (home.index) per ADR-0011 point 2; "
            "if you see this fail, the brand link has drifted back to /upload."
        )

    def test_brand_link_does_not_target_upload(self, authenticated_client):
        """The brand link must NOT target /upload anymore (regression guard
        against Phase 0 default returning)."""
        response = authenticated_client.get("/")
        # Find the brand anchor block and assert it does not contain /upload.
        body = response.data.decode("utf-8")
        # Crude but contract-faithful: locate the brand class block and
        # ensure its href is not /upload.
        brand_idx = body.find('class="brand"')
        assert brand_idx >= 0
        # Look at the 200 chars around the brand anchor.
        window = body[max(0, brand_idx - 100): brand_idx + 200]
        assert 'href="/upload"' not in window


# ---------------------------------------------------------------------------
# Post-login redirect lands on / (not /upload)
# ---------------------------------------------------------------------------

class TestPostLoginRedirectsToDashboard:
    """ADR-0011 point 1 + Amendment A Ticket 3: the post-login redirect
    in the auth flow targets / (the dashboard), not /upload."""

    def test_login_success_redirects_to_root(self, client, mock_auth_session):
        """POST /auth/login with valid credentials must redirect to /."""
        with patch(f"{AUTH_SERVICE_PATH}.sign_in", return_value=mock_auth_session), \
             patch(f"{AUTH_SERVICE_PATH}.store_refresh_token"):
            response = client.post(
                "/auth/login",
                data={"email": VALID_EMAIL, "password": VALID_PASSWORD},
                follow_redirects=False,
            )
        assert response.status_code in (301, 302)
        location = response.headers.get("Location", "")
        assert location.endswith("/") and not location.endswith("/upload"), (
            f"Post-login redirect must target /, got {location!r}"
        )

    def test_signup_success_redirects_to_root(
        self, client, mock_auth_user, mock_auth_session
    ):
        """POST /auth/signup success must redirect to / (not /upload)."""
        with patch(f"{AUTH_SERVICE_PATH}.sign_up", return_value=mock_auth_user), \
             patch(f"{AUTH_SERVICE_PATH}.sign_in", return_value=mock_auth_session), \
             patch(f"{AUTH_SERVICE_PATH}.store_refresh_token"):
            response = client.post(
                "/auth/signup",
                data={
                    "email": VALID_EMAIL,
                    "password": VALID_PASSWORD,
                    "confirm_password": VALID_PASSWORD,
                },
                follow_redirects=False,
            )
        assert response.status_code in (301, 302)
        location = response.headers.get("Location", "")
        assert location.endswith("/") and not location.endswith("/upload"), (
            f"Post-signup redirect must target /, got {location!r}"
        )

    def test_oauth_callback_success_redirects_to_root(self, client, mock_auth_session):
        """GET /auth/callback with a valid code must redirect to / (not /upload)."""
        with patch(
            f"{AUTH_SERVICE_PATH}.exchange_oauth_code",
            return_value=mock_auth_session,
        ), patch(f"{AUTH_SERVICE_PATH}.store_refresh_token"):
            response = client.get(
                "/auth/callback?code=fake-oauth-code",
                follow_redirects=False,
            )
        assert response.status_code in (301, 302)
        location = response.headers.get("Location", "")
        assert location.endswith("/") and not location.endswith("/upload"), (
            f"OAuth post-login redirect must target /, got {location!r}"
        )
