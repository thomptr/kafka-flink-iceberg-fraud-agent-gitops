import math
from datetime import datetime, timedelta, timezone

import structlog

from app.tools.iceberg_query_tool import query_iceberg_table

log = structlog.get_logger(__name__)


def fetch_pattern_stats(user_id: int) -> dict:
    try:
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = query_iceberg_table.invoke({
            "namespace": "fraud",
            "table_name": "transactions",
            "row_filter": f"user_id = {user_id} AND event_time >= '{thirty_days_ago}'",
            "limit": 1000,
        })
        rows = result["rows"]
        if not rows:
            return {"transaction_count": 0, "avg_amount": 0.0, "stddev_amount": 0.0}

        amounts = [float(r.get("amount", 0)) for r in rows]
        count = len(amounts)
        avg = sum(amounts) / count
        variance = sum((a - avg) ** 2 for a in amounts) / count if count > 1 else 0.0
        stddev = math.sqrt(variance)
        max_amount = max(amounts)

        return {
            "transaction_count": count,
            "avg_amount": round(avg, 2),
            "stddev_amount": round(stddev, 2),
            "max_single_amount": round(max_amount, 2),
            "avg_transactions_per_hour": round(count / (30 * 24), 4),
        }
    except Exception as exc:
        log.warning("fetch_pattern_stats_error", user_id=user_id, error=str(exc))
        return {"error": "pattern_lookup_unavailable"}
