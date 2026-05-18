"""Phase 3a schema: accounts, uploads, transactions.

Creates three new tables in dependency order inside a single Alembic transaction:
  1. public.accounts   — one row per named account per user (ADR-0014)
  2. public.uploads    — one row per uploaded CSV file, with file-level SHA-256 hash (ADR-0013)
  3. public.transactions — one row per transaction, with row-level SHA-256 fingerprint (ADR-0013)

All timestamps are TIMESTAMPTZ defaulting to now() per ADR-0001. UUID primary keys
default to gen_random_uuid(). Every per-user table cascades to auth.users(id) per ADR-0015.

Also repairs the public.categories table: the 0002 migration created user_id without a FK
to auth.users(id), so this migration adds that FK with ON DELETE CASCADE per ADR-0015.

ADR-0013: two-layer hash idempotency (file_hash + fingerprint).
ADR-0014: accounts table; account_id NOT NULL on uploads and transactions.
ADR-0015: hard cascade on user deletion.
ADR-0016: schema specification consolidating 0013/0014/0015 into one migration.

Revision ID: 0003
Revises:     0002
Create Date: 2026-05-17 00:00:00.000000 UTC

PII note:
  transactions.description is a verbatim merchant description from the CSV.
  uploads.filename may contain PII (e.g. "jane_doe_chequing_2026-04.csv").
  uploads.file_hash and transactions.fingerprint are SHA-256 digests derived
  from PII — treat as PII for log-scrubbing purposes.
  Retention: lifetime of user account; cascade on user deletion.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. Repair public.categories — add the missing ON DELETE CASCADE FK
    #    on user_id that the 0002 migration omitted (ADR-0015 follow-up).
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_categories_user_id",
        "categories",
        "users",
        ["user_id"],
        ["id"],
        source_schema="public",
        referent_schema="auth",
        ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 1. Create public.accounts
    #
    # One row per named account per user. The UNIQUE (user_id, name)
    # constraint prevents duplicate account names per user and serves as
    # the upsert target in get_or_create_default_account.
    # ON DELETE CASCADE from auth.users ensures hard deletion on account
    # removal per ADR-0015.
    # ------------------------------------------------------------------
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "currency",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'CAD'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_accounts_user_name"),
        sa.CheckConstraint(
            "kind IN ('checking','savings','credit_card','other')",
            name="ck_accounts_kind",
        ),
        schema="public",
    )
    op.create_index(
        "idx_accounts_user_id",
        "accounts",
        ["user_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 2. Create public.uploads
    #
    # One row per uploaded CSV file. file_hash is SHA-256 over the raw
    # upload bytes (32 bytes, BYTEA). UNIQUE (user_id, file_hash)
    # short-circuits byte-identical re-uploads before row parsing
    # (ADR-0013, file-level layer).
    # ON DELETE CASCADE from both auth.users and accounts per ADR-0015.
    # ------------------------------------------------------------------
    op.create_table(
        "uploads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column(
            "file_hash",
            postgresql.BYTEA(),
            nullable=False,
        ),
        sa.Column(
            "row_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "file_hash", name="uq_uploads_user_file_hash"),
        sa.CheckConstraint(
            "octet_length(file_hash) = 32",
            name="ck_uploads_file_hash_len",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_uploads_row_count_nonneg",
        ),
        schema="public",
    )
    op.create_index(
        "idx_uploads_user_id",
        "uploads",
        ["user_id"],
        schema="public",
    )
    op.create_index(
        "idx_uploads_account_id",
        "uploads",
        ["account_id"],
        schema="public",
    )

    # ------------------------------------------------------------------
    # 3. Create public.transactions
    #
    # One row per transaction. fingerprint is SHA-256 over a canonical
    # tuple (ADR-0013 canonicalization rule, 32 bytes, BYTEA).
    # UNIQUE (user_id, fingerprint) with ON CONFLICT DO NOTHING on insert
    # handles the overlapping-export dedup case.
    #
    # category_id is NULLABLE with ON DELETE SET NULL so deleting a
    # category does not delete the underlying spend — the transaction
    # becomes uncategorized rather than lost.
    #
    # FKs: user_id, account_id, source_file_id cascade; category_id sets null.
    # ------------------------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "fingerprint",
            postgresql.BYTEA(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "fingerprint", name="uq_transactions_user_fingerprint"
        ),
        sa.CheckConstraint(
            "octet_length(fingerprint) = 32",
            name="ck_transactions_fingerprint_len",
        ),
        schema="public",
    )
    op.create_index(
        "idx_transactions_user_date",
        "transactions",
        ["user_id", sa.text("date DESC")],
        schema="public",
    )
    op.create_index(
        "idx_transactions_user_category",
        "transactions",
        ["user_id", "category_id"],
        schema="public",
    )
    op.create_index(
        "idx_transactions_user_account",
        "transactions",
        ["user_id", "account_id"],
        schema="public",
    )
    op.create_index(
        "idx_transactions_source_file",
        "transactions",
        ["source_file_id"],
        schema="public",
    )


def downgrade() -> None:
    # Drop in reverse order: transactions indexes → transactions table
    # → uploads indexes → uploads table → accounts indexes → accounts table
    # → categories FK repair.
    # DROP TABLE removes implicit indexes (UNIQUE/PK); only explicitly named
    # CREATE INDEX indexes need explicit DROP INDEX.

    # -- transactions --
    op.drop_index("idx_transactions_source_file", table_name="transactions", schema="public")
    op.drop_index("idx_transactions_user_account", table_name="transactions", schema="public")
    op.drop_index("idx_transactions_user_category", table_name="transactions", schema="public")
    op.drop_index("idx_transactions_user_date", table_name="transactions", schema="public")
    op.drop_table("transactions", schema="public")

    # -- uploads --
    op.drop_index("idx_uploads_account_id", table_name="uploads", schema="public")
    op.drop_index("idx_uploads_user_id", table_name="uploads", schema="public")
    op.drop_table("uploads", schema="public")

    # -- accounts --
    op.drop_index("idx_accounts_user_id", table_name="accounts", schema="public")
    op.drop_table("accounts", schema="public")

    # -- undo categories FK repair --
    op.drop_constraint(
        "fk_categories_user_id",
        "categories",
        schema="public",
        type_="foreignkey",
    )
