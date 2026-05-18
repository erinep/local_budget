"""Create public.budgets table for Phase 4 Budgeting Module (ADR-0026).

Stores one standing budget target per user per category (global, not month-specific).
ADR-0026 supersedes ADR-0025 Decisions 1 and 2: budget_year and budget_month are
dropped in favour of a single row per (user_id, category_id).

A UNIQUE constraint on (user_id, category_id) enforces one target per category.
An index on (user_id) covers the primary fetch read pattern.

Foreign keys:
  - user_id  -> auth.users(id) ON DELETE CASCADE  (ADR-0015)
  - category_id -> public.categories(id) ON DELETE CASCADE  (ADR-0025, Decision 4)

Revision ID: 0006
Revises:     0005
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.budgets (
            id           UUID          NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id      UUID          NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            category_id  UUID          NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
            amount       NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
            created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE (user_id, category_id)
        )
    """)

    op.create_index(
        "idx_budgets_user",
        "budgets",
        ["user_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_budgets_user",
        table_name="budgets",
        schema="public",
    )
    op.execute("DROP TABLE public.budgets")
