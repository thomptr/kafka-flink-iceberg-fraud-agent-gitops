from unittest.mock import MagicMock, patch

import pytest


def _make_table_mock(rows=None):
    table = MagicMock()
    arrow_batch = MagicMock()
    arrow_batch.to_pylist.return_value = rows or []
    arrow_table = MagicMock()
    arrow_table.to_batches.return_value = [arrow_batch]
    table.scan.return_value.to_arrow.return_value = arrow_table

    snapshot = MagicMock()
    snapshot.snapshot_id = 12345
    snapshot.timestamp_ms = 1_700_000_000_000
    table.current_snapshot.return_value = snapshot

    hist_entry = MagicMock()
    hist_entry.snapshot_id = 12345
    hist_entry.timestamp_ms = 1_700_000_000_000
    table.history.return_value = [hist_entry] * 12  # more than 10 to test slicing

    return table


@patch("app.tools.transaction_details_tool.load_table")
def test_matching_row_returned_and_pii_masked(mock_load):
    mock_load.return_value = _make_table_mock([
        {"transaction_id": "abc", "amount": 100.0, "card_number": "4111 1111 1111 1234"}
    ])
    from app.tools.transaction_details_tool import get_transaction_details
    result = get_transaction_details.invoke({"transaction_id": "abc"})
    assert result["transaction"] is not None
    assert result["error"] is None
    assert "4111" not in str(result["transaction"].get("card_number", ""))
    assert result["snapshot_id"] == 12345
    assert result["snapshot_timestamp_ms"] == 1_700_000_000_000


@patch("app.tools.transaction_details_tool.load_table")
def test_no_matching_row(mock_load):
    mock_load.return_value = _make_table_mock([])
    from app.tools.transaction_details_tool import get_transaction_details
    result = get_transaction_details.invoke({"transaction_id": "missing"})
    assert result["transaction"] is None
    assert result["error"] is None


@patch("app.tools.transaction_details_tool.load_table")
def test_exception_returns_error_field(mock_load):
    mock_load.side_effect = RuntimeError("catalog down")
    from app.tools.transaction_details_tool import get_transaction_details
    result = get_transaction_details.invoke({"transaction_id": "x"})
    assert result["transaction"] is None
    assert result["error"] == "catalog down"


@patch("app.tools.transaction_details_tool.load_table")
def test_table_history_capped_at_10(mock_load):
    mock_load.return_value = _make_table_mock()
    from app.tools.transaction_details_tool import get_transaction_details
    result = get_transaction_details.invoke({"transaction_id": "abc"})
    assert len(result["table_history"]) <= 10


@patch("app.tools.transaction_details_tool.load_table")
def test_snapshot_metadata_matches_mock(mock_load):
    mock_load.return_value = _make_table_mock()
    from app.tools.transaction_details_tool import get_transaction_details
    result = get_transaction_details.invoke({"transaction_id": "abc"})
    assert result["snapshot_id"] == 12345
    assert result["snapshot_timestamp_ms"] == 1_700_000_000_000
