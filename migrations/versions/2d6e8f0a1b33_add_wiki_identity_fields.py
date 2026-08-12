"""add wiki identity fields to domain projections

Revision ID: 2d6e8f0a1b33
Revises: 9c2e4f7a1b55
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2d6e8f0a1b33"
down_revision: Union[str, None] = "9c2e4f7a1b55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("goals", "projects", "routines", "tasks"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("wiki_id", sa.String(length=300), nullable=True))
            batch.add_column(sa.Column("wiki_path", sa.String(length=500), nullable=True))
            batch.add_column(sa.Column("wiki_hash", sa.String(length=64), nullable=True))
            batch.create_unique_constraint(f"uq_{table}_wiki_id", ["wiki_id"])


def downgrade() -> None:
    for table in ("tasks", "routines", "projects", "goals"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"uq_{table}_wiki_id", type_="unique")
            batch.drop_column("wiki_hash")
            batch.drop_column("wiki_path")
            batch.drop_column("wiki_id")
