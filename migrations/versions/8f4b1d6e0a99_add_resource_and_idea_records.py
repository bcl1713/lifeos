"""add resource and idea lifecycle records

Revision ID: 8f4b1d6e0a99
Revises: 7e3a0c5d9f88
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8f4b1d6e0a99"
down_revision: Union[str, None] = "7e3a0c5d9f88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("canonical_url", sa.String(length=1000)),
        sa.Column("resource_type", sa.String(length=80)),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("description", sa.Text()),
        sa.Column("accessed_at", sa.Date()),
        sa.Column("source_refs", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ideas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="captured"),
        sa.Column("rationale", sa.Text()),
        sa.Column("experiment", sa.Text()),
        sa.Column("next_action", sa.Text()),
        sa.Column("source_refs", sa.Text()),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ideas")
    op.drop_table("resources")
