"""add investigation sessions tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analyst_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["alert_id"], ["fraud_alerts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investigation_sessions_alert_id", "investigation_sessions", ["alert_id"])
    op.create_index(
        "ix_investigation_sessions_analyst_status",
        "investigation_sessions",
        ["analyst_id", "status"],
    )
    op.create_index("ix_investigation_sessions_last_active", "investigation_sessions", ["last_active_at"])

    op.create_table(
        "session_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("analyst_input", sa.Text(), nullable=False),
        sa.Column("agent_response", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["investigation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn_number", name="uq_session_turns_session_turn"),
    )
    op.create_index("ix_session_turns_session_id", "session_turns", ["session_id"])

    op.create_table(
        "investigation_conclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("analyst_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["alert_id"], ["fraud_alerts.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["investigation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id", name="uq_investigation_conclusions_alert_id"),
    )
    op.create_index(
        "ix_investigation_conclusions_session_id", "investigation_conclusions", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_investigation_conclusions_session_id", table_name="investigation_conclusions")
    op.drop_table("investigation_conclusions")
    op.drop_index("ix_session_turns_session_id", table_name="session_turns")
    op.drop_table("session_turns")
    op.drop_index("ix_investigation_sessions_last_active", table_name="investigation_sessions")
    op.drop_index("ix_investigation_sessions_analyst_status", table_name="investigation_sessions")
    op.drop_index("ix_investigation_sessions_alert_id", table_name="investigation_sessions")
    op.drop_table("investigation_sessions")
