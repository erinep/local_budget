"""Account Settings service layer — category and keyword management.

Owns the public.categories and public.category_keywords tables introduced in
migration 0002. The Transaction Engine reads category maps exclusively through
this interface; it never queries the tables directly (ADR-0003).

ADR-0001: created_at columns are always UTC TIMESTAMPTZ (server default now()).
ADR-0007: schema changes go through Alembic migrations, never raw DDL here.
ADR-0009: normalized two-table relational schema replaces the JSONB blob.
ADR-0010: per-request g._category_cache keyed by user_id; invalidated on write.

Cache contract (ADR-0010):
  - Cache lives in flask.g._category_cache (dict[user_id, list[dict]]).
  - Read path: check cache before querying DB; store on miss.
  - Write path: pop user_id from cache after every committed mutation.
  - Outside a request context: fall through to direct DB query.
  - Cache shape: list[{"id": str, "name": str, "keywords": [str]}] —
    the output of list_categories(), which get_category_map() derives from
    without an additional DB hit.

Normalization rules:
  Category name : " ".join(name.strip().split())  — strip edges, collapse ws
  Keyword       : keyword.strip().upper()          — strip + upper-case

PII note: category names and keywords are user-defined configuration labels,
not raw transaction descriptions. Never log their values; use structured
logging with scrubbed keys only.
"""

import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import get_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache helpers (ADR-0010)
# ---------------------------------------------------------------------------

def _cache_get(user_id: str) -> "list[dict] | None":
    """Return cached category list for user_id, or None on miss / no context."""
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        cache = getattr(g, "_category_cache", None)
        if cache is None:
            return None
        return cache.get(user_id)
    except RuntimeError:
        return None


def _cache_set(user_id: str, categories: list) -> None:
    """Store categories in the per-request cache if a request context exists."""
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return
        if not hasattr(g, "_category_cache"):
            g._category_cache = {}
        g._category_cache[user_id] = categories
    except RuntimeError:
        pass


def _cache_invalidate(user_id: str) -> None:
    """Remove user_id from the per-request cache if present."""
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return
        cache = getattr(g, "_category_cache", None)
        if cache is not None:
            cache.pop(user_id, None)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    """Strip edges and collapse internal whitespace; preserve case."""
    return " ".join(name.strip().split())


def _norm_keyword(keyword: str) -> str:
    """Strip whitespace and upper-case."""
    return keyword.strip().upper()


# ---------------------------------------------------------------------------
# Ownership validation helpers
# ---------------------------------------------------------------------------

def _assert_category_owned(conn, user_id: str, category_id: str) -> None:
    """Raise ValueError("Category not found") if category_id doesn't belong to user."""
    row = conn.execute(
        text(
            "SELECT id FROM public.categories"
            " WHERE id = :cid AND user_id = :uid"
        ),
        {"cid": category_id, "uid": user_id},
    ).fetchone()
    if row is None:
        raise ValueError("Category not found")


def _assert_keyword_owned(conn, user_id: str, category_id: str, keyword_id: str) -> None:
    """Raise ValueError("Keyword not found") if keyword doesn't belong to category/user."""
    row = conn.execute(
        text(
            "SELECT ck.id FROM public.category_keywords ck"
            " JOIN public.categories c ON c.id = ck.category_id"
            " WHERE ck.id = :kid AND ck.category_id = :cid AND c.user_id = :uid"
        ),
        {"kid": keyword_id, "cid": category_id, "uid": user_id},
    ).fetchone()
    if row is None:
        raise ValueError("Keyword not found")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_categories(user_id: str) -> list:
    """Return all categories (with keywords) for user_id, ordered by name ASC.

    Result shape: [{"id": str, "name": str, "keywords": [str]}, ...]
    Keywords within each category are alphabetically sorted.
    Returns [] if the user has no categories.
    Cache-aware: returns a cached copy when available.
    """
    cached = _cache_get(user_id)
    if cached is not None:
        return cached

    engine = get_engine()
    with engine.connect() as conn:
        # Fetch categories ordered by name.
        cat_rows = conn.execute(
            text(
                "SELECT id, name FROM public.categories"
                " WHERE user_id = :uid ORDER BY name ASC"
            ),
            {"uid": user_id},
        ).fetchall()

        if not cat_rows:
            result = []
            _cache_set(user_id, result)
            return result

        # Fetch all keywords for those categories in one query.
        cat_ids = [str(row[0]) for row in cat_rows]
        placeholders = ", ".join(f":id{i}" for i in range(len(cat_ids)))
        params = {f"id{i}": cat_ids[i] for i in range(len(cat_ids))}
        kw_rows = conn.execute(
            text(
                f"SELECT category_id, keyword FROM public.category_keywords"
                f" WHERE category_id IN ({placeholders})"
                f" ORDER BY keyword ASC"
            ),
            params,
        ).fetchall()

    # Group keywords by category_id string.
    kw_by_cat: dict = {}
    for row in cat_rows:
        kw_by_cat[str(row[0])] = []
    for cat_id, keyword in kw_rows:
        kw_by_cat[str(cat_id)].append(keyword)

    result = [
        {
            "id": str(row[0]),
            "name": row[1],
            "keywords": kw_by_cat.get(str(row[0]), []),
        }
        for row in cat_rows
    ]

    _cache_set(user_id, result)
    return result


