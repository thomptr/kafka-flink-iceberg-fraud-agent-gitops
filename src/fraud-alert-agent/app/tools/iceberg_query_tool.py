from typing import TypedDict

import structlog
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.iceberg_catalog import get_catalog, load_table

log = structlog.get_logger(__name__)


class IcebergQueryInput(BaseModel):
    namespace: str
    table_name: str
    row_filter: str | None = None
    selected_columns: list[str] | None = None
    limit: int = Field(default=100, le=1000)
    snapshot_id: int | None = None


class IcebergQueryResult(TypedDict):
    rows: list[dict]
    row_count: int
    snapshot_id: int | None
    table: str
    columns: list[str]
    error: str | None


@tool(args_schema=IcebergQueryInput)
def query_iceberg_table(
    namespace: str,
    table_name: str,
    row_filter: str | None = None,
    selected_columns: list[str] | None = None,
    limit: int = 100,
    snapshot_id: int | None = None,
) -> IcebergQueryResult:
    """Query an Iceberg table and return rows as a list of dicts."""
    t_str = f"{namespace}.{table_name}"
    try:
        table = load_table(namespace, table_name)
        scan_kwargs: dict = {"limit": min(limit, 1000)}
        if row_filter:
            scan_kwargs["row_filter"] = row_filter
        if selected_columns:
            scan_kwargs["selected_fields"] = tuple(selected_columns)
        if snapshot_id is not None:
            scan_kwargs["snapshot_id"] = snapshot_id

        scan = table.scan(**scan_kwargs)
        arrow_table = scan.to_arrow()
        used_snapshot_id: int | None = None
        if snapshot_id is not None:
            used_snapshot_id = snapshot_id
        elif table.current_snapshot() is not None:
            used_snapshot_id = table.current_snapshot().snapshot_id  # type: ignore[union-attr]

        rows = arrow_table.to_pydict()
        col_names = list(rows.keys())
        row_count = arrow_table.num_rows
        row_list = [
            {col: rows[col][i] for col in col_names}
            for i in range(row_count)
        ]
        log.info(
            "iceberg_query",
            namespace=namespace,
            table_name=table_name,
            row_count=row_count,
            snapshot_id=used_snapshot_id,
        )
        return IcebergQueryResult(
            rows=row_list,
            row_count=row_count,
            snapshot_id=used_snapshot_id,
            table=t_str,
            columns=col_names,
            error=None,
        )
    except Exception as exc:
        log.warning(
            "iceberg_query_error",
            namespace=namespace,
            table_name=table_name,
            error=str(exc),
        )
        return IcebergQueryResult(
            rows=[],
            row_count=0,
            snapshot_id=None,
            table=t_str,
            columns=[],
            error=str(exc),
        )


@tool
def list_iceberg_tables(namespace: str) -> list[str]:
    """List all Iceberg tables in the given namespace."""
    try:
        catalog = get_catalog()
        tables = catalog.list_tables(namespace)
        return [f"{ns}.{tbl}" for ns, tbl in tables]
    except Exception as exc:
        log.warning("list_iceberg_tables_error", namespace=namespace, error=str(exc))
        return []
