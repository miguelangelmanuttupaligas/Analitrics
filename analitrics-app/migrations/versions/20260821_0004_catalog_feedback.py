from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_catalog_feedback"
down_revision = "0003_conversation_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("analysis_catalog_feedback"):
        op.create_table(
            "analysis_catalog_feedback",
            sa.Column("feedback_id", sa.BigInteger(), sa.Identity(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("conversation_id", sa.Text(), nullable=False),
            sa.Column("step", sa.Integer(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("step between 1 and 6", name="ck_analysis_catalog_feedback_step"),
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
        create index if not exists idx_analysis_catalog_feedback_conversation
        on analysis_catalog_feedback (tenant_id, user_id, conversation_id, step)
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists idx_analysis_catalog_feedback_conversation")
    op.drop_table("analysis_catalog_feedback")
