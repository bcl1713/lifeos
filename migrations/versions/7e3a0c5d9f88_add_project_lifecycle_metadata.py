"""add structured project lifecycle metadata

Revision ID: 7e3a0c5d9f88
Revises: 6d2f9b4c8e77
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7e3a0c5d9f88"
down_revision: Union[str, None] = "6d2f9b4c8e77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("owner", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("collaborators", sa.Text(), nullable=True))
        batch.add_column(sa.Column("scope", sa.Text(), nullable=True))
        batch.add_column(sa.Column("non_goals", sa.Text(), nullable=True))
        batch.add_column(sa.Column("risks", sa.Text(), nullable=True))
        batch.add_column(sa.Column("deadline", sa.Date(), nullable=True))
        batch.add_column(sa.Column("review_trigger", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_refs", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("source_refs")
        batch.drop_column("review_trigger")
        batch.drop_column("deadline")
        batch.drop_column("risks")
        batch.drop_column("non_goals")
        batch.drop_column("scope")
        batch.drop_column("collaborators")
        batch.drop_column("owner")
