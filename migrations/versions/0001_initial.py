"""Initial schema: user_sessions and custom_categories tables.

ADR-0007: All schema changes go through Alembic.
ADR-0001: All timestamps are TIMESTAMPTZ (UTC) — no naive datetime columns.

Revision ID: 0001
Revises: None
Create Date: 2026-05-10 00:00:00.000000 UTC

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # user_sessions
    # Stores active refresh tokens so the middleware can silently refresh
    # sessions nearing expiry. One row per issued session; expired rows
    # should be pruned by a background job (Phase 5).
    #
    # PII note: user_id is a UUID foreign key to Supabase Auth; no email
    # or name is stored here. refresh_token is treated as a secret and
    # must never appear in logs (PII scrubber covers this).
    # Retention: rows expire via expires_at; hard-delete by Phase 5 job.
    # ------------------------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_index(
        "idx_user_sessions_user_id",
        "user_sessions",
        ["user_id"],
        schema="public",
    )
    op.create_index(
        "idx_user_sessions_expires_at",
        "user_sessions",
        ["expires_at"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # custom_categories
    # Stores a per-user JSONB category map (keyword → category overrides).
    # Account Settings owns this table; the Transaction Engine reads the
    # map via the Account Settings service interface, not directly.
    #
    # PII note: category_map contains merchant keywords set by the user —
    # not raw transaction data. Retention: lives as long as the account.
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


def downgrade() -> None:
    op.drop_index("idx_custom_categories_user_id", table_name="custom_categories", schema="public")
    op.drop_table("custom_categories", schema="public")

    op.drop_index("idx_user_sessions_expires_at", table_name="user_sessions", schema="public")
    op.drop_index("idx_user_sessions_user_id", table_name="user_sessions", schema="public")
    op.drop_table("user_sessions", schema="public")
