import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_agent_test")
os.environ.setdefault("FRAUD_API_KEY", "test-api-key")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")

TEST_API_KEY = "test-api-key"
TEST_HEADERS = {"X-API-Key": TEST_API_KEY}


def _make_alert(
    alert_id: str | None = None,
    transaction_id: str = "txn-001",
    user_id: int = 42,
    amount: float = 500.00,
    fraud_probability: float = 0.92,
    severity: str = "critical",
    status: str = "open",
    recommended_action: str | None = "block",
    final_action: str | None = None,
    summary: str | None = "Suspicious transaction pattern detected.",
    merchant: str | None = "UnknownMerchant",
) -> MagicMock:
    alert = MagicMock()
    alert.id = uuid.UUID(alert_id) if alert_id else uuid.uuid4()
    alert.transaction_id = transaction_id
    alert.user_id = user_id
    alert.amount = amount
    alert.fraud_probability = fraud_probability
    alert.severity = severity
    alert.status = status
    alert.recommended_action = recommended_action
    alert.final_action = final_action
    alert.summary = summary
    alert.merchant = merchant
    alert.sla_deadline = datetime(2026, 4, 25, 1, 0, 0, tzinfo=timezone.utc)
    alert.created_at = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc)
    alert.updated_at = datetime(2026, 4, 25, 0, 1, 0, tzinfo=timezone.utc)
    alert.investigation_id = None
    return alert


def _make_decision(
    alert_id: str,
    actor: str = "analyst@example.com",
    action: str = "approve",
    outcome: str | None = "block",
    reason: str | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.alert_id = uuid.UUID(alert_id)
    event.actor = actor
    event.action = action
    event.outcome = outcome
    event.reason = reason
    event.created_at = datetime(2026, 4, 25, 0, 5, 0, tzinfo=timezone.utc)
    return event


@pytest.fixture
def test_alert_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_alert(test_alert_id) -> MagicMock:
    return _make_alert(alert_id=test_alert_id)


@pytest.fixture
def app_client():
    with (
        patch("app.agents.graph.build_graph", new_callable=AsyncMock),
        patch("app.workers.alert_monitor.run_alert_monitor", new_callable=AsyncMock),
        patch("app.workers.sla_worker.run_sla_worker", new_callable=AsyncMock),
        patch("app.tracing.setup_tracing"),
        patch("app.tracing.shutdown_tracing"),
        patch("app.db.base.engine"),
    ):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=True)
        yield client
