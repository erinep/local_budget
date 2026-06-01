"""Add public.user_settings table for per-user preferences (ADR-0043).

Stores one row per user with monthly_income (nullable) and future preferences.
ON DELETE CASCADE ensures purge on account deletion (ADR-0015).

Revision ID: 0011
Revises:     0010
Create Date: 2026-05-31 00:00:00.000000 UTC
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.user_settings (
            user_id        UUID           NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
            monthly_income NUMERIC(12,2)  CHECK (monthly_income IS NULL OR monthly_income >= 0),
            created_at     TIMESTAMPTZ    NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ    NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE public.user_settings")
