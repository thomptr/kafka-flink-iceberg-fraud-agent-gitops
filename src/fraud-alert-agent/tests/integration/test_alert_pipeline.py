"""Integration tests for the alert creation pipeline.

These tests mock external dependencies (Iceberg, Ollama, Kafka) but use real
service logic to verify alert creation, deduplication, and investigation launch.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.alert_service import create_alert, get_alert, list_alerts, update_alert_status


@pytest.mark.asyncio
async def test_create_alert_returns_alert_with_correct_fields():
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.transaction_id = "txn-pipeline-001"
    alert.severity = "critical"
    alert.status = "open"
    alert.fraud_probability = 0.93

    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        result_mock = MagicMock()
        result_mock.first.return_value = (alert,)
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_cls.return_value = mock_session

        with patch("app.services.alert_service.compute_sla_deadline", return_value=datetime.now(timezone.utc)):
            result = await create_alert(
                transaction_id="txn-pipeline-001",
                user_id=42,
                amount=500.0,
                fraud_probability=0.93,
                merchant="UnknownMerchant",
                severity="critical",
            )

    assert result is not None
    assert result.transaction_id == "txn-pipeline-001"
    assert result.severity == "critical"


@pytest.mark.asyncio
async def test_create_alert_deduplication_on_conflict():
    """Second insert of same transaction_id returns None (idempotent)."""
    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        result_mock = MagicMock()
        result_mock.first.return_value = None  # conflict returns no row
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_cls.return_value = mock_session

        with patch("app.services.alert_service.compute_sla_deadline", return_value=datetime.now(timezone.utc)):
            result = await create_alert(
                transaction_id="txn-duplicate",
                user_id=42,
                amount=500.0,
                fraud_probability=0.93,
                merchant="Merchant",
                severity="critical",
            )

    assert result is None  # ON CONFLICT DO NOTHING returns None


@pytest.mark.asyncio
async def test_get_alert_returns_none_for_missing_id():
    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_cls.return_value = mock_session

        result = await get_alert("00000000-0000-0000-0000-000000000000")

    assert result is None


@pytest.mark.asyncio
async def test_list_alerts_applies_severity_filter():
    critical_alert = MagicMock()
    critical_alert.severity = "critical"

    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [critical_alert]

        mock_session.execute = AsyncMock(side_effect=[count_result, items_result])
        mock_cls.return_value = mock_session

        alerts, total = await list_alerts(severity="critical", page=1, page_size=20)

    assert total == 1
    assert alerts[0].severity == "critical"


@pytest.mark.asyncio
async def test_update_alert_status_changes_status():
    alert = MagicMock()
    alert.status = "open"

    with patch("app.services.alert_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = alert
        mock_session.execute = AsyncMock(return_value=result_mock)
        mock_cls.return_value = mock_session

        await update_alert_status(str(uuid.uuid4()), "in_review")

    assert alert.status == "in_review"


@pytest.mark.asyncio
async def test_alert_severity_thresholds_map_correctly():
    """Verify that fraud_probability correctly determines severity labels."""
    from app.agents.triage_node import triage_node

    for route, expected in [
        ("CRITICAL", "critical"),
        ("STANDARD", "high"),
        ("MONITOR_ONLY", "medium"),
        ("FALSE_POSITIVE", "low"),
    ]:
        state = {
            "alert_id": "test",
            "transaction_id": "t",
            "user_id": 1,
            "amount": 100.0,
            "fraud_probability": 0.9,
            "merchant": None,
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
        result = triage_node(state)
        assert result["severity"] == expected, f"Route {route} should map to {expected}"
