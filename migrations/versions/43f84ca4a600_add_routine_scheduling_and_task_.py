"""add routine scheduling and task occurrences

Revision ID: 43f84ca4a600
Revises: 2ba6cdca15f2
Create Date: 2026-08-11 17:07:34.307584
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "43f84ca4a600"
down_revision: Union[str, None] = "2ba6cdca15f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("routines") as batch_op:
        batch_op.add_column(sa.Column("next_run_date", sa.Date(), nullable=False))
        batch_op.add_column(sa.Column("task_list_id", sa.Integer(), nullable=False))
        batch_op.create_foreign_key(
            "fk_routines_task_list_id_task_lists", "task_lists", ["task_list_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("occurrence_key", sa.String(length=180), nullable=True))
        batch_op.drop_constraint("uq_task_list_title", type_="unique")
        batch_op.create_unique_constraint("uq_tasks_occurrence_key", ["occurrence_key"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("uq_tasks_occurrence_key", type_="unique")
        batch_op.create_unique_constraint("uq_task_list_title", ["task_list_id", "title"])
        batch_op.drop_column("occurrence_key")
    with op.batch_alter_table("routines") as batch_op:
        batch_op.drop_constraint("fk_routines_task_list_id_task_lists", type_="foreignkey")
        batch_op.drop_column("task_list_id")
        batch_op.drop_column("next_run_date")
