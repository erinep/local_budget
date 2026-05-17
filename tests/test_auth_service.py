"""Unit tests for app/auth/services.py.

These tests mock the Supabase client per ADR-0012. Mocking allows unit tests
to run in CI without Supabase credentials while preserving the portability
constraint from ADR-0002: the application code does not reference Supabase
directly; only the auth module integrates with it.

ADR-0012 explains why mocking is appropriate: unit tests should be fast,
reliable, and not depend on external services. Optional integration tests
against real Supabase can be written separately if needed before launch.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.auth.services import (
    AuthError,
    AuthSession,
    AuthUser,
    sign_up,
    sign_in,
    sign_in_with_google,
    exchange_oauth_code,
    sign_out,
    refresh_session,
    get_user_from_session,
    initiate_password_reset,
    verify_recovery_token,
    update_password,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_email() -> str:
    """Generate a unique email address so tests do not collide with each other."""
    return f"testuser+{uuid.uuid4().hex[:8]}@example-test-domain.invalid"


VALID_PASSWORD = "S3cur3P@ssw0rd!"


def _mock_user(email: str = "test@example.com", user_id: str = None):
    """Create a mock Supabase User object."""
    if user_id is None:
        user_id = str(uuid.uuid4())
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = email
    return mock_user


def _mock_session(user_email: str = "test@example.com", user_id: str = None):
    """Create a mock Supabase Session object."""
    if user_id is None:
        user_id = str(uuid.uuid4())

    mock_session = MagicMock()
    mock_session.access_token = "mock_access_token_" + uuid.uuid4().hex[:8]
    mock_session.refresh_token = "mock_refresh_token_" + uuid.uuid4().hex[:8]
    # Supabase returns expires_at as a Unix timestamp (seconds since epoch)
    mock_session.expires_at = int(datetime.now(UTC).timestamp()) + 3600

    return mock_session, _mock_user(user_email, user_id)


@pytest.fixture
def mock_client():
    """Mock Supabase client for all auth service tests."""
    with patch("app.auth.services._get_client") as mock_get_client:
        mock = MagicMock()
        mock_get_client.return_value = mock
        yield mock


# ---------------------------------------------------------------------------
# sign_up
# ---------------------------------------------------------------------------

class TestSignUp:
    def test_sign_up_valid_credentials_returns_auth_user(self, mock_client):
        """Happy path: sign_up with valid credentials returns an AuthUser."""
        email = _unique_email()
        user_id = str(uuid.uuid4())

        mock_response = MagicMock()
        mock_response.user = _mock_user(email, user_id)
        mock_client.auth.sign_up.return_value = mock_response

        result = sign_up(email, VALID_PASSWORD)

        assert isinstance(result, AuthUser)
        assert result.email == email
        assert result.id == user_id
        mock_client.auth.sign_up.assert_called_once_with(
            {"email": email, "password": VALID_PASSWORD}
        )

    def test_sign_up_duplicate_email_raises_auth_error(self, mock_client):
        """Duplicate registration must raise AuthError."""
        email = _unique_email()

        # First call succeeds
        mock_response = MagicMock()
        mock_response.user = _mock_user(email)
        mock_client.auth.sign_up.return_value = mock_response

        sign_up(email, VALID_PASSWORD)

        # Second call raises (Supabase returns an error)
        mock_client.auth.sign_up.side_effect = Exception("User already exists")

        with pytest.raises(AuthError):
            sign_up(email, VALID_PASSWORD)

    def test_sign_up_no_user_returned_raises_auth_error(self, mock_client):
        """If Supabase returns no user, raise AuthError."""
        email = _unique_email()

        mock_response = MagicMock()
        mock_response.user = None
        mock_client.auth.sign_up.return_value = mock_response

        with pytest.raises(AuthError, match="no user returned"):
            sign_up(email, VALID_PASSWORD)


# ---------------------------------------------------------------------------
# sign_in
# ---------------------------------------------------------------------------

class TestSignIn:
    def test_sign_in_valid_credentials_returns_auth_session(self, mock_client):
        """Happy path: sign_in with correct credentials returns an AuthSession."""
        email = _unique_email()
        user_id = str(uuid.uuid4())

        mock_session, mock_user = _mock_session(email, user_id)
        mock_response = MagicMock()
        mock_response.session = mock_session
        mock_response.user = mock_user
        mock_client.auth.sign_in_with_password.return_value = mock_response

        session = sign_in(email, VALID_PASSWORD)

        assert isinstance(session, AuthSession)
        assert session.access_token == mock_session.access_token
        assert session.refresh_token == mock_session.refresh_token
        assert session.user.email == email
        assert session.user.id == user_id
        # expires_at must be UTC-aware (ADR-0001 constraint)
        assert session.expires_at.tzinfo is not None
        assert session.expires_at.tzinfo == UTC or (
            session.expires_at.utcoffset().total_seconds() == 0
        )

    def test_sign_in_wrong_password_raises_auth_error(self, mock_client):
        """Wrong password must raise AuthError."""
        email = _unique_email()

        mock_client.auth.sign_in_with_password.side_effect = Exception(
            "Invalid login credentials"
        )

        with pytest.raises(AuthError):
            sign_in(email, "WrongPassword999!")

    def test_sign_in_unknown_email_raises_auth_error(self, mock_client):
        """Unknown email must raise AuthError."""
        mock_client.auth.sign_in_with_password.side_effect = Exception(
            "User not found"
        )

        with pytest.raises(AuthError):
            sign_in("nobody@never-registered.invalid", VALID_PASSWORD)

    def test_sign_in_no_session_returned_raises_auth_error(self, mock_client):
        """If Supabase returns no session, raise AuthError."""
        email = _unique_email()

        mock_response = MagicMock()
        mock_response.session = None
        mock_response.user = _mock_user(email)
        mock_client.auth.sign_in_with_password.return_value = mock_response

        with pytest.raises(AuthError, match="no session returned"):
            sign_in(email, VALID_PASSWORD)


# ---------------------------------------------------------------------------
# sign_in_with_google
# ---------------------------------------------------------------------------

class TestSignInWithGoogle:
    def test_sign_in_with_google_returns_redirect_url(self, mock_client):
        """sign_in_with_google returns the OAuth redirect URL."""
        callback_url = "http://localhost:5000/auth/callback"
        redirect_url = "https://accounts.google.com/o/oauth2/v2/auth?..."

        mock_response = MagicMock()
        mock_response.url = redirect_url
        mock_client.auth.sign_in_with_oauth.return_value = mock_response

        result = sign_in_with_google(callback_url)

        assert result == redirect_url
        mock_client.auth.sign_in_with_oauth.assert_called_once_with({
            "provider": "google",
            "options": {"redirect_to": callback_url},
        })


# ---------------------------------------------------------------------------
# exchange_oauth_code
# ---------------------------------------------------------------------------

class TestExchangeOAuthCode:
    def test_exchange_oauth_code_returns_auth_session(self, mock_client):
        """exchange_oauth_code with valid code returns an AuthSession."""
        email = _unique_email()
        user_id = str(uuid.uuid4())
        auth_code = "auth_code_" + uuid.uuid4().hex[:16]

        mock_session, mock_user = _mock_session(email, user_id)
        mock_response = MagicMock()
        mock_response.session = mock_session
        mock_response.user = mock_user
        mock_client.auth.exchange_code_for_session.return_value = mock_response

        result = exchange_oauth_code(auth_code)

        assert isinstance(result, AuthSession)
        assert result.user.email == email
        assert result.access_token == mock_session.access_token

    def test_exchange_oauth_code_invalid_code_raises_auth_error(self, mock_client):
        """Invalid or expired code must raise AuthError."""
        mock_client.auth.exchange_code_for_session.side_effect = Exception(
            "Invalid code"
        )

        with pytest.raises(AuthError):
            exchange_oauth_code("invalid_code")


# ---------------------------------------------------------------------------
# sign_out
# ---------------------------------------------------------------------------

class TestSignOut:
    def test_sign_out_calls_client(self, mock_client):
        """sign_out calls the Supabase client's sign_out method."""
        refresh_token = "mock_refresh_token"

        sign_out(refresh_token)

        mock_client.auth.sign_out.assert_called_once()

    def test_sign_out_failure_does_not_raise(self, mock_client):
        """sign_out should not raise even if Supabase call fails."""
        refresh_token = "mock_refresh_token"
        mock_client.auth.sign_out.side_effect = Exception("Network error")

        # Should not raise
        sign_out(refresh_token)


