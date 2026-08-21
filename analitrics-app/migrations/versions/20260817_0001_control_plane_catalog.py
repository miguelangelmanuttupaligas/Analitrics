from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_control_plane_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("analysis_catalog_sessions"):
        op.create_table(
            "analysis_catalog_sessions",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("conversation_id", sa.Text(), nullable=False),
            sa.Column("cache_path", sa.Text(), nullable=True),
            sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("table_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("processed_files", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("last_cache_hits", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "user_id", "conversation_id"),
        )
    if not inspector.has_table("analysis_catalog_profiles"):
        op.create_table(
            "analysis_catalog_profiles",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("conversation_id", sa.Text(), nullable=False),
            sa.Column("table_name", sa.Text(), nullable=False),
            sa.Column("source_file_id", sa.Text(), nullable=True),
            sa.Column("source_filename", sa.Text(), nullable=True),
            sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id", "conversation_id"],
                ["analysis_catalog_sessions.tenant_id", "analysis_catalog_sessions.user_id", "analysis_catalog_sessions.conversation_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("tenant_id", "user_id", "conversation_id", "table_name"),
        )
    op.execute(
        """
        create index if not exists idx_analysis_catalog_profiles_file
        on analysis_catalog_profiles (tenant_id, user_id, source_file_id)
        """
    )


def downgrade() -> None:
    op.drop_index("idx_analysis_catalog_profiles_file", table_name="analysis_catalog_profiles")
    op.drop_table("analysis_catalog_profiles")
    op.drop_table("analysis_catalog_sessions")
