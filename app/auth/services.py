"""Supabase Auth integration for Local Budget Parser.

ADR-0002: This is the ONLY file that imports or calls the Supabase client SDK.
No other file in the project may import supabase directly.

All timestamps are UTC (ADR-0001). datetime.now(UTC) is used everywhere;
datetime.utcnow() is banned.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from supabase import Client, create_client


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AuthUser:
    """Minimal user identity object passed through the session layer."""
    id: str
    email: str


@dataclass
class AuthSession:
    """Returned after a successful sign-in or session refresh."""
    user: AuthUser
    access_token: str
    refresh_token: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised for any Supabase Auth failure.

    The message is safe to surface to the caller but must not contain PII —
    do not interpolate email addresses or tokens into it.
    """


# ---------------------------------------------------------------------------
# Supabase client (module-level singleton, lazy-initialised)
# ---------------------------------------------------------------------------

_client: Client | None = None


def _get_client() -> Client:
    """Return a cached Supabase client, creating it on first call.

    Reads SUPABASE_URL and SUPABASE_ANON_KEY from the environment.
    Raises RuntimeError in test environments if these are not set; callers
    should mock this function in unit tests.
    """
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in the environment."
            )
        _client = create_client(url, key)
    return _client


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def sign_up(email: str, password: str) -> AuthUser:
    """Create a new user account via Supabase Auth.

    Returns AuthUser on success. Raises AuthError on any failure (duplicate
    email, weak password, etc.).

    Note: email is not logged — it is PII (architecture doc, cross-cutting /
    Security).
    """
    try:
        client = _get_client()
        response = client.auth.sign_up({"email": email, "password": password})
        if response.user is None:
            raise AuthError("Sign-up failed: no user returned.")
        return AuthUser(id=str(response.user.id), email=response.user.email)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Sign-up failed: {exc}") from exc


def sign_in(email: str, password: str) -> AuthSession:
    """Authenticate with email and password.

    Returns AuthSession containing tokens and expiry. Raises AuthError on
    invalid credentials or any other failure.
    """
    try:
        client = _get_client()
        response = client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if response.session is None or response.user is None:
            raise AuthError("Sign-in failed: no session returned.")

        session = response.session
        user = response.user

        # Supabase returns expires_at as a Unix timestamp (int).
        expires_at = datetime.fromtimestamp(session.expires_at, tz=UTC)

        return AuthSession(
            user=AuthUser(id=str(user.id), email=user.email),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_at=expires_at,
        )
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Sign-in failed: {exc}") from exc


def sign_out(refresh_token: str) -> None:
    """Invalidate a session via Supabase Auth.

    refresh_token is treated as a secret; it must not appear in logs.
    Failures are swallowed — the local Flask session is cleared regardless.
    """
    try:
        client = _get_client()
        client.auth.sign_out()
    except Exception:
        # Best-effort: local session will be cleared by the route handler even
        # if the Supabase call fails.
        pass


def refresh_session(refresh_token: str) -> AuthSession:
    """Exchange a refresh token for a new access token + refresh token pair.

    Called by the middleware when the session is within 5 minutes of expiry.
    Raises AuthError if the refresh token is expired or invalid.
    """
    try:
        client = _get_client()
        response = client.auth.refresh_session(refresh_token)
        if response.session is None or response.user is None:
            raise AuthError("Session refresh failed: no session returned.")

        session = response.session
        user = response.user
        expires_at = datetime.fromtimestamp(session.expires_at, tz=UTC)

        return AuthSession(
            user=AuthUser(id=str(user.id), email=user.email),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expires_at=expires_at,
        )
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Session refresh failed: {exc}") from exc


def get_user_from_session(user_id: str) -> AuthUser | None:
    """Look up a user by their Supabase Auth UUID.

    Returns AuthUser if found, None otherwise. Used by the middleware to
    rehydrate g.user without a full token exchange.
    """
    try:
        client = _get_client()
        response = client.auth.get_user()
        if response.user is None:
            return None
        # Confirm the stored user_id matches the token subject.
        if str(response.user.id) != user_id:
            return None
        return AuthUser(id=str(response.user.id), email=response.user.email)
    except Exception:
        return None


def store_refresh_token(user_id: str, refresh_token: str, expires_at: datetime) -> None:
    """Upsert a refresh token into user_sessions (ADR-0006: server-side storage)."""
    from app.db import get_engine
    with get_engine().begin() as conn:
        conn.execute(
            sa.text("""
                INSERT INTO user_sessions (user_id, refresh_token, expires_at)
                VALUES (:user_id, :refresh_token, :expires_at)
                ON CONFLICT (user_id) DO UPDATE
                    SET refresh_token = EXCLUDED.refresh_token,
                        expires_at    = EXCLUDED.expires_at,
                        last_used_at  = now()
            """),
            {"user_id": user_id, "refresh_token": refresh_token, "expires_at": expires_at},
        )


def get_refresh_token(user_id: str) -> str | None:
    """Return the stored refresh token for a user, or None if not found."""
    from app.db import get_engine
    with get_engine().connect() as conn:
        row = conn.execute(
            sa.text("SELECT refresh_token FROM user_sessions WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
    return row[0] if row else None


def delete_refresh_token(user_id: str) -> None:
    """Remove the user_sessions row on logout."""
    from app.db import get_engine
    with get_engine().begin() as conn:
        conn.execute(
            sa.text("DELETE FROM user_sessions WHERE user_id = :uid"),
            {"uid": user_id},
        )


def initiate_password_reset(email: str) -> None:
    """Send a password-reset email via Supabase Auth.

    Raises AuthError on failure. On success, Supabase sends an email to the
    address; we do not confirm whether the address is registered (prevents
    user enumeration).
    """
    try:
        client = _get_client()
        client.auth.reset_password_email(email)
    except Exception as exc:
        raise AuthError(f"Password reset failed: {exc}") from exc


def verify_recovery_token(token_hash: str) -> "AuthSession":
    """Exchange a password-reset token_hash for an active session.

    Raises AuthError if the token is invalid or expired.
    Uses supabase.auth.verify_otp with type='recovery'.
    Returns an AuthSession built from the response.

    The token_hash is a secret credential; it must not appear in logs.
    """
    try:
        client = _get_client()
        response = client.auth.verify_otp({"token_hash": token_hash, "type": "recovery"})
        if response.session is None or response.user is None:
            raise AuthError("Recovery token verification failed: no session returned.")

        sess = response.session
        user = response.user
        expires_at = datetime.fromtimestamp(sess.expires_at, tz=UTC)

        return AuthSession(
            user=AuthUser(id=str(user.id), email=user.email),
            access_token=sess.access_token,
            refresh_token=sess.refresh_token,
            expires_at=expires_at,
        )
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Recovery token verification failed: {exc}") from exc


def update_password(access_token: str, new_password: str) -> None:
    """Set a new password for the authenticated user.

    Uses supabase.auth.set_session to authenticate the client with the
    provided access_token, then calls update_user to set the new password.
    Raises AuthError on failure.

    The access_token is a secret credential; it must not appear in logs.
    """
    try:
        client = _get_client()
        # Authenticate the client with the recovery session's access token.
        # An empty string is passed for the refresh_token because we only
        # need the access_token to perform this single update operation.
        client.auth.set_session(access_token, "")
        response = client.auth.update_user({"password": new_password})
        if response.user is None:
            raise AuthError("Password update failed: no user returned.")
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Password update failed: {exc}") from exc
