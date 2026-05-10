"""Authentication middleware for Local Budget Parser.

Provides:
- load_user(): before_request hook that hydrates flask.g.user from the session.
  Also performs silent session refresh when within 5 minutes of expiry.
- login_required: decorator that redirects to the login page if g.user is None.

ADR-0006: Cookie-based signed sessions (Flask built-in).
ADR-0001: All timestamps in UTC.
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import wraps

from flask import g, redirect, session, url_for

logger = logging.getLogger(__name__)

# Refresh the session when this many minutes remain before expiry.
_REFRESH_WINDOW_MINUTES = 5


def load_user() -> None:
    """Populate flask.g.user from the signed Flask session cookie.

    This function is registered as a before_request hook in the app factory.
    It reads ``session["user_id"]`` and ``session["expires_at"]`` (stored as
    an ISO-8601 UTC string) and populates ``g.user`` with an AuthUser instance,
    or sets it to None if no valid session exists.

    Silent refresh: if the session is within _REFRESH_WINDOW_MINUTES of expiry,
    this function calls auth_services.refresh_session and writes the updated
    tokens and expiry back to flask.session.
    """
    # Import here to avoid circular imports; auth.services is the Supabase
    # boundary and is only needed at request time.
    from app.auth.services import AuthError, AuthUser, get_refresh_token, refresh_session, store_refresh_token

    g.user = None

    user_id = session.get("user_id")
    if not user_id:
        return

    expires_at_str = session.get("expires_at")
    if not expires_at_str:
        # Malformed session — clear it.
        session.clear()
        return

    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        # Ensure the datetime is timezone-aware UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
    except ValueError:
        session.clear()
        return

    now = datetime.now(UTC)

    if now >= expires_at:
        # Session has already expired — clear it and remain unauthenticated.
        session.clear()
        return

    # Populate g.user from session data (no DB round-trip for most requests).
    g.user = AuthUser(
        id=user_id,
        email=session.get("email", ""),
    )

    # Silent refresh: if within the refresh window, exchange the refresh token.
    time_remaining = expires_at - now
    if time_remaining <= timedelta(minutes=_REFRESH_WINDOW_MINUTES):
        refresh_token = get_refresh_token(user_id)
        if refresh_token:
            try:
                new_session = refresh_session(refresh_token)
                session["expires_at"] = new_session.expires_at.isoformat()
                store_refresh_token(user_id, new_session.refresh_token, new_session.expires_at)
                g.user = new_session.user
            except AuthError:
                logger.warning("Silent session refresh failed; session will expire normally.")


def login_required(f):
    """Route decorator that enforces authentication.

    Redirects unauthenticated requests to the login page. Must be applied
    after the route decorator (i.e., closest to the function definition).

    Usage::

        @transactions_bp.route("/")
        @login_required
        def upload():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated
