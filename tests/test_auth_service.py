"""Unit tests for local Postgres-backed auth services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from app.auth.services import (
    AuthError,
    AuthSession,
    AuthUser,
    delete_refresh_token,
    get_refresh_token,
    get_user_from_session,
    initiate_password_reset,
    refresh_session,
    sign_in,
    sign_in_with_google,
    sign_out,
    sign_up,
    store_refresh_token,
    update_password,
    verify_recovery_token,
)


VALID_PASSWORD = "S3cur3P@ssw0rd!"


@pytest.fixture
def auth_engine(monkeypatch):
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _connection_record):
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS auth")
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS public")
        dbapi_connection.create_function("now", 0, lambda: "2000-01-01 00:00:00")

    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE auth.users (
                id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
                email TEXT UNIQUE,
                password_hash TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE public.user_sessions (
                id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
                user_id TEXT UNIQUE NOT NULL,
                refresh_token TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL,
                last_used_at TEXT
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE public.password_reset_tokens (
                id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
                user_id TEXT NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL,
                used_at TEXT
            )
        """))

    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    return engine


def _unique_email() -> str:
    return f"testuser+{uuid.uuid4().hex[:8]}@example.invalid"


class TestSignUp:
    def test_sign_up_valid_credentials_returns_auth_user(self, auth_engine):
        email = _unique_email()

        result = sign_up(email, VALID_PASSWORD)

        assert isinstance(result, AuthUser)
        assert result.email == email
        assert result.id

    def test_sign_up_normalizes_email(self, auth_engine):
        result = sign_up("  User@Example.Invalid  ", VALID_PASSWORD)

        assert result.email == "user@example.invalid"

    def test_sign_up_duplicate_email_raises_auth_error(self, auth_engine):
        email = _unique_email()
        sign_up(email, VALID_PASSWORD)

        with pytest.raises(AuthError):
            sign_up(email, VALID_PASSWORD)

    def test_sign_up_empty_input_raises_auth_error(self, auth_engine):
        with pytest.raises(AuthError):
            sign_up("", VALID_PASSWORD)


class TestSignIn:
    def test_sign_in_valid_credentials_returns_auth_session(self, auth_engine):
        email = _unique_email()
        user = sign_up(email, VALID_PASSWORD)

        session = sign_in(email, VALID_PASSWORD)

        assert isinstance(session, AuthSession)
        assert session.user == user
        assert session.access_token
        assert session.refresh_token
        assert session.expires_at.tzinfo is not None

    def test_sign_in_wrong_password_raises_auth_error(self, auth_engine):
        email = _unique_email()
        sign_up(email, VALID_PASSWORD)

        with pytest.raises(AuthError):
            sign_in(email, "WrongPassword999!")

    def test_sign_in_unknown_email_raises_auth_error(self, auth_engine):
        with pytest.raises(AuthError):
            sign_in("nobody@example.invalid", VALID_PASSWORD)


class TestOAuth:
    def test_google_oauth_is_unavailable(self, auth_engine):
        with pytest.raises(AuthError):
            sign_in_with_google("http://localhost/auth/callback")


class TestSessionStorage:
    def test_refresh_token_round_trip(self, auth_engine):
        user = sign_up(_unique_email(), VALID_PASSWORD)
        expires_at = datetime.now(UTC) + timedelta(hours=1)

        store_refresh_token(user.id, "refresh-token", expires_at)

        assert get_refresh_token(user.id) == "refresh-token"
        delete_refresh_token(user.id)
        assert get_refresh_token(user.id) is None

    def test_refresh_session_valid_token_returns_new_session(self, auth_engine):
        user = sign_up(_unique_email(), VALID_PASSWORD)
        store_refresh_token(user.id, "refresh-token", datetime.now(UTC) + timedelta(hours=1))

        session = refresh_session("refresh-token")

        assert isinstance(session, AuthSession)
        assert session.user == user
        assert session.refresh_token != "refresh-token"

    def test_refresh_session_invalid_token_raises_auth_error(self, auth_engine):
        with pytest.raises(AuthError):
            refresh_session("missing-token")

    def test_get_user_from_session_valid_id_returns_user(self, auth_engine):
        user = sign_up(_unique_email(), VALID_PASSWORD)

        assert get_user_from_session(user.id) == user

    def test_get_user_from_session_unknown_id_returns_none(self, auth_engine):
        assert get_user_from_session(str(uuid.uuid4())) is None

    def test_sign_out_does_not_raise(self, auth_engine):
        sign_out("refresh-token")


class TestPasswordReset:
    def test_initiate_password_reset_unknown_email_does_not_raise(self, auth_engine):
        initiate_password_reset("missing@example.invalid")

    def test_verify_recovery_token_and_update_password(self, auth_engine):
        email = _unique_email()
        sign_up(email, VALID_PASSWORD)
        initiate_password_reset(email)

        with auth_engine.connect() as conn:
            token = conn.execute(
                sa.text("SELECT token_hash FROM public.password_reset_tokens")
            ).scalar_one()

        reset_session = verify_recovery_token(token)
        assert reset_session.user.email == email

        update_password(reset_session.access_token, "NewP@ssw0rd123!")

        with pytest.raises(AuthError):
            verify_recovery_token(token)

        assert sign_in(email, "NewP@ssw0rd123!").user.email == email

    def test_verify_recovery_token_invalid_token_raises_auth_error(self, auth_engine):
        with pytest.raises(AuthError):
            verify_recovery_token("invalid-token")

    def test_update_password_invalid_token_raises_auth_error(self, auth_engine):
        with pytest.raises(AuthError):
            update_password("invalid-token", "NewP@ssw0rd123!")
