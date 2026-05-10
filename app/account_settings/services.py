"""Account Settings service layer — category map persistence.

Owns the custom_categories table. The Transaction Engine reads category maps
exclusively through this interface; it never queries custom_categories directly
(ADR-0003).

ADR-0001: updated_at is always stored as a UTC timestamp.
ADR-0007: schema changes go through Alembic migrations, not raw DDL here.

Seeding logic:
  On first login, if no row exists for user_id, get_category_map falls back to:
  1. custom_categories.json at the repo root (if the file exists), then
  2. the generic map from app.config["GENERIC_CATEGORY_MAP"].
  This ensures a new user gets useful categorization immediately without any
  manual configuration.
"""

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)

# Path to the optional per-repo seed file.  The file is not required; if it is
# absent the generic map is used instead.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SEED_FILE = os.path.join(_REPO_ROOT, "custom_categories.json")


def get_category_map(user_id: str) -> dict[str, list[str]]:
    """Return the category map for user_id.

    Query order:
    1. custom_categories table row for user_id.
    2. Seed from custom_categories.json if the file exists (first login).
    3. Fall back to the generic map from app.config.

    When 2 or 3 is used, the result is persisted via save_category_map so that
    subsequent calls hit case 1 (no repeated file I/O or fallback logic).

    Returns a dict of {category: [keyword, ...]} — always a copy, never a
    reference to an internal cache.
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT category_map FROM public.custom_categories WHERE user_id = :uid"
            ),
            {"uid": user_id},
        ).fetchone()

    if row is not None:
        # Row found — return a copy of the stored map.
        return dict(row[0])

    # No row yet — determine the seed map.
    seed_map = _load_seed_map()

    # Persist so subsequent calls are fast.
    save_category_map(user_id, seed_map)

    return dict(seed_map)


def save_category_map(user_id: str, category_map: dict[str, list[str]]) -> None:
    """Upsert the category map for user_id.

    Sets updated_at to the current UTC timestamp on every write. The caller
    supplies the full map; partial updates are not supported — replace the
    whole map or read-modify-write at the route layer.

    ADR-0001: updated_at stored as UTC.
    """
    now_utc = datetime.now(UTC)
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO public.custom_categories (user_id, category_map, updated_at)
                VALUES (:uid, :map, :now)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    category_map = EXCLUDED.category_map,
                    updated_at   = EXCLUDED.updated_at
                """
            ),
            {"uid": user_id, "map": json.dumps(category_map), "now": now_utc},
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_seed_map() -> dict[str, list[str]]:
    """Return the seed category map for a new user.

    Prefers custom_categories.json at the repo root; falls back to the generic
    map from app.config. Returns an empty dict if neither is available (safe
    for tests that do not configure a map).
    """
    if os.path.exists(_SEED_FILE):
        try:
            with open(_SEED_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            logger.warning("custom_categories.json exists but could not be loaded; using generic map.")

    # Fall back to app.config["GENERIC_CATEGORY_MAP"] if we are inside a
    # Flask request context.
    try:
        from flask import current_app
        generic = current_app.config.get("GENERIC_CATEGORY_MAP", {})
        if generic:
            return dict(generic)
    except RuntimeError:
        # No application context (e.g., running outside Flask).
        pass

    return {}
