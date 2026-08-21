from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_invalidation"
down_revision = "0001_control_plane_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("analysis_catalog_profiles")}
    if "active" not in columns:
        op.add_column("analysis_catalog_profiles", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    if "deleted_at" not in columns:
        op.add_column("analysis_catalog_profiles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    if "deleted_reason" not in columns:
        op.add_column("analysis_catalog_profiles", sa.Column("deleted_reason", sa.Text(), nullable=True))
    op.execute(
        """
        create index if not exists idx_analysis_catalog_profiles_active
        on analysis_catalog_profiles (tenant_id, user_id, conversation_id, active)
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists idx_analysis_catalog_profiles_active")
    op.drop_column("analysis_catalog_profiles", "deleted_reason")
    op.drop_column("analysis_catalog_profiles", "deleted_at")
    op.drop_column("analysis_catalog_profiles", "active")