# ---------------------------------------------------------------------------
# refresh_session
# ---------------------------------------------------------------------------

class TestRefreshSession:
    def test_refresh_session_valid_token_returns_auth_session(self, mock_client):
        """refresh_session with valid token returns a new AuthSession."""
        email = _unique_email()
        user_id = str(uuid.uuid4())
        refresh_token = "mock_refresh_token"

        mock_session, mock_user = _mock_session(email, user_id)
        mock_response = MagicMock()
        mock_response.session = mock_session
        mock_response.user = mock_user
        mock_client.auth.refresh_session.return_value = mock_response

        result = refresh_session(refresh_token)

        assert isinstance(result, AuthSession)
        assert result.user.email == email
        mock_client.auth.refresh_session.assert_called_once_with(refresh_token)

    def test_refresh_session_expired_token_raises_auth_error(self, mock_client):
        """Expired refresh token must raise AuthError."""
        refresh_token = "expired_token"
        mock_client.auth.refresh_session.side_effect = Exception("Token expired")

        with pytest.raises(AuthError):
            refresh_session(refresh_token)


# ---------------------------------------------------------------------------
# get_user_from_session
# ---------------------------------------------------------------------------

class TestGetUserFromSession:
    def test_get_user_from_session_valid_id_returns_auth_user(self, mock_client):
        """get_user_from_session with valid user ID returns AuthUser."""
        user_id = str(uuid.uuid4())
        email = _unique_email()

        mock_response = MagicMock()
        mock_response.user = _mock_user(email, user_id)
        mock_client.auth.get_user.return_value = mock_response

        result = get_user_from_session(user_id)

        assert isinstance(result, AuthUser)
        assert result.id == user_id
        assert result.email == email

    def test_get_user_from_session_id_mismatch_returns_none(self, mock_client):
        """If stored user_id doesn't match token subject, return None."""
        stored_user_id = str(uuid.uuid4())
        token_user_id = str(uuid.uuid4())  # Different ID

        mock_response = MagicMock()
        mock_response.user = _mock_user("test@example.com", token_user_id)
        mock_client.auth.get_user.return_value = mock_response

        result = get_user_from_session(stored_user_id)

        assert result is None

    def test_get_user_from_session_unknown_user_id_returns_none(self, mock_client):
        """Unknown user ID must return None, not raise."""
        random_id = str(uuid.uuid4())

        mock_response = MagicMock()
        mock_response.user = None
        mock_client.auth.get_user.return_value = mock_response

        result = get_user_from_session(random_id)

        assert result is None

    def test_get_user_from_session_exception_returns_none(self, mock_client):
        """Any exception should return None."""
        user_id = str(uuid.uuid4())
        mock_client.auth.get_user.side_effect = Exception("Network error")

        result = get_user_from_session(user_id)

        assert result is None


