"""Phase 5c: simplify public.accounts — drop is_active, kind, currency.

ADR-0034: Accounts are logical transaction groups (sets), not financial
account replicas. Archive semantics are dropped entirely. The is_active,
kind, and currency columns have no role in the simplified model.

Revision ID: 0009
Revises:     0008
Create Date: 2026-05-23 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_accounts_kind", "accounts", schema="public", type_="check")
    op.drop_column("accounts", "is_active", schema="public")
    op.drop_column("accounts", "kind", schema="public")
    op.drop_column("accounts", "currency", schema="public")


def downgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "currency",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'CAD'"),
        ),
        schema="public",
    )
    op.add_column(
        "accounts",
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'checking'")),
        schema="public",
    )
    op.add_column(
        "accounts",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_accounts_kind",
        "accounts",
        "kind IN ('checking','savings','credit_card','other')",
        schema="public",
    )
