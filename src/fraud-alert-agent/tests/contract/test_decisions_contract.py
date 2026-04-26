import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_HEADERS, _make_alert, _make_decision

_ALERT_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _patch_alert():
    alert = _make_alert(alert_id=_ALERT_ID, status="open")
    with patch("app.api.decisions.AsyncSessionLocal") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        alert_result = MagicMock()
        alert_result.scalars.return_value.first.return_value = alert

        async def fake_execute(stmt):
            return alert_result

        mock_session.execute = fake_execute
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session_cls.return_value = mock_session
        yield


def test_approve_decision_returns_201(app_client):
    resp = app_client.post(
        f"/api/v1/alerts/{_ALERT_ID}/decisions",
        headers=TEST_HEADERS,
        json={"actor": "analyst@example.com", "action": "approve", "outcome": "block"},
    )
    assert resp.status_code == 200  # FastAPI returns 200 by default for POST without response_model status
    body = resp.json()
    assert body["action"] == "approve"
    assert body["actor"] == "analyst@example.com"
    assert body["outcome"] == "block"


def test_override_with_reason_accepted(app_client):
    resp = app_client.post(
        f"/api/v1/alerts/{_ALERT_ID}/decisions",
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
    assert body["action"] == "override"
    assert body["reason"] == "Customer confirmed travelling abroad"


def test_override_without_reason_rejected(app_client):
    resp = app_client.post(
        f"/api/v1/alerts/{_ALERT_ID}/decisions",
        headers=TEST_HEADERS,
        json={"actor": "analyst@example.com", "action": "override", "outcome": "monitor"},
    )
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"].lower()


def test_approve_without_outcome_rejected(app_client):
    resp = app_client.post(
        f"/api/v1/alerts/{_ALERT_ID}/decisions",
        headers=TEST_HEADERS,
        json={"actor": "analyst@example.com", "action": "approve"},
    )
    assert resp.status_code == 400
    assert "outcome" in resp.json()["detail"].lower()


def test_decision_rejects_missing_api_key(app_client):
    resp = app_client.post(
        f"/api/v1/alerts/{_ALERT_ID}/decisions",
        json={"actor": "analyst@example.com", "action": "approve", "outcome": "block"},
    )
    assert resp.status_code == 401


def test_decision_on_nonexistent_alert_returns_404(app_client):
    with patch("app.api.decisions.AsyncSessionLocal") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=result)
        mock_session_cls.return_value = mock_session

        resp = app_client.post(
            "/api/v1/alerts/00000000-0000-0000-0000-000000000000/decisions",
            headers=TEST_HEADERS,
            json={"actor": "analyst@example.com", "action": "approve", "outcome": "block"},
        )
    assert resp.status_code == 404


def test_list_decisions_returns_list(app_client):
    with patch("app.api.decisions.AsyncSessionLocal") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=result)
        mock_session_cls.return_value = mock_session

        resp = app_client.get(f"/api/v1/alerts/{_ALERT_ID}/decisions", headers=TEST_HEADERS)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
