import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class FraudAlert(Base):
    __tablename__ = "fraud_alerts"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_fraud_alerts_transaction_id"),
        Index("idx_fraud_alerts_status_severity", "status", "severity"),
        Index("idx_fraud_alerts_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    merchant: Mapped[str | None] = mapped_column(Text)
    fraud_probability: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    recommended_action: Mapped[str | None] = mapped_column(Text)
    final_action: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    sla_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=True
    )

    investigation: Mapped["Investigation | None"] = relationship(
        "Investigation", back_populates="alert", foreign_keys=[investigation_id]
    )
    decisions: Mapped[list["DecisionEvent"]] = relationship("DecisionEvent", back_populates="alert")


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fraud_alerts.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    reasoning: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    alert: Mapped["FraudAlert"] = relationship(
        "FraudAlert", back_populates="investigation", foreign_keys="FraudAlert.investigation_id"
    )
    steps: Mapped[list["InvestigationStep"]] = relationship(
        "InvestigationStep", back_populates="investigation", order_by="InvestigationStep.step_order"
    )


class InvestigationStep(Base):
    __tablename__ = "investigation_steps"
    __table_args__ = (
        Index("idx_investigation_steps_investigation_id", "investigation_id", "step_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    investigation: Mapped["Investigation"] = relationship("Investigation", back_populates="steps")


class DecisionEvent(Base):
    __tablename__ = "decision_events"
    __table_args__ = (
        Index("idx_decision_events_alert_id", "alert_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fraud_alerts.id"), nullable=False
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    alert: Mapped["FraudAlert"] = relationship("FraudAlert", back_populates="decisions")


class InvestigationSession(Base):
    __tablename__ = "investigation_sessions"
    __table_args__ = (
        Index("ix_investigation_sessions_alert_id", "alert_id"),
        Index("ix_investigation_sessions_analyst_status", "analyst_id", "status"),
        Index("ix_investigation_sessions_last_active", "last_active_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fraud_alerts.id"), nullable=False
    )
    analyst_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    turns: Mapped[list["SessionTurn"]] = relationship(
        "SessionTurn", back_populates="session", order_by="SessionTurn.turn_number"
    )
    conclusion: Mapped["InvestigationConclusion | None"] = relationship(
        "InvestigationConclusion", back_populates="session", uselist=False
    )


class SessionTurn(Base):
    __tablename__ = "session_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_number", name="uq_session_turns_session_turn"),
        Index("ix_session_turns_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_sessions.id"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    analyst_input: Mapped[str] = mapped_column(Text, nullable=False)
    agent_response: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped["InvestigationSession"] = relationship("InvestigationSession", back_populates="turns")


class InvestigationConclusion(Base):
    __tablename__ = "investigation_conclusions"
    __table_args__ = (
        UniqueConstraint("alert_id", name="uq_investigation_conclusions_alert_id"),
        Index("ix_investigation_conclusions_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_sessions.id"), nullable=False
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fraud_alerts.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyst_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped["InvestigationSession"] = relationship(
        "InvestigationSession", back_populates="conclusion"
    )


class AlertMonitorCursor(Base):
    __tablename__ = "alert_monitor_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_snapshot_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
