"""add structured goal planning fields

Revision ID: 4b0d7f2a6c55
Revises: 3a9c6e1f5b44
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4b0d7f2a6c55"
down_revision: Union[str, None] = "3a9c6e1f5b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("goals") as batch:
        batch.add_column(sa.Column("outcome", sa.Text(), nullable=True))
        batch.add_column(sa.Column("baseline", sa.Text(), nullable=True))
        batch.add_column(sa.Column("target", sa.Text(), nullable=True))
        batch.add_column(sa.Column("rationale", sa.Text(), nullable=True))
        batch.add_column(sa.Column("constraints", sa.Text(), nullable=True))
        batch.add_column(sa.Column("review_cadence", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("review_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("adjustment_trigger", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("goals") as batch:
        batch.drop_column("adjustment_trigger")
        batch.drop_column("review_date")
        batch.drop_column("review_cadence")
        batch.drop_column("constraints")
        batch.drop_column("rationale")
        batch.drop_column("target")
        batch.drop_column("baseline")
        batch.drop_column("outcome")