# ---------------------------------------------------------------------------
# initiate_password_reset
# ---------------------------------------------------------------------------

class TestInitiatePasswordReset:
    def test_initiate_password_reset_unknown_email_does_not_raise(self, mock_client):
        """Password reset for unknown email must NOT raise (prevents enumeration)."""
        # Mock should succeed silently (Supabase does not error on unknown emails)
        mock_client.auth.reset_password_email.return_value = None

        # Should not raise
        initiate_password_reset("no-such-user@example-test-domain.invalid")

        mock_client.auth.reset_password_email.assert_called_once()

    def test_initiate_password_reset_known_email_sends_email(self, mock_client):
        """initiate_password_reset sends email for registered address."""
        email = _unique_email()
        mock_client.auth.reset_password_email.return_value = None

        initiate_password_reset(email)

        mock_client.auth.reset_password_email.assert_called_once_with(email)


# ---------------------------------------------------------------------------
# verify_recovery_token
# ---------------------------------------------------------------------------

class TestVerifyRecoveryToken:
    def test_verify_recovery_token_valid_token_returns_auth_session(self, mock_client):
        """verify_recovery_token with valid token returns an AuthSession."""
        email = _unique_email()
        user_id = str(uuid.uuid4())
        token_hash = "mock_token_hash_" + uuid.uuid4().hex[:16]

        mock_session, mock_user = _mock_session(email, user_id)
        mock_response = MagicMock()
        mock_response.session = mock_session
        mock_response.user = mock_user
        mock_client.auth.verify_otp.return_value = mock_response

        result = verify_recovery_token(token_hash)

        assert isinstance(result, AuthSession)
        assert result.user.email == email
        mock_client.auth.verify_otp.assert_called_once_with({
            "token_hash": token_hash,
            "type": "recovery"
        })

    def test_verify_recovery_token_invalid_token_raises_auth_error(self, mock_client):
        """Invalid or expired token must raise AuthError."""
        mock_client.auth.verify_otp.side_effect = Exception("Invalid token")

        with pytest.raises(AuthError):
            verify_recovery_token("invalid_token_hash")


# ---------------------------------------------------------------------------
# update_password
# ---------------------------------------------------------------------------

class TestUpdatePassword:
    def test_update_password_valid_token_succeeds(self, mock_client):
        """update_password with valid token succeeds."""
        access_token = "mock_access_token_" + uuid.uuid4().hex[:16]
        new_password = "NewP@ssw0rd123!"
        user_id = str(uuid.uuid4())

        mock_response = MagicMock()
        mock_response.user = _mock_user("test@example.com", user_id)
        mock_client.auth.update_user.return_value = mock_response

        # Should not raise
        update_password(access_token, new_password)

        mock_client.auth.set_session.assert_called_once_with(access_token, "")
        mock_client.auth.update_user.assert_called_once_with({
            "password": new_password
        })

    def test_update_password_invalid_token_raises_auth_error(self, mock_client):
        """Invalid token must raise AuthError."""
        mock_client.auth.set_session.side_effect = Exception("Invalid token")

        with pytest.raises(AuthError):
            update_password("invalid_token", "NewP@ssw0rd123!")
