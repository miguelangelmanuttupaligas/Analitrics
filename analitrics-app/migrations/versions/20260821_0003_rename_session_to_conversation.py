from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_conversation_id"
down_revision = "0002_invalidation"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    sessions = _columns("analysis_catalog_sessions")
    profiles = _columns("analysis_catalog_profiles")

    if "session_id" in sessions and "conversation_id" in sessions:
        op.drop_column("analysis_catalog_sessions", "conversation_id")
        sessions.remove("conversation_id")

    if "session_id" in sessions:
        op.alter_column("analysis_catalog_sessions", "session_id", new_column_name="conversation_id")

    if "session_id" in profiles:
        op.alter_column("analysis_catalog_profiles", "session_id", new_column_name="conversation_id")

    op.execute("drop index if exists idx_analysis_catalog_profiles_active")
    op.execute(
        """
        create index if not exists idx_analysis_catalog_profiles_active
        on analysis_catalog_profiles (tenant_id, user_id, conversation_id, active)
        """
    )


def downgrade() -> None:
    sessions = _columns("analysis_catalog_sessions")
    profiles = _columns("analysis_catalog_profiles")

    op.execute("drop index if exists idx_analysis_catalog_profiles_active")

    if "conversation_id" in profiles:
        op.alter_column("analysis_catalog_profiles", "conversation_id", new_column_name="session_id")

    if "conversation_id" in sessions:
        op.alter_column("analysis_catalog_sessions", "conversation_id", new_column_name="session_id")
        op.add_column("analysis_catalog_sessions", sa.Column("conversation_id", sa.Text(), nullable=True))
        op.execute("update analysis_catalog_sessions set conversation_id = session_id")

    op.execute(
        """
        create index if not exists idx_analysis_catalog_profiles_active
        on analysis_catalog_profiles (tenant_id, user_id, session_id, active)
        """
    )
