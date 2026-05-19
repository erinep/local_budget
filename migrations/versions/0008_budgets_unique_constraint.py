"""Add UNIQUE (user_id, category_id) constraint to public.budgets.

Migration 0006 declared the constraint in its CREATE TABLE but it was not
present on databases created before that migration was applied. This migration
adds it safely:

1. Deduplicates any existing rows (keeps the row with the highest amount per
   user/category pair, falling back to largest id to be deterministic).
2. Adds the constraint with a named form so ON CONFLICT ON CONSTRAINT can be
   used reliably in application code.

Idempotent: the DO $$ block checks pg_constraint before acting.

Revision ID: 0008
Revises:     0007
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_budgets_user_category'
                  AND conrelid = 'public.budgets'::regclass
            ) THEN
                -- Remove duplicate rows, keeping the one with the highest amount
                -- (ties broken by largest id so the result is deterministic).
                DELETE FROM public.budgets
                WHERE id NOT IN (
                    SELECT DISTINCT ON (user_id, category_id) id
                    FROM public.budgets
                    ORDER BY user_id, category_id, amount DESC, id DESC
                );

                ALTER TABLE public.budgets
                    ADD CONSTRAINT uq_budgets_user_category
                    UNIQUE (user_id, category_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE public.budgets
            DROP CONSTRAINT IF EXISTS uq_budgets_user_category;
    """)
