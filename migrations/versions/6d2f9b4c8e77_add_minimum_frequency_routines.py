"""add minimum-frequency routine configuration

Revision ID: 6d2f9b4c8e77
Revises: 5c1e8a3b7d66
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6d2f9b4c8e77"
down_revision: Union[str, None] = "5c1e8a3b7d66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("routines") as batch:
        batch.add_column(sa.Column("minimum_occurrences", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("frequency_window_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("routines") as batch:
        batch.drop_column("frequency_window_days")
        batch.drop_column("minimum_occurrences")
