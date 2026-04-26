import structlog

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
