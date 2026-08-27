from __future__ import annotations

from alembic import op


revision = "0009_dashboard_one_to_one"
down_revision = "0008_dashboards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_analysis_dashboards_conversation_owner",
        "analysis_dashboards",
        ["tenant_id", "user_id", "conversation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_analysis_dashboards_conversation_owner", table_name="analysis_dashboards")
