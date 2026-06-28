"""Add used_images table and thumbnail_url column.

Revision ID: 002_image_dedup
Revises: 001_initial
Create Date: 2024-01-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_image_dedup"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add thumbnail_url to existing articles table
    op.add_column(
        "articles",
        sa.Column("thumbnail_url", sa.String(2000), nullable=True, server_default=""),
    )

    # New table to track every used image URL
    op.create_table(
        "used_images",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("source", sa.String(50), default=""),
        sa.Column("keyword", sa.String(255), default=""),
        sa.Column("used_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("used_images")
    op.drop_column("articles", "thumbnail_url")
