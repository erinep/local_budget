"""Account Settings routes.

Phase 1: no UI routes yet — the category-management UI ships in Phase 2.
This file exists to register the blueprint so the module is addressable in
url_for() and can be extended without touching the app factory.

ADR-0004: each module is a Flask blueprint.
"""

from flask import Blueprint

account_settings_bp = Blueprint(
    "account_settings", __name__, url_prefix="/account-settings"
)

# Phase 2 will add GET/POST routes for viewing and editing the category map.
