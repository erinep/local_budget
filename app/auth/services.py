"""Local Postgres-backed authentication for Local Budget Parser.

The rest of the application depends on the dataclasses and functions in this
module, not on an external auth provider. User identity is stored in
``auth.users`` so existing per-user foreign keys and cascade deletion semantics
remain intact.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


SESSION_TTL = timedelta(hours=1)
RESET_TOKEN_TTL = timedelta(hours=1)


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


class AuthError(Exception):
    """Raised for any authentication failure.

    Messages may be surfaced to callers, so do not include emails, tokens, or
    other user-specific data.
    """


def _normalize_email(email: str) -> str:
    return " ".join((email or "").strip().lower().split())


def _new_session(user_id: str, email: str) -> AuthSession:
    return AuthSession(
        user=AuthUser(id=str(user_id), email=email),
        access_token=secrets.token_urlsafe(32),
        refresh_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + SESSION_TTL,
    )


def sign_up(email: str, password: str) -> AuthUser:
    """Create a local user account.

    The password is hashed with Werkzeug's default password hasher. Duplicate
    email addresses and invalid inputs raise AuthError.
    """
    email = _normalize_email(email)
    if not email or not password:
        raise AuthError("Sign-up failed.")

    from app.db import get_engine

    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                sa.text(
                    """
                    INSERT INTO auth.users (email, password_hash)
                    VALUES (:email, :password_hash)
                    RETURNING id, email
                    """
                ),
                {
                    "email": email,
                    "password_hash": generate_password_hash(password),
                },
            ).fetchone()
    except IntegrityError as exc:
        raise AuthError("Sign-up failed.") from exc
    except Exception as exc:
        raise AuthError("Sign-up failed.") from exc

    if row is None:
        raise AuthError("Sign-up failed: no user returned.")
    return AuthUser(id=str(row.id), email=row.email)


def sign_in(email: str, password: str) -> AuthSession:
    """Authenticate a local user with email and password."""
    email = _normalize_email(email)
    if not email or not password:
        raise AuthError("Sign-in failed.")

    from app.db import get_engine

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT id, email, password_hash
                    FROM auth.users
                    WHERE email = :email
                    """
                ),
                {"email": email},
            ).fetchone()
    except Exception as exc:
        raise AuthError("Sign-in failed.") from exc

    if row is None or not row.password_hash:
        raise AuthError("Sign-in failed.")
    if not check_password_hash(row.password_hash, password):
        raise AuthError("Sign-in failed.")

    return _new_session(str(row.id), row.email)


def sign_in_with_google(callback_url: str) -> str:
    """Google OAuth is not implemented for local auth."""
    raise AuthError("Google sign-in is unavailable.")


def exchange_oauth_code(auth_code: str) -> AuthSession:
    """OAuth callback exchange is unavailable without an OAuth provider."""
    raise AuthError("Google sign-in is unavailable.")


def sign_out(refresh_token: str) -> None:
    """Local sign-out is completed by deleting the stored refresh token."""
    return None


def refresh_session(refresh_token: str) -> AuthSession:
    """Exchange a stored refresh token for a new local session."""
    if not refresh_token:
        raise AuthError("Session refresh failed.")

    from app.db import get_engine

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT u.id, u.email
                    FROM public.user_sessions s
                    JOIN auth.users u ON u.id = s.user_id
                    WHERE s.refresh_token = :refresh_token
                      AND s.expires_at > now()
                    """
                ),
                {"refresh_token": refresh_token},
            ).fetchone()
    except Exception as exc:
        raise AuthError("Session refresh failed.") from exc

    if row is None:
        raise AuthError("Session refresh failed.")
    return _new_session(str(row.id), row.email)


def get_user_from_session(user_id: str) -> AuthUser | None:
    """Look up a user by local auth UUID."""
    from app.db import get_engine

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sa.text("SELECT id, email FROM auth.users WHERE id = :uid"),
                {"uid": user_id},
            ).fetchone()
    except Exception:
        return None

    if row is None:
        return None
    return AuthUser(id=str(row.id), email=row.email or "")


def store_refresh_token(user_id: str, refresh_token: str, expires_at: datetime) -> None:
    """Upsert a refresh token into user_sessions."""
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO public.user_sessions (user_id, refresh_token, expires_at)
                VALUES (:user_id, :refresh_token, :expires_at)
                ON CONFLICT (user_id) DO UPDATE
                    SET refresh_token = EXCLUDED.refresh_token,
                        expires_at    = EXCLUDED.expires_at,
                        last_used_at  = now()
                """
            ),
            {"user_id": user_id, "refresh_token": refresh_token, "expires_at": expires_at},
        )


