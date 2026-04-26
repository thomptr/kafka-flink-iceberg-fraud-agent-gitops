from unittest.mock import patch

import pytest


def _make_rows(n=10, merchants=None, lats=None, lons=None, hours=None):
    base = [
        {
            "amount": 50.0,
            "merchant": merchants[i % len(merchants)] if merchants else f"shop_{i % 3}",
            "lat": lats[i] if lats else 37.7,
            "lon": lons[i] if lons else -122.4,
            "ts": f"2026-01-{(i % 28) + 1:02d}T{(hours[i] if hours else 10):02d}:00:00",
            "distance_from_home_km": float(i * 2),
            "amount_velocity_5min": 200.0,
        }
        for i in range(n)
    ]
    return base


@patch("app.tools.user_history_tool.query_iceberg_table")
def test_aggregation_basic(mock_tool):
    rows = _make_rows(10, merchants=["A", "B", "C"], lats=[37.7, 37.8, 37.9, 38.0, 38.1, 38.2, 38.3, 38.4, 38.5, 38.6])
    mock_tool.invoke.return_value = {"rows": rows}
    from app.tools.user_history_tool import get_user_history
    result = get_user_history.invoke({"user_id": "42"})
    assert result["transaction_count"] == 10
    assert result["unique_merchants"] == 3
    assert len(result["merchant_list"]) == 3
    assert result["error"] is None


@patch("app.tools.user_history_tool.query_iceberg_table")
def test_no_transactions(mock_tool):
    mock_tool.invoke.return_value = {"rows": []}
    from app.tools.user_history_tool import get_user_history
    result = get_user_history.invoke({"user_id": "99"})
    assert result["transaction_count"] == 0
    assert result["total_amount"] == 0.0
    assert result["merchant_list"] == []
    assert result["error"] is None


@patch("app.tools.user_history_tool.query_iceberg_table")
def test_catalog_exception(mock_tool):
    mock_tool.invoke.side_effect = RuntimeError("catalog error")
    from app.tools.user_history_tool import get_user_history
    result = get_user_history.invoke({"user_id": "1"})
    assert result["error"] == "catalog error"
    assert result["transaction_count"] == 0


@patch("app.tools.user_history_tool.query_iceberg_table")
def test_unusual_hour_flag(mock_tool):
    rows = _make_rows(3, hours=[3, 10, 14])
    mock_tool.invoke.return_value = {"rows": rows}
    from app.tools.user_history_tool import get_user_history
    result = get_user_history.invoke({"user_id": "5"})
    assert result["unusual_hour_flag"] is True


@patch("app.tools.user_history_tool.query_iceberg_table")
def test_custom_days_filter_applied(mock_tool):
    mock_tool.invoke.return_value = {"rows": []}
    from app.tools.user_history_tool import get_user_history
    get_user_history.invoke({"user_id": "7", "days": 7})
    call_args = mock_tool.invoke.call_args[0][0]
    assert "AND ts >=" in call_args["row_filter"]
    assert "user_id = 7" in call_args["row_filter"]
