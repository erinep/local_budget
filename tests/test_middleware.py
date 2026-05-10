"""Tests for app/middleware/auth.py.

The middleware contract (from the spec):
  - load_user() is a before_request hook that sets flask.g.user
  - login_required is a decorator that redirects to /auth/login when g.user is None

All timestamps are UTC-aware (ADR-0001).
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from flask import g, session


# ---------------------------------------------------------------------------
# load_user — sets g.user from session
# ---------------------------------------------------------------------------

class TestLoadUser:
    def test_sets_g_user_when_session_has_valid_user_id(self, app, mock_auth_user):
        """When flask.session contains a user_id and a future expires_at,
        load_user must construct g.user from session data (no DB call for
        non-expiring sessions)."""
        future_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        with app.test_request_context("/"):
            session["user_id"] = mock_auth_user.id
            session["email"] = mock_auth_user.email
            session["expires_at"] = future_expiry

            from app.middleware.auth import load_user
            load_user()

            assert g.user is not None
            assert g.user.id == mock_auth_user.id
            assert g.user.email == mock_auth_user.email

    def test_sets_g_user_to_none_when_no_user_id_in_session(self, app):
        """When flask.session has no user_id key, load_user must set g.user = None."""
        with app.test_request_context("/"):
            from app.middleware.auth import load_user
            load_user()
            assert g.user is None

    def test_sets_g_user_to_none_when_session_is_expired(self, app, mock_auth_user):
        """When flask.session["expires_at"] is in the past, load_user must
        treat the session as invalid and set g.user = None.
        Expired sessions must never grant access (ADR-0006)."""
        past_expiry = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        with app.test_request_context("/"):
            session["user_id"] = mock_auth_user.id
            session["email"] = mock_auth_user.email
            session["expires_at"] = past_expiry

            from app.middleware.auth import load_user
            load_user()

            assert g.user is None

    def test_sets_g_user_to_none_when_expires_at_is_missing(self, app, mock_auth_user):
        """A session with user_id but no expires_at is malformed and must be
        rejected — load_user must set g.user = None and clear the session."""
        with app.test_request_context("/"):
            session["user_id"] = mock_auth_user.id
            session["email"] = mock_auth_user.email
            # expires_at intentionally omitted

            from app.middleware.auth import load_user
            load_user()

            assert g.user is None


# ---------------------------------------------------------------------------
# login_required — decorator behaviour
# ---------------------------------------------------------------------------

class TestLoginRequired:
    def test_allows_request_when_g_user_is_set(self, app, mock_auth_user):
        """When g.user is not None, login_required must allow the request
        through and return the wrapped function's value unchanged."""
        from app.middleware.auth import login_required

        @login_required
        def protected_view():
            return "secret content", 200

        with app.test_request_context("/"):
            g.user = mock_auth_user
            result = protected_view()

        assert result == ("secret content", 200)

    def test_redirects_to_login_when_g_user_is_none(self, app):
        """When g.user is None, login_required must redirect to /auth/login.
        This is the core enforcement point for the session strategy (ADR-0006)."""
        from app.middleware.auth import login_required

        @login_required
        def protected_view():
            return "should not reach here", 200

        with app.test_request_context("/protected"):
            g.user = None
            response = protected_view()

        # The response may be a Flask Response object or a tuple; handle both.
        if hasattr(response, "status_code"):
            assert response.status_code in (302, 301)
            assert "/auth/login" in response.headers.get("Location", "")
        else:
            # Tuple form (body, status, headers) — unlikely but handle gracefully
            pytest.fail(
                f"Expected a redirect Response, got: {response!r}"
            )

    def test_preserves_return_value_when_user_is_authenticated(self, app, mock_auth_user):
        """login_required must be transparent to the return value when the
        user is authenticated — it must not wrap or alter the response."""
        from app.middleware.auth import login_required

        expected = {"data": [1, 2, 3]}, 200

        @login_required
        def json_view():
            return expected

        with app.test_request_context("/"):
            g.user = mock_auth_user
            result = json_view()

        assert result == expected


# ---------------------------------------------------------------------------
# Integration: login_required applied via Flask test client
# ---------------------------------------------------------------------------

class TestLoginRequiredViaClient:
    def test_unauthenticated_request_redirects(self, client):
        """End-to-end via test client: a route decorated with login_required
        must redirect an unauthenticated request to /auth/login."""
        # The root route is expected to be protected in Phase 1
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 301)
        assert b"/auth/login" in response.data or "/auth/login" in response.headers.get(
            "Location", ""
        )

    def test_authenticated_request_is_allowed(self, authenticated_client):
        """A client with a valid session must not be redirected to /auth/login
        when accessing a protected route."""
        response = authenticated_client.get("/", follow_redirects=False)
        # Should not redirect to login
        location = response.headers.get("Location", "")
        assert "/auth/login" not in location
