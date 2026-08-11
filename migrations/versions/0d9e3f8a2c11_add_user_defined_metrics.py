"""add user-defined metrics

Revision ID: 0d9e3f8a2c11
Revises: 7f3c2a1d9b44
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0d9e3f8a2c11"
down_revision: Union[str, None] = "7f3c2a1d9b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("data_type", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=80)),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "metric_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "metric_id", sa.Integer(), sa.ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=300)),
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("metric_entries")
    op.drop_table("metric_definitions")
