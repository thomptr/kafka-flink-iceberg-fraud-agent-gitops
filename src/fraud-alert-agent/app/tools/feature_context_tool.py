import structlog
from langchain_core.tools import tool

from app.tools.iceberg_query_tool import query_iceberg_table

log = structlog.get_logger(__name__)


def fetch_feature_context(
    transaction_id: str, snapshot_id: int | None = None
) -> tuple[dict | None, int | None]:
    try:
        result = query_iceberg_table.invoke({
            "namespace": "fraud",
            "table_name": "transactions_scored",
            "row_filter": f"transaction_id = '{transaction_id}'",
            "limit": 1,
            "snapshot_id": snapshot_id,
        })
        if result["rows"]:
            return result["rows"][0], result["snapshot_id"]
        return None, None
    except Exception as exc:
        log.warning("fetch_feature_context_error", transaction_id=transaction_id, error=str(exc))
        return None, None


@tool
def get_feature_context(transaction_id: str) -> dict:
    """Retrieve the ML feature vector and raw feature values for a specific transaction.

    Returns feature names, values, and baselines from the transactions_scored table.
    Use this when the analyst asks about ML feature values, model inputs, or which
    features had the highest fraud weight.
    """
    features, snapshot_id = fetch_feature_context(transaction_id)
    if features is None:
        return {"error": "No feature data found.", "transaction_id": transaction_id}
    return {"features": features, "snapshot_id": snapshot_id, "transaction_id": transaction_id}
