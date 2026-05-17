"""Tests for the Flask application factory (app/__init__.py).

Contract sources:
  - Phase 2 Amendment A, Ticket 1 — purge CUSTOM_CATEGORY_MAP from the app
    factory. GENERIC_CATEGORY_MAP must remain loaded (feeds seed_defaults).
  - docs/phase2-contract.md §2.11 — generic seed map is still consumed.

These tests assert on app.config keys only; they do not exercise routes.
"""

from app import create_app


# ---------------------------------------------------------------------------
# Ticket 1 — CUSTOM_CATEGORY_MAP purge
# ---------------------------------------------------------------------------

class TestCustomCategoryMapPurged:
    """The legacy per-user custom-category file load must be gone.

    The Phase 2 contract states the import UI (POST /account-settings/import)
    is the only migration path for users with an existing custom file.
    Leaving the config key in place contradicts the contract and keeps dead
    code alive — Amendment A Ticket 1 explicitly removes it.
    """

    def test_custom_category_map_key_absent_after_app_creation(self):
        """create_app() must NOT set app.config['CUSTOM_CATEGORY_MAP'].

        Asserting on absence (not on a falsy value) — if the key exists
        at all, Ticket 1 has regressed.
        """
        app = create_app()
        assert "CUSTOM_CATEGORY_MAP" not in app.config, (
            "CUSTOM_CATEGORY_MAP was removed in Phase 2 Amendment A Ticket 1; "
            "if you see this failure, the legacy load has been reintroduced."
        )


# ---------------------------------------------------------------------------
# Ticket 1 — GENERIC_CATEGORY_MAP regression guard
# ---------------------------------------------------------------------------

class TestGenericCategoryMapStillLoaded:
    """Removing CUSTOM_CATEGORY_MAP must not break the generic seed load.

    GENERIC_CATEGORY_MAP is consumed by seed_defaults (Phase 2 contract §2.11)
    and by the upload-route fallback path. If Ticket 1 inadvertently removes
    this load too, new-user seeding silently breaks.
    """

    def test_generic_category_map_key_present(self):
        """app.config['GENERIC_CATEGORY_MAP'] must exist after create_app()."""
        app = create_app()
        assert "GENERIC_CATEGORY_MAP" in app.config

    def test_generic_category_map_is_dict(self):
        """The loaded map must be a dict (keyword: [merchant, ...] shape)."""
        app = create_app()
        assert isinstance(app.config["GENERIC_CATEGORY_MAP"], dict)

    def test_generic_category_map_is_non_empty(self):
        """The generic map ships with default categories on disk; a brand-new
        user relies on this to be seeded with categories on first login.

        An empty dict here is a regression: either generic_categories.json
        was deleted, moved, or _load_json silently returned {}.
        """
        app = create_app()
        assert len(app.config["GENERIC_CATEGORY_MAP"]) > 0, (
            "GENERIC_CATEGORY_MAP must be non-empty after create_app(); "
            "seed_defaults depends on it (docs/phase2-contract.md §2.11)."
        )
