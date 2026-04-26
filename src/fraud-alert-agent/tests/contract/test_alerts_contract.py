from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_HEADERS, _make_alert


@pytest.fixture(autouse=True)
def _patch_services():
    alert = _make_alert()
    with (
        patch("app.api.alerts.list_alerts", new=AsyncMock(return_value=([alert], 1))),
        patch("app.api.alerts.get_alert", new=AsyncMock(return_value=alert)),
    ):
        yield


def test_list_alerts_returns_pagination_envelope(app_client):
    resp = app_client.get("/api/v1/alerts", headers=TEST_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "items" in body
    assert isinstance(body["items"], list)


def test_list_alerts_item_schema(app_client):
    resp = app_client.get("/api/v1/alerts", headers=TEST_HEADERS)
    item = resp.json()["items"][0]
    for field in ("id", "transaction_id", "user_id", "amount", "fraud_probability",
                  "severity", "status", "sla_deadline", "created_at"):
        assert field in item, f"Missing field: {field}"


def test_list_alerts_severity_filter_accepted(app_client):
    resp = app_client.get("/api/v1/alerts?severity=critical", headers=TEST_HEADERS)
    assert resp.status_code == 200


def test_list_alerts_status_filter_accepted(app_client):
    resp = app_client.get("/api/v1/alerts?status=open", headers=TEST_HEADERS)
    assert resp.status_code == 200


def test_list_alerts_pagination_params_accepted(app_client):
    resp = app_client.get("/api/v1/alerts?page=2&page_size=10", headers=TEST_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 2
    assert body["page_size"] == 10


def test_list_alerts_rejects_missing_api_key(app_client):
    resp = app_client.get("/api/v1/alerts")
    assert resp.status_code == 401


def test_list_alerts_rejects_wrong_api_key(app_client):
    resp = app_client.get("/api/v1/alerts", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_get_alert_returns_alert(app_client, test_alert_id):
    resp = app_client.get(f"/api/v1/alerts/{test_alert_id}", headers=TEST_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert "severity" in body
    assert "status" in body


def test_get_alert_detailed_includes_summary(app_client, test_alert_id):
    resp = app_client.get(f"/api/v1/alerts/{test_alert_id}", headers=TEST_HEADERS)
    body = resp.json()
    assert "summary" in body


def test_get_alert_not_found(app_client):
    with patch("app.api.alerts.get_alert", new=AsyncMock(return_value=None)):
        resp = app_client.get("/api/v1/alerts/00000000-0000-0000-0000-000000000000",
                              headers=TEST_HEADERS)
    assert resp.status_code == 404
    assert "detail" in resp.json()
