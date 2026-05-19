"""Add updated_at column to public.budgets if missing.

Some live databases have public.budgets without an updated_at column
because the table was created before or independently of migration 0006.
This migration adds it safely with a backfill default of created_at.

Revision ID: 0009
Revises:     0008
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = 'budgets'
                  AND column_name  = 'updated_at'
            ) THEN
                ALTER TABLE public.budgets
                    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

                UPDATE public.budgets SET updated_at = created_at;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    pass
