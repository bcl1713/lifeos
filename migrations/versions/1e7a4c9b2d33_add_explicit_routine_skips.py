"""add explicit routine skips

Revision ID: 1e7a4c9b2d33
Revises: 0d9e3f8a2c11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1e7a4c9b2d33"
down_revision: Union[str, None] = "0d9e3f8a2c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routine_skips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("routine_id", sa.Integer(), sa.ForeignKey("routines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("routine_id", "scheduled_date", name="uq_routine_skip_date"),
    )


def downgrade() -> None:
    op.drop_table("routine_skips")
