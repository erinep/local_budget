"""Application factory for Local Budget Parser.

ADR 0004 — Flask Blueprint Layout and Application Factory.
ADR 0005 — Category Map Dependency Injection.
"""

import json
import logging
import os


class PIIScrubber(logging.Filter):
    """Remove sensitive fields from log records before emission.

    Phase 0 foundation. Covers the cross-cutting PII-in-logs risk documented
    in docs/risks.md (rated P0+, High impact).
    """

    SENSITIVE = ("description", "amount", "email")

    def filter(self, record):
        for key in self.SENSITIVE:
            if hasattr(record, key):
                setattr(record, key, "[REDACTED]")
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

    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

    # Load category maps from JSON files. These are injected into the service
    # layer via app.config so they are never module-level globals (ADR 0005).
    # In Phase 1 this block is replaced by a per-user database read; the
    # make_categorizer call site in the route handler does not change.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(base_dir)

    def _load_json(filename):
        path = os.path.join(repo_root, filename)
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return json.load(f)

    app.config["CUSTOM_CATEGORY_MAP"] = _load_json("custom_categories.json")
    app.config["GENERIC_CATEGORY_MAP"] = _load_json("generic_categories.json")

    # Apply any caller-supplied overrides (e.g. test fixtures injecting
    # controlled category maps).
    if config:
        app.config.update(config)

    # Structured logging with PII scrubber (Phase 0 foundation).
    # Architecture doc (cross-cutting concerns / Observability) requires
    # structured logging from Phase 0 onward.
    handler = logging.StreamHandler()
    handler.addFilter(PIIScrubber())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    # Sentry integration point — no data flows yet; activated in Phase 1.
    # sentry_dsn = os.environ.get("SENTRY_DSN", None)
    # if sentry_dsn:
    #     import sentry_sdk
    #     sentry_sdk.init(dsn=sentry_dsn)

    # Register blueprints. ADR 0004: transactions_bp first because its URL
    # prefix is "/" and later blueprints use distinct prefixes.
    from app.transactions.routes import transactions_bp
    app.register_blueprint(transactions_bp)

    return app
