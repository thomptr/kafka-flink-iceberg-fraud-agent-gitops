import structlog

from app.tools.iceberg_query_tool import query_iceberg_table

log = structlog.get_logger(__name__)


def fetch_transaction_history(
    user_id: int, snapshot_id: int | None = None
) -> tuple[list[dict], int | None]:
    try:
        result = query_iceberg_table.invoke({
            "namespace": "fraud",
            "table_name": "transactions",
            "row_filter": f"user_id = {user_id}",
            "selected_columns": [
                "transaction_id", "amount", "merchant", "event_time", "fraud_probability"
            ],
            "limit": 50,
            "snapshot_id": snapshot_id,
        })
        rows = sorted(
            result["rows"],
            key=lambda r: r.get("event_time", ""),
            reverse=True,
        )
        return rows, result["snapshot_id"]
    except Exception as exc:
        log.warning("fetch_transaction_history_error", user_id=user_id, error=str(exc))
        return [], None
