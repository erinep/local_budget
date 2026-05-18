"""Create public.budgets table for Phase 4 Budgeting Module (ADR-0025).

Stores one monthly budget target per user per category. The period is encoded
as (budget_year SMALLINT, budget_month SMALLINT) to map directly to
DateRange.for_month(year, month) with no lossy conversion (ADR-0025, Decision 1).

A UNIQUE constraint on (user_id, category_id, budget_year, budget_month) enforces
one budget per category per month. An additional three-column index on
(user_id, budget_year, budget_month) covers the primary monthly-fetch read pattern.

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
            budget_year  SMALLINT      NOT NULL CHECK (budget_year  BETWEEN 2000 AND 2100),
            budget_month SMALLINT      NOT NULL CHECK (budget_month BETWEEN 1    AND 12),
            created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
            UNIQUE (user_id, category_id, budget_year, budget_month)
        )
    """)

    op.create_index(
        "idx_budgets_user_month",
        "budgets",
        ["user_id", "budget_year", "budget_month"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_budgets_user_month",
        table_name="budgets",
        schema="public",
    )
    op.execute("DROP TABLE public.budgets")
