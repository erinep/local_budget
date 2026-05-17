"""Normalize categories: replace custom_categories JSONB with relational tables.

Replaces the single-row JSONB ``custom_categories`` table (introduced in
0001_initial) with two properly-normalized relational tables:

- ``public.categories``        — one row per named category per user
- ``public.category_keywords`` — one row per keyword per category

The data migration (inside upgrade()) reads any existing JSONB rows,
normalizes names and keywords, and inserts them into the new tables before
dropping the old table.

ADR-0007: all schema changes go through Alembic; never raw SQL on prod.
ADR-0001: all TIMESTAMPTZ columns default to now() UTC.
ADR-0009: normalized category schema (two-table relational design).
ADR-0010: per-request g._category_cache invalidated on every write.

Revision ID: 0002
Revises:     0001
Create Date: 2026-05-16 00:00:00.000000 UTC

PII note:
  categories.name and category_keywords.keyword contain user-supplied labels
  (e.g. "Groceries", "METRO"). These are not raw transaction descriptions —
  they are user-defined configuration strings. Retention: lives as long as
  the account; deleted on account deletion via cascade from categories.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create public.categories
    #
    # One row per named category per user.  The UNIQUE (user_id, name)
    # constraint prevents duplicate category names for the same user.
    # ON DELETE behaviour: if the user row is removed from Supabase Auth,
    # categories are orphaned (no FK to auth.users here — Supabase manages
    # that side). Account-deletion runbook is deferred to Phase 3a ADR.
    # ------------------------------------------------------------------
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_categories_user_name"),
        schema="public",
    )
    op.create_index(
        "idx_categories_user_id",
        "categories",
        ["user_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 2. Create public.category_keywords
    #
    # One row per keyword per category.  ON DELETE CASCADE means removing
    # a category automatically removes all its keywords — no orphan cleanup
    # needed at the application layer.
    # ------------------------------------------------------------------
    op.create_table(
        "category_keywords",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("category_id", "keyword", name="uq_category_keywords_cat_kw"),
        schema="public",
    )
    op.create_index(
        "idx_category_keywords_category_id",
        "category_keywords",
        ["category_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 3. Data migration — JSONB → relational rows
    #
    # Normalization rules (mirrors the service layer so on-disk data is
    # consistent with what the service would write):
    #   category name : " ".join(name.strip().split())   — strip + collapse
    #   keyword       : kw.strip().upper()               — upper-case, strip
    #
    # Duplicates are deduped per category (seen set).  Empty strings after
    # normalization are skipped silently — they would be rejected by the
    # service layer anyway.
    # ------------------------------------------------------------------
    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT user_id, category_map FROM public.custom_categories")
    ).fetchall()

    for user_id, category_map in rows:
        if not isinstance(category_map, dict):
            continue
        for cat_name, keywords in category_map.items():
            norm_name = " ".join(cat_name.strip().split())
            if not norm_name:
                continue
            result = conn.execute(
                text(
                    "INSERT INTO public.categories (user_id, name)"
                    " VALUES (:uid, :name) RETURNING id"
                ),
                {"uid": str(user_id), "name": norm_name},
            )
            cat_id = result.fetchone()[0]
            seen: set[str] = set()
            if not isinstance(keywords, list):
                continue
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                norm_kw = kw.strip().upper()
                if not norm_kw or norm_kw in seen:
                    continue
                seen.add(norm_kw)
                conn.execute(
                    text(
                        "INSERT INTO public.category_keywords (category_id, keyword)"
                        " VALUES (:cid, :kw)"
                    ),
                    {"cid": str(cat_id), "kw": norm_kw},
                )

    # ------------------------------------------------------------------
    # 4. Drop public.custom_categories (now superseded)
    # ------------------------------------------------------------------
    op.drop_index("idx_custom_categories_user_id", table_name="custom_categories", schema="public")
    op.drop_table("custom_categories", schema="public")


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Recreate public.custom_categories
    # ------------------------------------------------------------------
    op.create_table(
        "custom_categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "category_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="public",
    )
    op.create_index(
        "idx_custom_categories_user_id",
        "custom_categories",
        ["user_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 2. Data migration — relational rows → JSONB
    #
    # Re-serializes each user's categories + keywords back into the JSONB
    # format expected by the 0001 schema.  Keywords are stored as-is (they
    # were uppercased during the forward migration, so the downgraded data
    # will be uppercase — this is acceptable for a rollback scenario).
    # ------------------------------------------------------------------
    import json

    conn = op.get_bind()

    # Collect all categories, then all keywords, grouped by user.
    cat_rows = conn.execute(
        text("SELECT id, user_id, name FROM public.categories ORDER BY name ASC")
    ).fetchall()

    # Build a map: cat_id → (user_id, name)
    cat_map: dict[str, tuple[str, str]] = {
        str(row[0]): (str(row[1]), row[2]) for row in cat_rows
    }

    kw_rows = conn.execute(
        text("SELECT category_id, keyword FROM public.category_keywords")
    ).fetchall()

    # Build: user_id → {cat_name: [keywords]}
    user_data: dict[str, dict[str, list[str]]] = {}
    for cat_id, keyword in kw_rows:
        cat_id_str = str(cat_id)
        if cat_id_str not in cat_map:
            continue
        user_id_str, cat_name = cat_map[cat_id_str]
        user_data.setdefault(user_id_str, {}).setdefault(cat_name, []).append(keyword)

    # Include users who have categories but no keywords.
    for cat_id_str, (user_id_str, cat_name) in cat_map.items():
        user_data.setdefault(user_id_str, {}).setdefault(cat_name, [])

    for user_id_str, category_map in user_data.items():
        conn.execute(
            text(
                "INSERT INTO public.custom_categories (user_id, category_map)"
                " VALUES (:uid, :cmap)"
                " ON CONFLICT (user_id) DO UPDATE SET category_map = EXCLUDED.category_map"
            ),
            {"uid": user_id_str, "cmap": json.dumps(category_map)},
        )

    # ------------------------------------------------------------------
    # 3. Drop the normalized tables (keywords first, then categories)
    # ------------------------------------------------------------------
    op.drop_index("idx_category_keywords_category_id", table_name="category_keywords", schema="public")
    op.drop_table("category_keywords", schema="public")

    op.drop_index("idx_categories_user_id", table_name="categories", schema="public")
    op.drop_table("categories", schema="public")
