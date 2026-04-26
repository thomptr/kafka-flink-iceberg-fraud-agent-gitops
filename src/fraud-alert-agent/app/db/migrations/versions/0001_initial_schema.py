"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create fraud_alerts without the investigation_id FK first (circular dependency)
    op.create_table(
        "fraud_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("fraud_probability", sa.Numeric(5, 4), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("final_action", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_fraud_alerts_transaction_id"),
    )
    op.create_index("idx_fraud_alerts_status_severity", "fraud_alerts", ["status", "severity"])
    op.create_index("idx_fraud_alerts_created_at", "fraud_alerts", ["created_at"])

    op.create_table(
        "investigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["alert_id"], ["fraud_alerts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id"),
    )

    # Now add the FK from fraud_alerts.investigation_id → investigations.id
    op.create_foreign_key(
        "fk_fraud_alerts_investigation_id",
        "fraud_alerts", "investigations",
        ["investigation_id"], ["id"],
    )

    op.create_table(
        "investigation_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_investigation_steps_investigation_id",
        "investigation_steps",
        ["investigation_id", "step_order"],
    )

    op.create_table(
        "decision_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["alert_id"], ["fraud_alerts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_decision_events_alert_id", "decision_events", ["alert_id", "created_at"])

    op.create_table(
        "alert_monitor_cursor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("alert_monitor_cursor")
    op.drop_index("idx_decision_events_alert_id", table_name="decision_events")
    op.drop_table("decision_events")
    op.drop_index("idx_investigation_steps_investigation_id", table_name="investigation_steps")
    op.drop_table("investigation_steps")
    op.drop_constraint("fk_fraud_alerts_investigation_id", "fraud_alerts", type_="foreignkey")
    op.drop_table("investigations")
    op.drop_index("idx_fraud_alerts_status_severity", table_name="fraud_alerts")
    op.drop_index("idx_fraud_alerts_created_at", table_name="fraud_alerts")
    op.drop_table("fraud_alerts")
