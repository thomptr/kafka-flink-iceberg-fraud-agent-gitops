"""Integration tests for human decision flow: approve, override, SLA breach."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_approve_sets_alert_status_to_resolved(app_client):
    alert_id = str(uuid.uuid4())
    alert = MagicMock()
    alert.id = uuid.UUID(alert_id)
    alert.status = "open"
    alert.updated_at = datetime.now(timezone.utc)

    added_objects = []

    with patch("app.api.decisions.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)

        alert_result = MagicMock()
        alert_result.scalars.return_value.first.return_value = alert
        mock_session.execute = AsyncMock(return_value=alert_result)
        mock_cls.return_value = mock_session

        from tests.conftest import TEST_HEADERS
        resp = app_client.post(
            f"/api/v1/alerts/{alert_id}/decisions",
            headers=TEST_HEADERS,
            json={"actor": "analyst@example.com", "action": "approve", "outcome": "block"},
        )

    assert resp.status_code == 200
    assert alert.status == "resolved"


@pytest.mark.asyncio
async def test_override_with_reason_persists_reason(app_client):
    alert_id = str(uuid.uuid4())
    alert = MagicMock()
    alert.id = uuid.UUID(alert_id)
    alert.status = "open"
    alert.updated_at = datetime.now(timezone.utc)

    added_objects = []

    with patch("app.api.decisions.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)

        alert_result = MagicMock()
        alert_result.scalars.return_value.first.return_value = alert
        mock_session.execute = AsyncMock(return_value=alert_result)
        mock_cls.return_value = mock_session

        from tests.conftest import TEST_HEADERS
        resp = app_client.post(
            f"/api/v1/alerts/{alert_id}/decisions",
            headers=TEST_HEADERS,
            json={
                "actor": "senior@example.com",
                "action": "override",
                "outcome": "monitor",
                "reason": "Customer confirmed travelling abroad",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reason"] == "Customer confirmed travelling abroad"
    assert alert.status == "resolved"


@pytest.mark.asyncio
async def test_audit_trail_immutability_no_update_delete_routes(app_client):
    """Verify no HTTP routes expose UPDATE/DELETE on decision_events."""
    from tests.conftest import TEST_HEADERS

    alert_id = str(uuid.uuid4())

    # PUT /decisions should not exist
    resp = app_client.put(f"/api/v1/alerts/{alert_id}/decisions", headers=TEST_HEADERS, json={})
    assert resp.status_code in (404, 405)

    # DELETE /decisions should not exist
    resp = app_client.delete(f"/api/v1/alerts/{alert_id}/decisions", headers=TEST_HEADERS)
    assert resp.status_code in (404, 405)

    decision_id = str(uuid.uuid4())
    resp = app_client.delete(
        f"/api/v1/alerts/{alert_id}/decisions/{decision_id}", headers=TEST_HEADERS
    )
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_sla_worker_escalates_breached_alerts():
    import asyncio
    from app.workers.sla_worker import _sweep

    breached_alert = MagicMock()
    breached_alert.id = uuid.uuid4()
    breached_alert.status = "open"
    breached_alert.severity = "critical"
    breached_alert.sla_deadline = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc)

    reloaded_alert = MagicMock()
    reloaded_alert.status = "open"
    reloaded_alert.final_action = None
    reloaded_alert.updated_at = datetime.now(timezone.utc)

    added_objects = []

    with patch("app.services.sla_service.get_breached_alerts", AsyncMock(return_value=[breached_alert])), \
         patch("app.services.notification_service.send_slack_notification", AsyncMock()), \
         patch("app.tools.kafka_producer_tool.publish_kafka_event") as mock_kafka, \
         patch("app.workers.sla_worker.AsyncSessionLocal") as mock_cls:

        mock_kafka.invoke = MagicMock(return_value={"delivered": True})

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.add = lambda obj: added_objects.append(obj)

        alert_result = MagicMock()
        alert_result.scalars.return_value.first.return_value = reloaded_alert
        mock_session.execute = AsyncMock(return_value=alert_result)
        mock_cls.return_value = mock_session

        await _sweep()

    assert reloaded_alert.status == "sla_breached"
    from app.db.models import DecisionEvent
    events = [o for o in added_objects if isinstance(o, DecisionEvent)]
    assert any(e.actor == "sla_bot" and e.action == "escalate" for e in events)
