"""add explicit canonical task owner fields

Revision ID: 3d4e5f6a7b8c
Revises: 2d6e8f0a1b33
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3d4e5f6a7b8c"
down_revision: Union[str, None] = "2d6e8f0a1b33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("owner_wiki_id", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("owner_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("owner_type")
        batch.drop_column("owner_wiki_id")