def get_category_detail(user_id: str, category_id: str) -> "dict | None":
    """Return a single category with full keyword dicts (id + keyword string).

    Used by the edit route, which needs keyword IDs to build remove-button URLs.
    Returns None if the category doesn't exist or doesn't belong to user_id.

    Result shape: {"id": str, "name": str, "keywords": [{"id": str, "keyword": str}]}
    """
    engine = get_engine()
    with engine.connect() as conn:
        cat_row = conn.execute(
            text(
                "SELECT id, name FROM public.categories"
                " WHERE id = :cid AND user_id = :uid"
            ),
            {"cid": category_id, "uid": user_id},
        ).fetchone()
        if cat_row is None:
            return None
        kw_rows = conn.execute(
            text(
                "SELECT id, keyword FROM public.category_keywords"
                " WHERE category_id = :cid ORDER BY keyword ASC"
            ),
            {"cid": category_id},
        ).fetchall()
    return {
        "id": str(cat_row[0]),
        "name": cat_row[1],
        "keywords": [{"id": str(r[0]), "keyword": r[1]} for r in kw_rows],
    }


def get_category_map(user_id: str) -> dict:
    """Return {category_name: [keyword, ...]} for user_id.

    Derives from list_categories() — no extra DB query when the cache is warm.
    Returns {} if the user has no categories.
    Does NOT auto-seed; callers that need defaults should call seed_defaults().
    """
    categories = list_categories(user_id)
    return {cat["name"]: cat["keywords"] for cat in categories}


def save_category_map(user_id: str, category_map: dict) -> None:
    """Replace the user's entire category set from a flat {name: [keywords]} dict.

    Deletes all existing categories for the user (keywords cascade), then
    inserts the new set.  Normalizes names and keywords; deduplicates keywords
    per category.  Runs inside a single transaction.

    Raises:
        ValueError: if category_map is not a dict.
    """
    if not isinstance(category_map, dict):
        raise ValueError("Invalid category map format")

    engine = get_engine()
    with engine.begin() as conn:
        # Delete existing categories (keywords cascade via FK ON DELETE CASCADE).
        conn.execute(
            text("DELETE FROM public.categories WHERE user_id = :uid"),
            {"uid": user_id},
        )

        for cat_name, keywords in category_map.items():
            norm_name = _norm_name(cat_name)
            if not norm_name:
                continue
            result = conn.execute(
                text(
                    "INSERT INTO public.categories (user_id, name)"
                    " VALUES (:uid, :name) RETURNING id"
                ),
                {"uid": user_id, "name": norm_name},
            )
            cat_id = str(result.fetchone()[0])
            seen: set = set()
            if not isinstance(keywords, list):
                continue
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                norm_kw = _norm_keyword(kw)
                if not norm_kw or norm_kw in seen:
                    continue
                seen.add(norm_kw)
                conn.execute(
                    text(
                        "INSERT INTO public.category_keywords (category_id, keyword)"
                        " VALUES (:cid, :kw)"
                    ),
                    {"cid": cat_id, "kw": norm_kw},
                )

    _cache_invalidate(user_id)


def create_category(user_id: str, name: str) -> dict:
    """Create a new category for user_id.

    Normalizes the name.  Raises ValueError on empty name or duplicate.
    Returns {"id": str, "name": str, "keywords": []}.

    Raises:
        ValueError("Category name cannot be empty")
        ValueError("Category '<name>' already exists")
    """
    norm_name = _norm_name(name)
    if not norm_name:
        raise ValueError("Category name cannot be empty")

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO public.categories (user_id, name)"
                    " VALUES (:uid, :name) RETURNING id"
                ),
                {"uid": user_id, "name": norm_name},
            )
            cat_id = str(result.fetchone()[0])
    except IntegrityError:
        raise ValueError(f"Category '{norm_name}' already exists")

    _cache_invalidate(user_id)
    return {"id": cat_id, "name": norm_name, "keywords": []}


