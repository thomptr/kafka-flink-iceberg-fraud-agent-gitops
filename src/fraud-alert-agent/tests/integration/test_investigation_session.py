"""Integration tests for the full investigation session lifecycle.

These tests use a real Postgres container via testcontainers (same pattern as
test_alert_pipeline.py). They are skipped if INTEGRATION_TESTS=1 is not set.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION_TESTS") != "1",
    reason="Integration tests require INTEGRATION_TESTS=1 and a running Postgres",
)


@pytest.fixture(scope="module")
async def db_session():
    from app.db.base import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_session_lifecycle():
    """Open session → add turns → conclude → verify all rows."""
    from app.db.base import AsyncSessionLocal
    from app.db.models import FraudAlert, InvestigationSession, SessionTurn, InvestigationConclusion
    from app.services import session_service
    from sqlalchemy import select

    alert_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        alert = FraudAlert(
            id=alert_id,
            transaction_id=f"txn-{uuid.uuid4()}",
            user_id=1,
            amount=100.0,
            fraud_probability=0.9,
            severity="critical",
            status="open",
            sla_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        db.add(alert)
        await db.commit()

    session_obj = await session_service.create_session(alert_id=alert_id, analyst_id="tester")
    assert session_obj.status == "active"

    turn1 = await session_service.create_turn(
        session_id=str(session_obj.id),
        analyst_input="Why was this flagged?",
        agent_response="High velocity.",
        tool_calls=["get_transaction_details"],
    )
    assert turn1.turn_number == 1

    turn2 = await session_service.create_turn(
        session_id=str(session_obj.id),
        analyst_input="Show me history",
        agent_response="10 recent transactions.",
        tool_calls=["get_user_history"],
    )
    assert turn2.turn_number == 2

    turns = await session_service.list_turns(str(session_obj.id))
    assert len(turns) == 2
    assert [t.turn_number for t in turns] == [1, 2]

    conclusion = await session_service.conclude_session(
        session_id=str(session_obj.id),
        outcome="confirmed_fraud",
        notes="Merchant blocklist match.",
        analyst_id="tester",
    )
    assert conclusion.outcome == "confirmed_fraud"

    refreshed = await session_service.get_session(str(session_obj.id))
    assert refreshed.status == "concluded"


@pytest.mark.asyncio
async def test_concurrent_conclusion_returns_409():
    """Two sessions for the same alert: second conclude raises ConflictError."""
    from app.db.base import AsyncSessionLocal
    from app.db.models import FraudAlert
    from app.services import session_service

    alert_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        alert = FraudAlert(
            id=alert_id,
            transaction_id=f"txn-{uuid.uuid4()}",
            user_id=2,
            amount=200.0,
            fraud_probability=0.88,
            severity="high",
            status="open",
            sla_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        db.add(alert)
        await db.commit()

    session1 = await session_service.create_session(alert_id=alert_id, analyst_id="a1")
    session2 = await session_service.create_session(alert_id=alert_id, analyst_id="a2")

    await session_service.conclude_session(
        session_id=str(session1.id),
        outcome="confirmed_fraud",
        notes=None,
        analyst_id="a1",
    )

    with pytest.raises(session_service.ConflictError):
        await session_service.conclude_session(
            session_id=str(session2.id),
            outcome="false_positive",
            notes=None,
            analyst_id="a2",
        )


@pytest.mark.asyncio
async def test_turn_tool_calls_persisted():
    """Assert tool_calls JSONB field is persisted and returned correctly."""
    from app.services import session_service
    from app.db.base import AsyncSessionLocal
    from app.db.models import FraudAlert

    alert_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        alert = FraudAlert(
            id=alert_id,
            transaction_id=f"txn-{uuid.uuid4()}",
            user_id=3,
            amount=50.0,
            fraud_probability=0.7,
            severity="medium",
            status="open",
            sla_deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        db.add(alert)
        await db.commit()

    session_obj = await session_service.create_session(alert_id=alert_id, analyst_id="tester")
    turn = await session_service.create_turn(
        session_id=str(session_obj.id),
        analyst_input="Show feature values",
        agent_response="feature_x: 0.92, feature_y: 1.2",
        tool_calls=["get_feature_context", "pattern_lookup_tool"],
    )
    turns = await session_service.list_turns(str(session_obj.id))
    assert turns[0].tool_calls == ["get_feature_context", "pattern_lookup_tool"]
