import time
from functools import lru_cache

import structlog
from pyiceberg.catalog.rest import RestCatalog
from pyiceberg.exceptions import NoSuchNamespaceError
from pyiceberg.table import Table

from app.config import settings

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_catalog() -> RestCatalog:
    return RestCatalog(
        name="polaris",
        **{
            "uri": settings.ICEBERG_CATALOG_URI,
            "credential": settings.POLARIS_CREDENTIAL,
            "warehouse": settings.ICEBERG_WAREHOUSE,
            "scope": "PRINCIPAL_ROLE:ALL",
            # Disable vended credentials — use static MinIO keys instead
            "header.X-Iceberg-Access-Delegation": "",
            "s3.endpoint": settings.MINIO_ENDPOINT,
            "s3.access-key-id": settings.AWS_ACCESS_KEY_ID,
            "s3.secret-access-key": settings.AWS_SECRET_ACCESS_KEY,
            "s3.region": "us-east-1",
            "client.region": "us-east-1",
        },
    )


def load_table(namespace: str, table_name: str) -> Table:
    catalog = get_catalog()
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            return catalog.load_table(f"{namespace}.{table_name}")
        except Exception as exc:
            last_exc = exc
            log.warning(
                "iceberg_load_table_retry",
                namespace=namespace,
                table_name=table_name,
                attempt=attempt,
                error=str(exc),
            )
            time.sleep(0.5 * attempt)
    raise last_exc  # type: ignore[misc]


def ensure_namespace(namespace: str) -> None:
    catalog = get_catalog()
    try:
        catalog.load_namespace_properties(namespace)
    except NoSuchNamespaceError:
        catalog.create_namespace(namespace)
