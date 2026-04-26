"""Contract tests for investigation session endpoints against the OpenAPI spec."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_HEADERS


def _make_session(session_id=None, alert_id=None, status="active"):
    s = MagicMock()
    s.id = uuid.UUID(session_id) if session_id else uuid.uuid4()
    s.alert_id = uuid.UUID(alert_id) if alert_id else uuid.uuid4()
    s.analyst_id = "analyst@example.com"
    s.status = status
    s.created_at = datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc)
    s.last_active_at = datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc)
    s.updated_at = datetime(2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc)
    return s


def _make_turn(session_id=None, turn_number=1):
    t = MagicMock()
    t.id = uuid.uuid4()
    t.session_id = uuid.UUID(session_id) if session_id else uuid.uuid4()
    t.turn_number = turn_number
    t.analyst_input = "Why was this flagged?"
    t.agent_response = "The transaction was flagged because of unusual amount velocity."
    t.tool_calls = ["get_transaction_details"]
    t.created_at = datetime(2026, 4, 26, 10, 0, 1, tzinfo=timezone.utc)
    return t


def _make_conclusion(session_id=None, alert_id=None):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.session_id = uuid.UUID(session_id) if session_id else uuid.uuid4()
    c.alert_id = uuid.UUID(alert_id) if alert_id else uuid.uuid4()
    c.outcome = "confirmed_fraud"
    c.notes = "Merchant on blocklist."
    c.analyst_id = "analyst@example.com"
    c.created_at = datetime(2026, 4, 26, 10, 5, 0, tzinfo=timezone.utc)
    return c


# --- POST /api/v1/alerts/{alert_id}/investigation-sessions ---

@patch("app.api.sessions.session_service.create_session", new_callable=AsyncMock)
@patch("app.api.sessions.session_service.create_turn", new_callable=AsyncMock)
@patch("app.api.sessions.get_session_graph")
@patch("app.services.alert_service.get_alert", new_callable=AsyncMock)
def test_open_session_201(mock_get_alert, mock_graph_factory, mock_create_turn, mock_create_session, app_client, sample_alert):
    alert_id = str(sample_alert.id)
    session = _make_session(alert_id=alert_id)
    turn = _make_turn(session_id=str(session.id))

    mock_get_alert.return_value = sample_alert
    mock_create_session.return_value = session
    mock_create_turn.return_value = turn

    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="Initial explanation.")]})
    mock_graph_factory.return_value = graph

    resp = app_client.post(
        f"/api/v1/alerts/{alert_id}/investigation-sessions",
        headers={**TEST_HEADERS, "X-Analyst-Id": "analyst@example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    assert "initial_turn" in data
    assert data["status"] == "active"


@patch("app.services.alert_service.get_alert", new_callable=AsyncMock)
def test_open_session_404_unknown_alert(mock_get_alert, app_client):
    mock_get_alert.return_value = None
    resp = app_client.post(
        f"/api/v1/alerts/{uuid.uuid4()}/investigation-sessions",
        headers={**TEST_HEADERS, "X-Analyst-Id": "analyst@example.com"},
    )
    assert resp.status_code == 404


# --- POST /api/v1/investigation-sessions/{session_id}/turns ---

@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
@patch("app.api.sessions.session_service.create_turn", new_callable=AsyncMock)
@patch("app.api.sessions.get_session_graph")
def test_create_turn_200(mock_graph_factory, mock_create_turn, mock_get_session, app_client):
    session = _make_session()
    turn = _make_turn(session_id=str(session.id), turn_number=2)
    mock_get_session.return_value = session
    mock_create_turn.return_value = turn

    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"messages": [MagicMock(content="Follow-up answer.")]})
    mock_graph_factory.return_value = graph

    resp = app_client.post(
        f"/api/v1/investigation-sessions/{session.id}/turns",
        headers=TEST_HEADERS,
        json={"question": "What was the merchant?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "turn_number" in data
    assert "agent_response" in data


@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
def test_create_turn_409_concluded(mock_get_session, app_client):
    session = _make_session(status="concluded")
    mock_get_session.return_value = session
    resp = app_client.post(
        f"/api/v1/investigation-sessions/{session.id}/turns",
        headers=TEST_HEADERS,
        json={"question": "Any question"},
    )
    assert resp.status_code == 409


@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
def test_create_turn_404_unknown_session(mock_get_session, app_client):
    from app.services.session_service import SessionNotFoundError
    mock_get_session.side_effect = SessionNotFoundError("missing")
    resp = app_client.post(
        f"/api/v1/investigation-sessions/{uuid.uuid4()}/turns",
        headers=TEST_HEADERS,
        json={"question": "x"},
    )
    assert resp.status_code == 404


# --- POST /api/v1/investigation-sessions/{session_id}/conclude ---

@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
@patch("app.api.sessions.session_service.conclude_session", new_callable=AsyncMock)
@patch("app.services.alert_service.update_alert_status", new_callable=AsyncMock)
def test_conclude_201(mock_update_status, mock_conclude, mock_get_session, app_client):
    session = _make_session()
    conclusion = _make_conclusion(session_id=str(session.id), alert_id=str(session.alert_id))
    mock_get_session.return_value = session
    mock_conclude.return_value = conclusion
    mock_update_status.return_value = None

    resp = app_client.post(
        f"/api/v1/investigation-sessions/{session.id}/conclude",
        headers=TEST_HEADERS,
        json={"outcome": "confirmed_fraud", "notes": "Merchant on blocklist."},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["outcome"] == "confirmed_fraud"
    assert "conclusion_id" in data


@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
@patch("app.api.sessions.session_service.conclude_session", new_callable=AsyncMock)
def test_conclude_409_conflict(mock_conclude, mock_get_session, app_client):
    from app.services.session_service import ConflictError
    session = _make_session()
    mock_get_session.return_value = session
    existing = _make_conclusion()
    mock_conclude.side_effect = ConflictError(existing)

    resp = app_client.post(
        f"/api/v1/investigation-sessions/{session.id}/conclude",
        headers=TEST_HEADERS,
        json={"outcome": "false_positive"},
    )
    assert resp.status_code == 409
    assert "detail" in resp.json()


@patch("app.api.sessions.session_service.get_session", new_callable=AsyncMock)
def test_conclude_404_unknown_session(mock_get_session, app_client):
    from app.services.session_service import SessionNotFoundError
    mock_get_session.side_effect = SessionNotFoundError("missing")
    resp = app_client.post(
        f"/api/v1/investigation-sessions/{uuid.uuid4()}/conclude",
        headers=TEST_HEADERS,
        json={"outcome": "escalate"},
    )
    assert resp.status_code == 404
