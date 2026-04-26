from typing import TypedDict

import structlog
from langchain_core.tools import tool

from app.tools.iceberg_catalog import load_table
from app.tools.pii_masking import mask_pii

log = structlog.get_logger(__name__)


class TransactionDetailsResult(TypedDict):
    transaction: dict | None
    snapshot_id: int | None
    snapshot_timestamp_ms: int | None
    table_history: list[dict]
    error: str | None


@tool
def get_transaction_details(transaction_id: str) -> TransactionDetailsResult:
    """Look up a specific transaction by ID from the fraud.transactions Iceberg table.

    Returns the transaction row, the current snapshot metadata, and recent snapshot
    history for time-travel context. Use this when the analyst asks about a specific
    transaction by ID, or asks what snapshot or point-in-time the data comes from.
    """
    try:
        table = load_table("fraud", "transactions")

        scan = table.scan(
            row_filter=f"transaction_id = '{transaction_id}'",
            limit=1,
        )
        rows = [dict(r) for batch in scan.to_arrow().to_batches() for r in batch.to_pylist()]
        transaction = mask_pii(rows[0]) if rows else None

        snapshot = table.current_snapshot()
        snapshot_id = snapshot.snapshot_id if snapshot else None
        snapshot_timestamp_ms = snapshot.timestamp_ms if snapshot else None

        history_entries = table.history()
        table_history = [
            {"snapshot_id": h.snapshot_id, "timestamp_ms": h.timestamp_ms}
            for h in history_entries[-10:]
        ]

        return TransactionDetailsResult(
            transaction=transaction,
            snapshot_id=snapshot_id,
            snapshot_timestamp_ms=snapshot_timestamp_ms,
            table_history=table_history,
            error=None,
        )
    except Exception as exc:
        log.warning("get_transaction_details_error", transaction_id=transaction_id, error=str(exc))
        return TransactionDetailsResult(
            transaction=None,
            snapshot_id=None,
            snapshot_timestamp_ms=None,
            table_history=[],
            error=str(exc),
        )
