"""Fix public.budgets schema to match ADR-0026 (global targets, no month-specificity).

The original Phase 4 budgets table was created with budget_year and budget_month
columns (ADR-0025 schema). ADR-0026 superseded that — budgets are global per
(user_id, category_id) — but the live table was never altered. This migration:

  1. Drops budget_year and budget_month (both NOT NULL in the old schema).
  2. Ensures the UNIQUE constraint on (user_id, category_id) exists.

Idempotent: each step checks information_schema before acting, so this is safe
to run against both old-schema and new-schema databases.

Revision ID: 0008
Revises:     0007
Create Date: 2026-05-19 00:00:00.000000 UTC
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop budget_year if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = 'budgets'
                  AND column_name  = 'budget_year'
            ) THEN
                ALTER TABLE public.budgets DROP COLUMN budget_year;
            END IF;
        END $$;
    """)

    # Drop budget_month if it exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name   = 'budgets'
                  AND column_name  = 'budget_month'
            ) THEN
                ALTER TABLE public.budgets DROP COLUMN budget_month;
            END IF;
        END $$;
    """)

    # Ensure UNIQUE (user_id, category_id) exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'public.budgets'::regclass
                  AND contype  = 'u'
                  AND conname  = 'budgets_user_id_category_id_key'
            ) THEN
                ALTER TABLE public.budgets
                    ADD CONSTRAINT budgets_user_id_category_id_key
                    UNIQUE (user_id, category_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Downgrade is intentionally a no-op: re-adding NOT NULL columns with
    # no data is destructive and the old schema (ADR-0025) is superseded.
    pass
