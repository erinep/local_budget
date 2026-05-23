"""Phase 5c: re-add is_active to public.accounts with a defined contract.

ADR-0037: is_active controls whether an account's transactions are included in
reporting. Dropped in 0009 before its role was defined; re-introduced here with
a precise meaning. Default TRUE so all existing accounts remain visible.

Revision ID: 0010
Revises:     0009
Create Date: 2026-05-23 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_column("accounts", "is_active", schema="public")
