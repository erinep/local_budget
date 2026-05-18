"""Drop uploads.row_count — replaced by live transaction count (ADR-0022).

The stored row_count reflected rows parsed at ingestion time and went stale
after deduplication or cascaded deletes. get_uploads now computes the count
live via LEFT JOIN on public.transactions.source_file_id.

Revision ID: 0004
Revises:     0003
Create Date: 2026-05-18 00:00:00.000000 UTC
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("uploads", "row_count", schema="public")


def downgrade() -> None:
    op.add_column(
        "uploads",
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        schema="public",
    )
