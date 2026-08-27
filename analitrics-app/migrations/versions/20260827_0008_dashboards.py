from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_dashboards"
down_revision = "0007_pending_clarification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_dashboards",
        sa.Column("dashboard_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("seed_question", sa.Text(), nullable=True),
        sa.Column("seed_sql", sa.Text(), nullable=False),
        sa.Column("seed_message_id", sa.Text(), nullable=True),
        sa.Column("seed_run_id", sa.Text(), nullable=True),
        sa.Column(
            "source_file_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("duckdb_path", sa.Text(), nullable=True),
        sa.Column(
            "catalog_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "business_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id", "conversation_id"],
            ["analysis_catalog_sessions.tenant_id", "analysis_catalog_sessions.user_id", "analysis_catalog_sessions.conversation_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_analysis_dashboards_user_recent",
        "analysis_dashboards",
        ["tenant_id", "user_id", "updated_at"],
    )
    op.create_index(
        "idx_analysis_dashboards_conversation",
        "analysis_dashboards",
        ["tenant_id", "user_id", "conversation_id"],
    )

    op.create_table(
        "analysis_dashboard_views",
        sa.Column("view_id", sa.Text(), primary_key=True),
        sa.Column("dashboard_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("view_type", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column(
            "chart_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dashboard_id"], ["analysis_dashboards.dashboard_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_analysis_dashboard_views_dashboard",
        "analysis_dashboard_views",
        ["dashboard_id", "position"],
    )
    op.create_index(
        "idx_analysis_dashboard_views_user_recent",
        "analysis_dashboard_views",
        ["tenant_id", "user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_analysis_dashboard_views_user_recent", table_name="analysis_dashboard_views")
    op.drop_index("idx_analysis_dashboard_views_dashboard", table_name="analysis_dashboard_views")
    op.drop_table("analysis_dashboard_views")
    op.drop_index("idx_analysis_dashboards_conversation", table_name="analysis_dashboards")
    op.drop_index("idx_analysis_dashboards_user_recent", table_name="analysis_dashboards")
    op.drop_table("analysis_dashboards")
