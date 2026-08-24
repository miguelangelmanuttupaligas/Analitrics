from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_analysis_states"
down_revision = "0005_feedback_source_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("analysis_conversation_states"):
        op.create_table(
            "analysis_conversation_states",
            sa.Column("state_id", sa.BigInteger(), sa.Identity(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("conversation_id", sa.Text(), nullable=False),
            sa.Column("message_id", sa.Text(), nullable=True),
            sa.Column("run_id", sa.Text(), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer_summary", sa.Text(), nullable=True),
            sa.Column("intent", sa.Text(), nullable=True),
            sa.Column("metric", sa.Text(), nullable=True),
            sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("dataset", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("last_sql", sa.Text(), nullable=True),
            sa.Column("last_chart", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id", "conversation_id"],
                [
                    "analysis_catalog_sessions.tenant_id",
                    "analysis_catalog_sessions.user_id",
                    "analysis_catalog_sessions.conversation_id",
                ],
                ondelete="CASCADE",
            ),
        )
    op.execute(
        """
        create index if not exists idx_analysis_conversation_states_recent
        on analysis_conversation_states (tenant_id, user_id, conversation_id, state_id desc)
        """
    )
    op.execute(
        """
        create index if not exists idx_analysis_conversation_states_message
        on analysis_conversation_states (tenant_id, user_id, conversation_id, message_id)
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists idx_analysis_conversation_states_message")
    op.execute("drop index if exists idx_analysis_conversation_states_recent")
    op.drop_table("analysis_conversation_states")
