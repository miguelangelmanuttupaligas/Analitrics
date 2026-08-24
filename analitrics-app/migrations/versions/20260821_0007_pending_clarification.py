from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_pending_clarification"
down_revision = "0006_analysis_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("analysis_catalog_sessions")}
    if "pending_clarification" not in columns:
        op.add_column(
            "analysis_catalog_sessions",
            sa.Column(
                "pending_clarification",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("analysis_catalog_sessions", "pending_clarification")
