"""Application factory for Local Budget Parser.

ADR-0004 — Flask Blueprint Layout and Application Factory.
ADR-0005 — Category Map Dependency Injection.
ADR-0006 — Cookie-based signed sessions; CSRF via Flask-WTF.
"""

import json
import logging
import os
import re

from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


class PIIScrubber(logging.Filter):
    """Scrub PII from log records.

    Two-pass scrubbing:
    1. Named extra attributes (e.g. extra={"email": ...}) — exact-key match.
    2. Message string — regex patterns for emails and currency amounts.

    Limitation: free-form merchant/description strings are not regex-matchable.
    Callers must never log raw transaction descriptions or merchant names in
    the message string. Use structured logging with extra= and let pass 1
    catch it.

    Phase 0 foundation. Covers the cross-cutting PII-in-logs risk documented
    in docs/risks.md (rated P0+, High impact).
    """

    SENSITIVE_KEYS = ("description", "amount", "email")
    PATTERNS = [
        (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
        (re.compile(r"\$[\d,]+\.?\d*"), "[AMOUNT]"),
        (re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b"), "[AMOUNT]"),
    ]

    def filter(self, record):
        # Pass 1: named attributes
        for key in self.SENSITIVE_KEYS:
            if hasattr(record, key):
                setattr(record, key, "[REDACTED]")

        # Pass 2: message string
        try:
            msg = record.getMessage()
            for pattern, replacement in self.PATTERNS:
                msg = pattern.sub(replacement, msg)
            record.msg = msg
            record.args = ()  # already interpolated above
        except Exception:
            pass  # never let the scrubber break logging

        return True


def create_app(config=None):
    """Create and configure the Flask application.

    This is the single entry point for both the production server and the test
    suite. Pass a dict via `config` to override any app.config values — tests
    use this to inject controlled category maps without touching the filesystem.
    """
    from flask import Flask

    # template_folder and static_folder are relative to this file's directory
    # (app/), so "../templates" and "../static" resolve to the repo root.
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    # CSRF protection — required on all state-changing routes (architecture doc,
    # cross-cutting concerns). Production must set SECRET_KEY as an env variable.
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-key-change-in-prod"
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not app.debug  # True in prod, False on localhost
    csrf.init_app(app)

    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

    # Load the generic category map from disk. This feeds `seed_defaults` on
    # first login (docs/phase2-contract.md §2.11); per-user category data lives
    # in the database via the Account Settings service (ADR-0005).
    #
    # Per-user custom maps are no longer loaded from a JSON file. Users with an
    # existing `custom_categories.json` migrate via POST /account-settings/import.
    # See samples/custom_categories.example.json for the expected shape.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(base_dir)

    def _load_json(filename):
        path = os.path.join(repo_root, filename)
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return json.load(f)

    app.config["GENERIC_CATEGORY_MAP"] = _load_json("generic_categories.json")

    # Apply any caller-supplied overrides (e.g. test fixtures injecting
    # controlled category maps).
    if config:
        app.config.update(config)

    # Structured logging with PII scrubber (Phase 0 foundation).
    # Architecture doc (cross-cutting concerns / Observability) requires
    # structured logging from Phase 0 onward.
    try:
        from pythonjsonlogger.json import JsonFormatter as _JsonFormatter
    except ImportError:
        from pythonjsonlogger import jsonlogger as _jl
        _JsonFormatter = _jl.JsonFormatter
    handler = logging.StreamHandler()
    handler.addFilter(PIIScrubber())
    handler.setFormatter(_JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    # Sentry error tracking (Phase 1).
    # Only initialised when SENTRY_DSN is set so local dev without credentials
    # works without modification. send_default_pii=False is explicit: we never
    # want Sentry capturing user IPs, cookies, or request bodies.
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )

    # Register blueprints. ADR-0004.
    # auth_bp must be registered before transactions_bp so that the login
    # redirect (url_for("auth.login")) resolves when load_user() runs.
    from app.auth.routes import auth_bp
    app.register_blueprint(auth_bp)

    from app.home.routes import home_bp
    app.register_blueprint(home_bp)

    from app.account_settings.routes import account_settings_bp
    app.register_blueprint(account_settings_bp)

    from app.transactions.routes import transactions_bp
    app.register_blueprint(transactions_bp)

    # Register the authentication before_request hook.
    # ADR-0006: load_user populates flask.g.user from the signed session cookie.
    from app.middleware.auth import load_user
    app.before_request(load_user)

    return app