def rename_category(user_id: str, category_id: str, new_name: str) -> dict:
    """Rename an existing category.

    Validates ownership, normalizes the new name, and checks for conflicts
    (excluding the category being renamed).

    Returns {"id": str, "name": str}.

    Raises:
        ValueError("Category not found")
        ValueError("Category name cannot be empty")
        ValueError("Category '<name>' already exists")
    """
    norm_name = _norm_name(new_name)
    if not norm_name:
        raise ValueError("Category name cannot be empty")

    engine = get_engine()
    with engine.begin() as conn:
        _assert_category_owned(conn, user_id, category_id)

        # Check for a name conflict excluding self.
        conflict = conn.execute(
            text(
                "SELECT id FROM public.categories"
                " WHERE user_id = :uid AND name = :name AND id != :cid"
            ),
            {"uid": user_id, "name": norm_name, "cid": category_id},
        ).fetchone()
        if conflict is not None:
            raise ValueError(f"Category '{norm_name}' already exists")

        conn.execute(
            text("UPDATE public.categories SET name = :name WHERE id = :cid"),
            {"name": norm_name, "cid": category_id},
        )

    _cache_invalidate(user_id)
    return {"id": category_id, "name": norm_name}


def delete_category(user_id: str, category_id: str) -> None:
    """Delete a category (keywords cascade automatically).

    Raises:
        ValueError("Category not found")
    """
    engine = get_engine()
    with engine.begin() as conn:
        _assert_category_owned(conn, user_id, category_id)
        conn.execute(
            text("DELETE FROM public.categories WHERE id = :cid"),
            {"cid": category_id},
        )

    _cache_invalidate(user_id)


def add_keyword(user_id: str, category_id: str, keyword: str) -> dict:
    """Add a keyword to a category owned by user_id.

    Validates category ownership.  Normalizes the keyword.
    Returns {"id": str, "keyword": str}.

    Raises:
        ValueError("Category not found")
        ValueError("Keyword cannot be empty")
        ValueError("Keyword '<kw>' already exists in this category")
    """
    norm_kw = _norm_keyword(keyword)
    if not norm_kw:
        raise ValueError("Keyword cannot be empty")

    engine = get_engine()
    with engine.begin() as conn:
        _assert_category_owned(conn, user_id, category_id)
        try:
            result = conn.execute(
                text(
                    "INSERT INTO public.category_keywords (category_id, keyword)"
                    " VALUES (:cid, :kw) RETURNING id"
                ),
                {"cid": category_id, "kw": norm_kw},
            )
            kw_id = str(result.fetchone()[0])
        except IntegrityError:
            raise ValueError(f"Keyword '{norm_kw}' already exists in this category")

    _cache_invalidate(user_id)
    return {"id": kw_id, "keyword": norm_kw}


def remove_keyword(user_id: str, category_id: str, keyword_id: str) -> None:
    """Remove a keyword from a category.

    Validates that the category belongs to user_id and that the keyword
    belongs to that category.

    Raises:
        ValueError("Category not found")
        ValueError("Keyword not found")
    """
    engine = get_engine()
    with engine.begin() as conn:
        _assert_category_owned(conn, user_id, category_id)
        _assert_keyword_owned(conn, user_id, category_id, keyword_id)
        conn.execute(
            text("DELETE FROM public.category_keywords WHERE id = :kid"),
            {"kid": keyword_id},
        )

    _cache_invalidate(user_id)


def import_from_json(user_id: str, category_map: dict) -> None:
    """Import a category map from a parsed JSON dict.

    Validates that the input is a dict with string keys and list-of-string
    values.  Delegates to save_category_map(); idempotent.

    Raises:
        ValueError("Invalid category map format")
    """
    if not isinstance(category_map, dict):
        raise ValueError("Invalid category map format")
    for key, val in category_map.items():
        if not isinstance(key, str):
            raise ValueError("Invalid category map format")
        if not isinstance(val, list) or not all(isinstance(kw, str) for kw in val):
            raise ValueError("Invalid category map format")

    save_category_map(user_id, category_map)


def seed_defaults(user_id: str) -> None:
    """Seed the user's categories from GENERIC_CATEGORY_MAP if they have none.

    No-op if the user already has at least one category.
    No-op if GENERIC_CATEGORY_MAP is empty or not configured.
    """
    existing = list_categories(user_id)
    if existing:
        return

    try:
        from flask import current_app
        generic = current_app.config.get("GENERIC_CATEGORY_MAP", {})
    except RuntimeError:
        # Outside application context — nothing to seed.
        return

    if not generic:
        return

    import_from_json(user_id, generic)
