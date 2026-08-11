"""add task lifecycle metadata

Revision ID: 7f3c2a1d9b44
Revises: 43f84ca4a600
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7f3c2a1d9b44"
down_revision: Union[str, None] = "43f84ca4a600"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("tags", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("source_ref", sa.String(length=500), nullable=True))
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.alter_column("priority", server_default=None)
        batch_op.alter_column("tags", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("source_ref")
        batch_op.drop_column("tags")
        batch_op.drop_column("priority")
