"""add rebuildable wiki context index

Revision ID: 9c2e4f7a1b55
Revises: 8f4b1d6e0a99
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c2e4f7a1b55"
down_revision: Union[str, None] = "8f4b1d6e0a99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wiki_context_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("wiki_path", sa.String(length=500), nullable=False),
        sa.Column("wiki_url", sa.String(length=700), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("aliases", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", name="uq_wiki_context_source_id"),
    )


def downgrade() -> None:
    op.drop_table("wiki_context_items")
