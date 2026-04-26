from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import structlog
from langchain_core.tools import tool

from app.tools.iceberg_query_tool import query_iceberg_table
from app.tools.pii_masking import mask_pii

log = structlog.get_logger(__name__)

_UNUSUAL_HOURS = frozenset(range(2, 6))  # 02:00–05:59 UTC


class UserHistoryResult(TypedDict):
    transaction_count: int
    total_amount: float
    velocity_txns_per_day: float
    unique_merchants: int
    merchant_list: list[str]
    unique_locations: int
    avg_distance_from_home_km: float
    max_distance_from_home_km: float
    avg_amount_velocity_5min: float
    peak_hour_buckets: dict[str, int]
    unusual_hour_flag: bool
    error: str | None


@tool
def get_user_history(user_id: str, days: int = 90) -> UserHistoryResult:
    """Aggregate a user's transaction history over a configurable window.

    Returns velocity, location spread, merchant diversity, and time-of-day patterns.
    Use this when the analyst asks about location patterns, geographic spread, unusual
    timing, or velocity over time. Prefer this over pattern_lookup_tool for location
    and time-of-day questions; use pattern_lookup_tool for amount statistics.
    """
    empty = UserHistoryResult(
        transaction_count=0,
        total_amount=0.0,
        velocity_txns_per_day=0.0,
        unique_merchants=0,
        merchant_list=[],
        unique_locations=0,
        avg_distance_from_home_km=0.0,
        max_distance_from_home_km=0.0,
        avg_amount_velocity_5min=0.0,
        peak_hour_buckets={},
        unusual_hour_flag=False,
        error=None,
    )
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = query_iceberg_table.invoke({
            "namespace": "fraud",
            "table_name": "transactions",
            "row_filter": f"user_id = {int(user_id)} AND ts >= '{cutoff.isoformat()}'",
            "limit": 5000,
        })
        rows = result.get("rows", [])
        if not rows:
            return empty

        amounts = [float(r.get("amount", 0)) for r in rows]
        merchants = [str(r.get("merchant", "")) for r in rows if r.get("merchant")]
        masked_merchants = [str(mask_pii(m)) for m in merchants]
        unique_merchant_set = set(masked_merchants)

        locations = {
            (round(float(r["lat"]), 2), round(float(r["lon"]), 2))
            for r in rows
            if r.get("lat") is not None and r.get("lon") is not None
        }

        distances = [float(r["distance_from_home_km"]) for r in rows if r.get("distance_from_home_km") is not None]
        velocities = [float(r["amount_velocity_5min"]) for r in rows if r.get("amount_velocity_5min") is not None]

        hour_counts: Counter = Counter()
        unusual_flag = False
        for r in rows:
            ts_raw = r.get("ts")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    hour = ts.hour
                    hour_counts[str(hour)] += 1
                    if hour in _UNUSUAL_HOURS:
                        unusual_flag = True
                except ValueError:
                    pass

        top_hours = dict(hour_counts.most_common(5))

        return UserHistoryResult(
            transaction_count=len(rows),
            total_amount=sum(amounts),
            velocity_txns_per_day=len(rows) / max(days, 1),
            unique_merchants=len(unique_merchant_set),
            merchant_list=list(unique_merchant_set)[:20],
            unique_locations=len(locations),
            avg_distance_from_home_km=sum(distances) / len(distances) if distances else 0.0,
            max_distance_from_home_km=max(distances) if distances else 0.0,
            avg_amount_velocity_5min=sum(velocities) / len(velocities) if velocities else 0.0,
            peak_hour_buckets=top_hours,
            unusual_hour_flag=unusual_flag,
            error=None,
        )
    except Exception as exc:
        log.warning("get_user_history_error", user_id=user_id, days=days, error=str(exc))
        return UserHistoryResult(**{**empty, "error": str(exc)})
