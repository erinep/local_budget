"""Add covering index for aggregation queries (ADR-0023).

The idx_transactions_user_date_category index supports get_spend_by_category
and get_spend_history, which filter on (user_id, date range, amount < 0) and
group by category_id. Including category_id in the index avoids a separate
heap lookup for the GROUP BY column in the common case.

Revision ID: 0005
Revises:     0004
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_transactions_user_date_category",
        "transactions",
        ["user_id", sa.text("date DESC"), "category_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_transactions_user_date_category",
        table_name="transactions",
        schema="public",
    )
