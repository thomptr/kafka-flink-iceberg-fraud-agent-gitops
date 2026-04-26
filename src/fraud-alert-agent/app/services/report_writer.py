import json
import uuid
from datetime import datetime, timezone

import pyarrow as pa
import structlog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.schema import Schema
from pyiceberg.transforms import MonthTransform
from pyiceberg.types import (
    DoubleType,
    FloatType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from app.tools.iceberg_catalog import ensure_namespace, get_catalog

log = structlog.get_logger(__name__)

_TABLE_NAMESPACE = "fraud"
_TABLE_NAME = "investigations"
_FULL_NAME = f"{_TABLE_NAMESPACE}.{_TABLE_NAME}"

_SCHEMA = Schema(
    NestedField(1, "investigation_id", StringType(), required=True),
    NestedField(2, "alert_id", StringType(), required=True),
    NestedField(3, "transaction_id", StringType(), required=True),
    NestedField(4, "user_id", IntegerType()),
    NestedField(5, "amount", DoubleType()),
    NestedField(6, "merchant", StringType()),
    NestedField(7, "fraud_probability", FloatType()),
    NestedField(8, "route", StringType()),
    NestedField(9, "severity", StringType()),
    NestedField(10, "recommended_action", StringType()),
    NestedField(11, "final_action", StringType()),
    NestedField(12, "rule_matched", StringType()),
    NestedField(13, "confidence", FloatType()),
    NestedField(14, "explanation", StringType()),
    NestedField(15, "evidence_json", StringType()),
    NestedField(16, "snapshot_ids_json", StringType()),
    NestedField(17, "tool_errors_json", StringType()),
    NestedField(18, "investigation_started_at", TimestamptzType()),
    NestedField(19, "investigation_completed_at", TimestamptzType()),
    NestedField(20, "report_written_at", TimestamptzType()),
)


def get_or_create_investigations_table():
    catalog = get_catalog()
    ensure_namespace(_TABLE_NAMESPACE)
    try:
        return catalog.load_table(_FULL_NAME)
    except NoSuchTableError:
        from pyiceberg.partitioning import PartitionField, PartitionSpec
        partition_spec = PartitionSpec(
            PartitionField(
                source_id=19,
                field_id=1000,
                transform=MonthTransform(),
                name="investigation_completed_at_month",
            )
        )
        return catalog.create_table(_FULL_NAME, schema=_SCHEMA, partition_spec=partition_spec)


def write_investigation_report(
    state: dict,
    investigation_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> int | None:
    try:
        table = get_or_create_investigations_table()
        now = datetime.now(timezone.utc)

        row = {
            "investigation_id": investigation_id,
            "alert_id": state.get("alert_id", ""),
            "transaction_id": state.get("transaction_id", ""),
            "user_id": state.get("user_id"),
            "amount": float(state.get("amount", 0)),
            "merchant": state.get("merchant"),
            "fraud_probability": float(state.get("fraud_probability", 0)),
            "route": state.get("route", ""),
            "severity": state.get("severity", ""),
            "recommended_action": state.get("recommended_action", ""),
            "final_action": state.get("final_action", ""),
            "rule_matched": state.get("rule_matched", ""),
            "confidence": float(state["confidence"]) if state.get("confidence") is not None else None,
            "explanation": state.get("explanation", ""),
            "evidence_json": json.dumps(state.get("evidence", [])),
            "snapshot_ids_json": json.dumps(state.get("snapshot_ids", {})),
            "tool_errors_json": json.dumps(state.get("tool_errors", [])),
            "investigation_started_at": started_at,
            "investigation_completed_at": completed_at,
            "report_written_at": now,
        }

        arrow_table = pa.table({k: [v] for k, v in row.items()})
        table.append(arrow_table)

        snapshot_id: int | None = None
        if table.current_snapshot() is not None:
            snapshot_id = table.current_snapshot().snapshot_id  # type: ignore[union-attr]

        log.info(
            "investigation_report_written",
            investigation_id=investigation_id,
            alert_id=state.get("alert_id"),
            snapshot_id=snapshot_id,
        )
        return snapshot_id
    except Exception as exc:
        log.warning(
            "investigation_report_write_error",
            investigation_id=investigation_id,
            error=str(exc),
        )
        return None
