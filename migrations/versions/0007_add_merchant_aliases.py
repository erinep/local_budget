"""Create public.merchant_aliases table for Phase 5b Categorizer v2 (ADR-0029).

Stores normalized merchant names mapped to categories for Tier 2 exact-match
lookups in make_categorizer_v2. Tenant scope is enforced via category_id FK
into public.categories (which carries user_id), consistent with the pattern
established for category_keywords in ADR-0009.

Foreign keys:
  - category_id -> public.categories(id) ON DELETE CASCADE

Revision ID: 0007
Revises:     0006
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.merchant_aliases (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id     UUID NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
            normalized_name TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (category_id, normalized_name)
        )
    """)

    op.execute(
        "CREATE INDEX idx_merchant_aliases_category_id"
        " ON public.merchant_aliases (category_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_merchant_aliases_category_id")
    op.execute("DROP TABLE public.merchant_aliases")
