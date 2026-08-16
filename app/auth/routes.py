"""Auth blueprint routes.

Covers: login, logout, signup, password-reset.
All POST routes are CSRF-protected via Flask-WTF (ADR-0006).
Google OAuth is unavailable while the app uses local auth.

Session shape written to flask.session on login:
    user_id      str   local auth UUID
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
    exchange_oauth_code,
    get_refresh_token,
    initiate_password_reset,
    sign_in,
    sign_in_with_google,
    sign_out,
    sign_up,
    store_refresh_token,
    update_password,
    verify_recovery_token,
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
        return redirect(url_for("home.index"))

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
        return redirect(url_for("home.index"))

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
        return redirect(url_for("home.index"))

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
        return redirect(url_for("home.index"))

    return render_template("auth/signup.html")


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

@auth_bp.route("/google")
def google_login():
    """Redirect to Google OAuth when a provider is configured."""
    if g.user is not None:
        return redirect(url_for("home.index"))

    try:
        callback_url = url_for("auth.oauth_callback", _external=True)
        oauth_url = sign_in_with_google(callback_url)
    except AuthError:
        logger.warning("Google OAuth initiation failed.")
        return render_template("auth/login.html", error="Google sign-in is unavailable. Please try again."), 503

    return redirect(oauth_url)


@auth_bp.route("/callback")
def oauth_callback():
    """Handle an OAuth callback when a provider is configured."""
    error = request.args.get("error")
    if error:
        logger.warning("OAuth callback received an error from provider.")
        return render_template("auth/login.html", error="Google sign-in was cancelled or failed."), 400

    auth_code = request.args.get("code")
    if not auth_code:
        logger.warning("OAuth callback received no code parameter.")
        return render_template("auth/login.html", error="Google sign-in failed: no authorization code received."), 400

    try:
        auth_session = exchange_oauth_code(auth_code)
    except AuthError:
        logger.warning("OAuth code exchange failed.")
        return render_template("auth/login.html", error="Google sign-in failed. Please try again."), 401

    _write_session(auth_session)
    return redirect(url_for("home.index"))


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
# Update password (called from the password-reset email link)
# ---------------------------------------------------------------------------

@auth_bp.route("/update-password", methods=["GET", "POST"])
def update_password_view():
    """Handle a recovery link and allow the user to set a new password.

    GET:  The reset link sends ?token_hash=...&type=recovery. Verify the token,
          store the access_token in the session for the subsequent POST, and
          render the update-password form.
    POST: Read the new password from the form, use the stored reset token to
          call update_password, then redirect to /auth/login on success.
    """
    if request.method == "GET":
        token_hash = request.args.get("token_hash", "")
        token_type = request.args.get("type", "")

        if not token_hash or token_type != "recovery":
            return render_template(
                "auth/update_password.html",
                error="Reset link is invalid or has expired.",
            )

        try:
            auth_session = verify_recovery_token(token_hash)
        except AuthError:
            logger.warning("Password recovery token verification failed.")
            return render_template(
                "auth/update_password.html",
                error="Reset link is invalid or has expired.",
            )

        # Store the reset token so the POST handler can complete the password
        # update. This is short-lived and used only for this flow.
        session["reset_access_token"] = auth_session.access_token
        return render_template("auth/update_password.html")

    # POST
    new_password = request.form.get("new_password", "")
    access_token = session.get("reset_access_token")

    if not access_token:
        return redirect(url_for("auth.reset_password"))

    try:
        update_password(access_token, new_password)
    except AuthError:
        logger.warning("Password update failed.")
        return render_template(
            "auth/update_password.html",
            error="Could not update your password. Please request a new reset link.",
        )

    session.pop("reset_access_token", None)
    return redirect(url_for("auth.login", message="password_reset"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_session(auth_session) -> None:
    """Write an AuthSession into flask.session.

    expires_at is stored as an ISO-8601 UTC string so it survives cookie
    serialisation without losing timezone information (ADR-0001).
    """
    session.clear()
    session["user_id"] = auth_session.user.id
    session["email"] = auth_session.user.email
    session["expires_at"] = auth_session.expires_at.isoformat()
    try:
        store_refresh_token(auth_session.user.id, auth_session.refresh_token, auth_session.expires_at)
    except Exception:
        logger.warning("Could not persist refresh token; silent refresh will not be available.")
    # Idempotent seed: no-op when the user already has categories. Runs on every
    # login so pre-Phase-2 accounts (created before seed_defaults existed) get
    # back-filled on next sign-in without a separate migration.
    try:
        from app.account_settings.services import seed_defaults
        seed_defaults(auth_session.user.id)
    except Exception:
        logger.warning("Could not seed default categories; user may see an empty Categories UI until they import.")
