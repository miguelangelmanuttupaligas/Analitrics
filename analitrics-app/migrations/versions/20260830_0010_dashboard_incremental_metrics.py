from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_dashboard_inc"
down_revision = "0009_dashboard_one_to_one"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_dashboard_views", sa.Column("metric", sa.Text(), nullable=True))
    op.add_column(
        "analysis_dashboard_views",
        sa.Column(
            "dimensions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "analysis_dashboard_views",
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "analysis_dashboard_views",
        sa.Column(
            "source_file_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("analysis_dashboard_views", sa.Column("catalog_hash", sa.Text(), nullable=True))
    op.add_column(
        "analysis_dashboard_views",
        sa.Column(
            "generation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "idx_analysis_dashboard_views_catalog_hash",
        "analysis_dashboard_views",
        ["tenant_id", "user_id", "dashboard_id", "catalog_hash"],
    )

    op.create_table(
        "analysis_catalog_metrics",
        sa.Column("metric_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("source_file_id", sa.Text(), nullable=True),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_from", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id", "conversation_id"],
            ["analysis_catalog_sessions.tenant_id", "analysis_catalog_sessions.user_id", "analysis_catalog_sessions.conversation_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "user_id", "conversation_id", "name", name="uq_analysis_catalog_metrics_name"),
    )
    op.create_index(
        "idx_analysis_catalog_metrics_conversation",
        "analysis_catalog_metrics",
        ["tenant_id", "user_id", "conversation_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_analysis_catalog_metrics_conversation", table_name="analysis_catalog_metrics")
    op.drop_table("analysis_catalog_metrics")
    op.drop_index("idx_analysis_dashboard_views_catalog_hash", table_name="analysis_dashboard_views")
    op.drop_column("analysis_dashboard_views", "generation_metadata")
    op.drop_column("analysis_dashboard_views", "catalog_hash")
    op.drop_column("analysis_dashboard_views", "source_file_ids")
    op.drop_column("analysis_dashboard_views", "filters")
    op.drop_column("analysis_dashboard_views", "dimensions")
    op.drop_column("analysis_dashboard_views", "metric")
