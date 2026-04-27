import concurrent.futures
import json
from unittest.mock import MagicMock, patch

import pytest


@patch("app.tools.explanation_tool.get_llm_plain")
def test_returns_llm_content(mock_get_llm):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="The transaction was flagged because of unusual amount.")
    mock_get_llm.return_value = llm
    from app.tools.explanation_tool import explain_fraud_flag
    result = explain_fraud_flag.invoke({
        "transaction_json": json.dumps({"amount": 500}),
        "user_history_json": json.dumps({"velocity": 2.0}),
        "fraud_score": 0.91,
    })
    assert result == "The transaction was flagged because of unusual amount."


@patch("app.tools.explanation_tool.get_llm_plain")
def test_timeout_returns_message(mock_get_llm):
    llm = MagicMock()
    llm.invoke.side_effect = concurrent.futures.TimeoutError()
    mock_get_llm.return_value = llm
    from app.tools.explanation_tool import explain_fraud_flag
    result = explain_fraud_flag.invoke({
        "transaction_json": json.dumps({}),
        "user_history_json": json.dumps({}),
        "fraud_score": 0.5,
    })
    assert "timed out" in result


@patch("app.tools.explanation_tool.get_llm_plain")
def test_llm_error_returns_unavailable(mock_get_llm):
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("llm error")
    mock_get_llm.return_value = llm
    from app.tools.explanation_tool import explain_fraud_flag
    result = explain_fraud_flag.invoke({
        "transaction_json": json.dumps({}),
        "user_history_json": json.dumps({}),
        "fraud_score": 0.5,
    })
    assert result.startswith("Explanation unavailable")


@patch("app.tools.explanation_tool.get_llm_plain")
def test_fraud_score_in_system_message(mock_get_llm):
    captured = {}
    def fake_invoke(messages):
        captured["messages"] = messages
        return MagicMock(content="ok")
    llm = MagicMock()
    llm.invoke.side_effect = fake_invoke
    mock_get_llm.return_value = llm
    from app.tools.explanation_tool import explain_fraud_flag
    explain_fraud_flag.invoke({
        "transaction_json": json.dumps({"amount": 1}),
        "user_history_json": json.dumps({}),
        "fraud_score": 0.92,
    })
    system_content = captured["messages"][0]["content"]
    assert "92.00%" in system_content


def test_invalid_json_returns_parse_error():
    from app.tools.explanation_tool import explain_fraud_flag
    result = explain_fraud_flag.invoke({
        "transaction_json": "not-json",
        "user_history_json": "{}",
        "fraud_score": 0.5,
    })
    assert result.startswith("Invalid input")
