import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.triage_node import triage_node


def _make_state(route: str = "CRITICAL") -> dict:
    return {
        "alert_id": "test-alert-001",
        "transaction_id": "txn-001",
        "user_id": 42,
        "amount": 500.0,
        "fraud_probability": 0.93,
        "merchant": "UnknownMerchant",
        "route": route,
        "transaction_history": [],
        "feature_values": None,
        "pattern_stats": None,
        "snapshot_ids": {},
        "severity": "",
        "sla_deadline": None,
        "explanation": "",
        "evidence": [],
        "recommended_action": "",
        "confidence": None,
        "final_action": "",
        "rule_matched": "",
        "iceberg_snapshot_id": None,
        "kafka_delivered": False,
        "tool_errors": [],
        "error": None,
    }


def test_triage_node_classifies_critical():
    result = triage_node(_make_state(route="CRITICAL"))
    assert result["severity"] == "critical"


def test_triage_node_classifies_standard_as_high():
    result = triage_node(_make_state(route="STANDARD"))
    assert result["severity"] == "high"


def test_triage_node_classifies_monitor_only_as_medium():
    result = triage_node(_make_state(route="MONITOR_ONLY"))
    assert result["severity"] == "medium"


def test_triage_node_classifies_false_positive_as_low():
    result = triage_node(_make_state(route="FALSE_POSITIVE"))
    assert result["severity"] == "low"


def test_triage_node_returns_sla_deadline():
    result = triage_node(_make_state(route="CRITICAL"))
    assert result.get("sla_deadline") is not None


@pytest.mark.asyncio
async def test_investigation_timeout_sets_timed_out_status():
    """Verify that when the graph exceeds timeout, investigation is marked timed_out."""

    async def slow_graph(*args, **kwargs):
        await asyncio.sleep(999)

    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.investigation_id = None
    alert.updated_at = datetime.now(timezone.utc)

    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.status = "running"

    with patch("app.services.investigation_service.compiled_graph") as mock_graph, \
         patch("app.services.investigation_service.AsyncSessionLocal") as mock_cls, \
         patch("app.agents.trace_callbacks.FraudGraphTraceCallback") as mock_cb:

        mock_graph.ainvoke = slow_graph

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        inv_result = MagicMock()
        inv_result.scalars.return_value.first.return_value = inv
        mock_session.execute = AsyncMock(return_value=inv_result)
        mock_cls.return_value = mock_session

        mock_cb_instance = MagicMock()
        mock_cb_instance.end_root_span = MagicMock()
        mock_cb.return_value = mock_cb_instance

        with patch("app.services.investigation_service._INVESTIGATION_TIMEOUT", 0.05):
            from app.services.investigation_service import start_investigation
            await start_investigation(alert, _make_state())

        # After timeout, the commit should have been called to persist timed_out status
        assert mock_session.commit.called


@pytest.mark.asyncio
async def test_investigation_timeout_creates_escalation_decision_event():
    """Verify that a timeout creates a DecisionEvent(actor=agent, action=escalate)."""

    async def slow_graph(*args, **kwargs):
        await asyncio.sleep(999)

    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.investigation_id = None
    alert.updated_at = datetime.now(timezone.utc)

    inv = MagicMock()
    inv.status = "running"

    added_objects = []

    with patch("app.services.investigation_service.compiled_graph") as mock_graph, \
         patch("app.services.investigation_service.AsyncSessionLocal") as mock_cls, \
         patch("app.agents.trace_callbacks.FraudGraphTraceCallback") as mock_cb:

        mock_graph.ainvoke = slow_graph

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)

        inv_result = MagicMock()
        inv_result.scalars.return_value.first.return_value = inv
        mock_session.execute = AsyncMock(return_value=inv_result)
        mock_cls.return_value = mock_session

        mock_cb_instance = MagicMock()
        mock_cb_instance.end_root_span = MagicMock()
        mock_cb.return_value = mock_cb_instance

        with patch("app.services.investigation_service._INVESTIGATION_TIMEOUT", 0.05):
            from app.services.investigation_service import start_investigation
            await start_investigation(alert, _make_state())

        from app.db.models import DecisionEvent
        decision_events = [o for o in added_objects if isinstance(o, DecisionEvent)]
        assert len(decision_events) >= 1
        escalation_event = decision_events[0]
        assert escalation_event.action == "escalate"
        assert escalation_event.actor == "agent"
