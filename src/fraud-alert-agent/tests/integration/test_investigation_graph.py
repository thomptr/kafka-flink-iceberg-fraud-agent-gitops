"""Integration tests for investigation graph: step recording, idempotency, timeout."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.investigation_service import _handle_timeout, _finalize_investigation


@pytest.mark.asyncio
async def test_finalize_investigation_sets_completed_status():
    inv = MagicMock()
    inv.status = "running"

    alert = MagicMock()
    alert.summary = None
    alert.recommended_action = None
    alert.final_action = None

    final_state = {
        "explanation": "Suspicious transaction: velocity spike detected.",
        "recommended_action": "block",
        "final_action": "block",
        "confidence": 0.92,
        "evidence": [{"rank": 1, "type": "transaction_history", "description": "8 txns in 5min", "weight": "high"}],
    }

    with patch("app.services.investigation_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        inv_result = MagicMock()
        inv_result.scalars.return_value.first.return_value = inv
        alert_result = MagicMock()
        alert_result.scalars.return_value.first.return_value = alert

        mock_session.execute = AsyncMock(side_effect=[inv_result, alert_result])
        mock_cls.return_value = mock_session

        await _finalize_investigation(
            str(uuid.uuid4()), uuid.uuid4(), final_state, datetime.now(timezone.utc)
        )

    assert inv.status == "completed"
    assert alert.summary == "Suspicious transaction: velocity spike detected."
    assert alert.recommended_action == "block"


@pytest.mark.asyncio
async def test_handle_timeout_sets_timed_out_and_creates_escalation():
    inv = MagicMock()
    inv.status = "running"

    added_objects = []

    with patch("app.services.investigation_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)

        inv_result = MagicMock()
        inv_result.scalars.return_value.first.return_value = inv
        mock_session.execute = AsyncMock(return_value=inv_result)
        mock_cls.return_value = mock_session

        alert_id = uuid.uuid4()
        await _handle_timeout(str(uuid.uuid4()), alert_id)

    assert inv.status == "timed_out"
    from app.db.models import DecisionEvent
    decision_events = [o for o in added_objects if isinstance(o, DecisionEvent)]
    assert any(e.action == "escalate" and e.actor == "agent" for e in decision_events)


@pytest.mark.asyncio
async def test_investigation_idempotency_second_call_returns_none():
    """create_alert returns None on duplicate transaction_id (ON CONFLICT DO NOTHING)."""
    from app.services.alert_service import create_alert

    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls, \
         patch("app.services.alert_service.compute_sla_deadline", return_value=datetime.now(timezone.utc)):

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        result_mock = MagicMock()
        result_mock.first.return_value = None  # conflict
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_cls.return_value = mock_session

        result = await create_alert(
            transaction_id="txn-dupe-test",
            user_id=1,
            amount=100.0,
            fraud_probability=0.88,
            merchant="Merchant",
            severity="critical",
        )

    assert result is None, "Duplicate transaction_id must return None"


@pytest.mark.asyncio
async def test_investigation_steps_are_ordered():
    """Verify step records are created with sequential step_order values."""
    from app.services.investigation_service import _record_steps

    added_steps = []

    with patch("app.services.investigation_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_steps.append(obj)
        mock_cls.return_value = mock_session

        final_state = {
            "route": "CRITICAL",
            "snapshot_ids": {},
            "tool_errors": [],
            "recommended_action": "block",
            "confidence": 0.9,
            "explanation": "Test",
            "final_action": "block",
            "rule_matched": "high_velocity",
            "kafka_delivered": True,
            "iceberg_snapshot_id": 12345,
        }

        await _record_steps(str(uuid.uuid4()), final_state, datetime.now(timezone.utc))

    from app.db.models import InvestigationStep
    steps = [s for s in added_steps if isinstance(s, InvestigationStep)]
    step_orders = [s.step_order for s in steps]
    assert step_orders == sorted(step_orders), "Steps must be in sequential order"
    assert len(steps) > 0
