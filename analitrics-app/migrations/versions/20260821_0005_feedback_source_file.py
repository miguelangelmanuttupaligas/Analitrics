from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_feedback_source_file"
down_revision = "0004_catalog_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("analysis_catalog_feedback")}
    if "source_file_id" not in columns:
        op.add_column("analysis_catalog_feedback", sa.Column("source_file_id", sa.Text(), nullable=True))
    if "source_filename" not in columns:
        op.add_column("analysis_catalog_feedback", sa.Column("source_filename", sa.Text(), nullable=True))
    op.execute(
        """
        create index if not exists idx_analysis_catalog_feedback_source
        on analysis_catalog_feedback (tenant_id, user_id, conversation_id, source_file_id, step)
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists idx_analysis_catalog_feedback_source")
    op.drop_column("analysis_catalog_feedback", "source_filename")
    op.drop_column("analysis_catalog_feedback", "source_file_id")
