from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_HEADERS

_METRICS_RESPONSE = {
    "window_hours": 24,
    "alert_count": 42,
    "route_distribution": {"critical": 5, "high": 12, "medium": 25},
    "final_action_distribution": {"block": 4, "monitor": 10},
    "iceberg_write_success_rate": 0.97,
    "kafka_delivery_rate": 0.99,
    "kafka_consumer_lag": 0,
    "mlflow_model_version_in_use": "7",
}


@pytest.fixture(autouse=True)
def _patch_metrics_db():
    with patch("app.api.metrics_api.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        count_result = MagicMock()
        count_result.scalar.return_value = 42
        severity_result = MagicMock()
        severity_result.all.return_value = [("critical", 5), ("high", 12), ("medium", 25)]
        action_result = MagicMock()
        action_result.all.return_value = [("block", 4), ("monitor", 10)]
        steps_result = MagicMock()
        steps_result.scalars.return_value.all.return_value = []
        kafka_result = MagicMock()
        kafka_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[count_result, severity_result, action_result, steps_result, kafka_result]
        )
        mock_cls.return_value = mock_session

        with (
            patch("app.api.metrics_api.AdminClient", side_effect=Exception("no kafka")),
            patch("app.api.metrics_api.get_latest_model_version", side_effect=Exception("no mlflow")),
        ):
            yield


def test_metrics_returns_200(app_client):
    resp = app_client.get("/api/v1/metrics", headers=TEST_HEADERS)
    assert resp.status_code == 200


def test_metrics_schema_fields_present(app_client):
    resp = app_client.get("/api/v1/metrics", headers=TEST_HEADERS)
    body = resp.json()
    for field in ("window_hours", "alert_count", "route_distribution",
                  "final_action_distribution", "iceberg_write_success_rate",
                  "kafka_delivery_rate"):
        assert field in body, f"Missing field: {field}"


def test_metrics_window_hours_default(app_client):
    resp = app_client.get("/api/v1/metrics", headers=TEST_HEADERS)
    assert resp.json()["window_hours"] == 24


def test_metrics_window_hours_custom(app_client):
    resp = app_client.get("/api/v1/metrics?window_hours=48", headers=TEST_HEADERS)
    assert resp.status_code == 200


def test_metrics_rejects_missing_api_key(app_client):
    resp = app_client.get("/api/v1/metrics")
    assert resp.status_code == 401


def test_metrics_alert_count_is_integer(app_client):
    resp = app_client.get("/api/v1/metrics", headers=TEST_HEADERS)
    assert isinstance(resp.json()["alert_count"], int)