def get_refresh_token(user_id: str) -> str | None:
    """Return the stored refresh token for a user, or None if not found."""
    from app.db import get_engine

    with get_engine().connect() as conn:
        row = conn.execute(
            sa.text("SELECT refresh_token FROM public.user_sessions WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
    return row[0] if row else None


def delete_refresh_token(user_id: str) -> None:
    """Remove the user_sessions row on logout."""
    from app.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            sa.text("DELETE FROM public.user_sessions WHERE user_id = :uid"),
            {"uid": user_id},
        )


def initiate_password_reset(email: str) -> None:
    """Create a local password-reset token when the address exists.

    This intentionally returns the same result for known and unknown addresses.
    Token delivery is an operational concern that needs a separate email
    provider decision before public use.
    """
    email = _normalize_email(email)
    if not email:
        return None

    from app.db import get_engine

    token_hash = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + RESET_TOKEN_TTL

    with get_engine().begin() as conn:
        row = conn.execute(
            sa.text("SELECT id FROM auth.users WHERE email = :email"),
            {"email": email},
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            sa.text(
                """
                INSERT INTO public.password_reset_tokens (token_hash, user_id, expires_at)
                VALUES (:token_hash, :user_id, :expires_at)
                """
            ),
            {"token_hash": token_hash, "user_id": str(row.id), "expires_at": expires_at},
        )
    return None


def verify_recovery_token(token_hash: str) -> AuthSession:
    """Exchange a local password-reset token for a short-lived session."""
    if not token_hash:
        raise AuthError("Recovery token verification failed.")

    from app.db import get_engine

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT u.id, u.email
                    FROM public.password_reset_tokens t
                    JOIN auth.users u ON u.id = t.user_id
                    WHERE t.token_hash = :token_hash
                      AND t.used_at IS NULL
                      AND t.expires_at > now()
                    """
                ),
                {"token_hash": token_hash},
            ).fetchone()
    except Exception as exc:
        raise AuthError("Recovery token verification failed.") from exc

    if row is None:
        raise AuthError("Recovery token verification failed.")

    session = _new_session(str(row.id), row.email)
    session.access_token = token_hash
    return session


def update_password(access_token: str, new_password: str) -> None:
    """Set a new password using a verified local recovery token."""
    if not access_token or not new_password:
        raise AuthError("Password update failed.")

    from app.db import get_engine

    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT user_id
                    FROM public.password_reset_tokens
                    WHERE token_hash = :token_hash
                      AND used_at IS NULL
                      AND expires_at > now()
                    """
                ),
                {"token_hash": access_token},
            ).fetchone()
            if row is None:
                raise AuthError("Password update failed.")

            conn.execute(
                sa.text(
                    """
                    UPDATE auth.users
                    SET password_hash = :password_hash,
                        updated_at = now()
                    WHERE id = :user_id
                    """
                ),
                {
                    "password_hash": generate_password_hash(new_password),
                    "user_id": str(row.user_id),
                },
            )
            conn.execute(
                sa.text(
                    """
                    UPDATE public.password_reset_tokens
                    SET used_at = now()
                    WHERE token_hash = :token_hash
                    """
                ),
                {"token_hash": access_token},
            )
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("Password update failed.") from exc
