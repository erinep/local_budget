import io
from datetime import UTC, datetime, timedelta

import pytest

from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    """Unauthenticated test client.

    Routes protected by @login_required will return 302 redirects with this
    client. Use ``auth_client`` for tests that need an authenticated session.
    """
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """Authenticated test client with a pre-populated Flask session.

    Injects a fake session so that load_user() populates g.user without
    hitting Supabase. The user_id and email are test fixtures only.

    Tests that exercise auth-protected routes (including the upload route)
    should use this fixture.
    """
    client = app.test_client()

    # Build a session cookie that load_user() will accept.
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    with client.session_transaction() as sess:
        sess["user_id"] = "00000000-0000-0000-0000-000000000001"
        sess["email"] = "test@example.invalid"
        sess["expires_at"] = expires_at.isoformat()
        sess["refresh_token"] = "test-refresh-token"

    return client


def make_csv(rows: list[dict]) -> io.BytesIO:
    """Build a minimal valid CSV as a file-like object."""
    lines = ["Transaction Date,Description 1,CAD$"]
    for row in rows:
        lines.append(f"{row['date']},{row['desc']},{row['amount']}")
    content = "\n".join(lines).encode("latin1")
    buf = io.BytesIO(content)
    buf.name = "transactions.csv"
    return buf
