"""add metric presentation and missing-value metadata

Revision ID: 5c1e8a3b7d66
Revises: 4b0d7f2a6c55
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5c1e8a3b7d66"
down_revision: Union[str, None] = "4b0d7f2a6c55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("metric_definitions") as batch:
        batch.add_column(sa.Column("aggregation", sa.String(length=30), nullable=False, server_default="latest"))
        batch.add_column(sa.Column("display", sa.String(length=30), nullable=False, server_default="number"))
        batch.add_column(sa.Column("privacy", sa.String(length=30), nullable=False, server_default="private"))
        batch.add_column(sa.Column("missing_policy", sa.String(length=30), nullable=False, server_default="unknown"))


def downgrade() -> None:
    with op.batch_alter_table("metric_definitions") as batch:
        batch.drop_column("missing_policy")
        batch.drop_column("privacy")
        batch.drop_column("display")
        batch.drop_column("aggregation")
