"""Auth blueprint routes.

Covers: login, logout, signup, password-reset.
All POST routes are CSRF-protected via Flask-WTF (ADR-0006).
Google OAuth is deferred to Phase 1.5 (ADR-0008).

Session shape written to flask.session on login:
    user_id      str   Supabase Auth UUID
    email        str   user's email address (stored for display only)
    expires_at   str   ISO-8601 UTC datetime string

The refresh_token is stored server-side in user_sessions (ADR-0006),
NOT in the cookie. Routes and middleware read it from the DB.

ADR-0001: all datetimes stored as UTC ISO-8601 strings in the session.
"""

import logging

from flask import Blueprint, g, redirect, render_template, request, session, url_for

from app.auth.services import (
    AuthError,
    delete_refresh_token,
    get_refresh_token,
    initiate_password_reset,
    sign_in,
    sign_out,
    sign_up,
    store_refresh_token,
)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Redirect already-authenticated users.
    if g.user is not None:
        return redirect(url_for("transactions.upload"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            auth_session = sign_in(email, password)
        except AuthError:
            # Do not include PII (email) in the log message — only the
            # generic event type.
            logger.warning("Login attempt failed.")
            return render_template("auth/login.html", error="Invalid email or password."), 401

        _write_session(auth_session)
        return redirect(url_for("transactions.upload"))

    return render_template("auth/login.html")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.route("/logout", methods=["GET"])
def logout():
    user_id = session.get("user_id")
    if user_id:
        refresh_token = get_refresh_token(user_id)
        if refresh_token:
            sign_out(refresh_token)
        delete_refresh_token(user_id)
    session.clear()
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None:
        return redirect(url_for("transactions.upload"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            sign_up(email, password)
            # sign_up creates the account; sign_in establishes a session.
            auth_session = sign_in(email, password)
        except AuthError:
            logger.warning("Signup attempt failed.")
            return render_template(
                "auth/signup.html",
                error="Could not create account. The email may already be registered.",
            ), 400

        _write_session(auth_session)
        return redirect(url_for("transactions.upload"))

    return render_template("auth/signup.html")


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        try:
            initiate_password_reset(email)
        except AuthError:
            # Log without PII; surface a generic error to the user.
            logger.warning("Password reset initiation failed.")
            return render_template(
                "auth/reset_password.html",
                error="Could not send reset email. Please try again later.",
            ), 500

        # Always show the same confirmation regardless of whether the address
        # is registered — prevents user enumeration.
        return render_template("auth/reset_password.html", success=True)

    return render_template("auth/reset_password.html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session(auth_session) -> None:
    """Write a Supabase AuthSession into flask.session.

    expires_at is stored as an ISO-8601 UTC string so it survives cookie
    serialisation without losing timezone information (ADR-0001).
    """
    session.clear()
    session["user_id"] = auth_session.user.id
    session["email"] = auth_session.user.email
    session["expires_at"] = auth_session.expires_at.isoformat()
    # Refresh token stored server-side only (ADR-0006).
    store_refresh_token(auth_session.user.id, auth_session.refresh_token, auth_session.expires_at)
