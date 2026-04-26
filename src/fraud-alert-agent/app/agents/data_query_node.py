import asyncio

import structlog

from app.agents.state import FraudInvestigationState
from app.tools.feature_context_tool import fetch_feature_context
from app.tools.pattern_lookup_tool import fetch_pattern_stats
from app.tools.transaction_history_tool import fetch_transaction_history

log = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 15.0


async def data_query_node(state: FraudInvestigationState) -> dict:
    user_id = state["user_id"]
    transaction_id = state["transaction_id"]
    tool_errors: list[str] = []
    snapshot_ids: dict = {}

    async def _fetch_history():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fetch_transaction_history, user_id, None)

    async def _fetch_feature():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fetch_feature_context, transaction_id, None)

    async def _fetch_patterns():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fetch_pattern_stats, user_id)

    try:
        results = await asyncio.wait_for(
            asyncio.gather(_fetch_history(), _fetch_feature(), _fetch_patterns(), return_exceptions=True),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        tool_errors.append("data_query_timeout")
        log.warning("data_query_timeout", alert_id=state["alert_id"])
        return {"tool_errors": tool_errors}

    history_result, feature_result, pattern_result = results

    transaction_history: list[dict] = []
    feature_values: dict | None = None
    pattern_stats: dict | None = None

    if isinstance(history_result, Exception):
        tool_errors.append(f"transaction_history: {history_result}")
    else:
        rows, snap_id = history_result
        transaction_history = rows
        if snap_id is not None:
            snapshot_ids["transactions"] = snap_id

    if isinstance(feature_result, Exception):
        tool_errors.append(f"feature_context: {feature_result}")
    else:
        feat, snap_id = feature_result
        feature_values = feat
        if snap_id is not None:
            snapshot_ids["transactions_scored"] = snap_id

    if isinstance(pattern_result, Exception):
        tool_errors.append(f"pattern_stats: {pattern_result}")
    else:
        pattern_stats = pattern_result

    log.info(
        "data_query_complete",
        alert_id=state["alert_id"],
        history_count=len(transaction_history),
        snapshot_ids=snapshot_ids,
        tool_errors=tool_errors,
    )
    return {
        "transaction_history": transaction_history,
        "feature_values": feature_values,
        "pattern_stats": pattern_stats,
        "snapshot_ids": snapshot_ids,
        "tool_errors": tool_errors,
    }
