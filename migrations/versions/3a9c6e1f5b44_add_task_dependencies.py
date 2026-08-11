"""add task dependencies

Revision ID: 3a9c6e1f5b44
Revises: 2f8b5d0c4e22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a9c6e1f5b44"
down_revision: Union[str, None] = "2f8b5d0c4e22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
    )


def downgrade() -> None:
    op.drop_table("task_dependencies")
