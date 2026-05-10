"""Integration tests for app/auth/services.py.

These tests call real Supabase — they require SUPABASE_URL and SUPABASE_KEY
environment variables pointing at a test Supabase project.  They are skipped
automatically when those variables are absent, so CI without a test Supabase
project does not fail on import.

Per ADR-0002: the Supabase client is NOT mocked here.  The purpose of these
tests is to verify real behaviour through the service boundary, which is what
gives the portability constraint meaning.  Tests that mock the Supabase client
would only confirm that Python can call a mock.

Security note: the auth surface is sensitive.  Any change to these tests
requires a human review before merging (see architecture.md — auth surface
section).
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

# Skip the entire module if the test Supabase project is not configured.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

pytestmark = pytest.mark.skipif(
    not (SUPABASE_URL and SUPABASE_KEY),
    reason="SUPABASE_URL and SUPABASE_KEY must be set to run auth service integration tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_email() -> str:
    """Generate a unique email address so tests do not collide with each other."""
    return f"testuser+{uuid.uuid4().hex[:8]}@example-test-domain.invalid"


VALID_PASSWORD = "S3cur3P@ssw0rd!"


# ---------------------------------------------------------------------------
# sign_up
# ---------------------------------------------------------------------------

class TestSignUp:
    def test_sign_up_valid_credentials_returns_auth_user(self):
        """Happy path: sign_up with a fresh email/password returns an AuthUser
        whose email matches the one supplied."""
        from app.auth.services import sign_up, AuthUser

        email = _unique_email()
        result = sign_up(email, VALID_PASSWORD)

        assert isinstance(result, AuthUser)
        assert result.email == email
        assert result.id  # non-empty string / UUID

    def test_sign_up_duplicate_email_raises_auth_error(self):
        """Duplicate registration must raise AuthError — the spec must not
        silently succeed or return a different user."""
        from app.auth.services import sign_up, AuthError

        email = _unique_email()
        sign_up(email, VALID_PASSWORD)  # first registration succeeds

        with pytest.raises(AuthError):
            sign_up(email, VALID_PASSWORD)  # second must fail


# ---------------------------------------------------------------------------
# sign_in
# ---------------------------------------------------------------------------

class TestSignIn:
    def test_sign_in_valid_credentials_returns_auth_session(self):
        """Happy path: sign_in with correct credentials returns an AuthSession
        with non-empty access and refresh tokens, and a UTC-aware expires_at."""
        from app.auth.services import sign_up, sign_in, AuthSession

        email = _unique_email()
        sign_up(email, VALID_PASSWORD)

        session = sign_in(email, VALID_PASSWORD)

        assert isinstance(session, AuthSession)
        assert session.access_token  # non-empty
        assert session.refresh_token  # non-empty
        assert session.user.email == email
        # expires_at must be UTC-aware (ADR-0001 and CLAUDE.md constraint)
        assert session.expires_at.tzinfo is not None
        assert session.expires_at.tzinfo == timezone.utc or (
            session.expires_at.utcoffset().total_seconds() == 0
        )

    def test_sign_in_wrong_password_raises_auth_error(self):
        """Wrong password must raise AuthError, not return a partial session."""
        from app.auth.services import sign_up, sign_in, AuthError

        email = _unique_email()
        sign_up(email, VALID_PASSWORD)

        with pytest.raises(AuthError):
            sign_in(email, "WrongPassword999!")

    def test_sign_in_unknown_email_raises_auth_error(self):
        """A completely unregistered email must raise AuthError — the service
        must not return a null session or swallow the error."""
        from app.auth.services import sign_in, AuthError

        with pytest.raises(AuthError):
            sign_in("nobody@never-registered.invalid", VALID_PASSWORD)


# ---------------------------------------------------------------------------
# get_user_from_session
# ---------------------------------------------------------------------------

class TestGetUserFromSession:
    def test_unknown_user_id_returns_none(self):
        """A random UUID with no corresponding Supabase user must return None,
        not raise an exception and not return an arbitrary user."""
        from app.auth.services import get_user_from_session

        random_id = str(uuid.uuid4())
        result = get_user_from_session(random_id)

        assert result is None


# ---------------------------------------------------------------------------
# initiate_password_reset
# ---------------------------------------------------------------------------

class TestInitiatePasswordReset:
    def test_unknown_email_does_not_raise(self):
        """Password reset for an email that was never registered must NOT raise
        any exception.  Raising would allow email enumeration — the spec
        explicitly requires silent behaviour for unknown addresses."""
        from app.auth.services import initiate_password_reset

        # Should complete without raising
        initiate_password_reset("no-such-user@example-test-domain.invalid")
