"""Initial migration - create all tables.

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("keyword", sa.String(255), nullable=False, index=True),
        sa.Column("slug", sa.String(300), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("wp_post_id", sa.Integer(), nullable=True),
        sa.Column("wp_url", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(50), default="draft"),
        sa.Column("word_count", sa.Integer(), default=0),
        sa.Column("seo_score", sa.Float(), default=0.0),
        sa.Column("thumbnail_source", sa.String(100), default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("keyword", sa.String(255), nullable=False, index=True),
        sa.Column("total_score", sa.Float(), default=0.0),
        sa.Column("search_volume_score", sa.Float(), default=0.0),
        sa.Column("search_intent_score", sa.Float(), default=0.0),
        sa.Column("evergreen_score", sa.Float(), default=0.0),
        sa.Column("commercial_value_score", sa.Float(), default=0.0),
        sa.Column("competition_score", sa.Float(), default=0.0),
        sa.Column("relevance_score", sa.Float(), default=0.0),
        sa.Column("source", sa.String(100), default=""),
        sa.Column("used", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("keyword", sa.String(255), default=""),
        sa.Column("status", sa.String(50), default="running"),
        sa.Column("progress_step", sa.String(200), default=""),
        sa.Column("article_title", sa.String(500), default=""),
        sa.Column("wp_post_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), default=""),
        sa.Column("processing_time_seconds", sa.Float(), default=0.0),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pipeline_runs")
    op.drop_table("keywords")
    op.drop_table("articles")
