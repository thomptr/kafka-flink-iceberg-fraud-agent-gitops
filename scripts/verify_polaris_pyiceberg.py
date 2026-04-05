#!/usr/bin/env python3
"""Smoke test an Apache Polaris catalog with PyIceberg."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import pyarrow as pa
except ImportError as exc:
    raise SystemExit(
        "PyArrow is required for the table smoke test. Install with: uv pip install pyarrow"
    ) from exc

from pyiceberg.catalog import load_catalog
from pyiceberg.partitioning import PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.types import LongType, NestedField, StringType


def getenv(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or ""


def derive_management_uri(catalog_uri: str) -> str:
    suffix = "/api/catalog"
    if catalog_uri.endswith(suffix):
        return catalog_uri[: -len(suffix)] + "/api/management/v1"
    raise SystemExit(
        "Set POLARIS_MANAGEMENT_URI explicitly when POLARIS_CATALOG_URI does not end with /api/catalog"
    )


def http_request(
    method: str,
    url: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    token: str | None = None,
    body: dict | None = None,
    form: dict | None = None,
) -> tuple[int, dict | str]:
    headers: dict[str, str] = {}
    data = None

    if client_id and client_secret:
        raw = f"{client_id}:{client_secret}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    elif form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read().decode("utf-8")
            if not payload:
                return response.status, ""
            return response.status, json.loads(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else ""
        except json.JSONDecodeError:
            parsed = payload
        return exc.code, parsed


def request_token(catalog_uri: str, client_id: str, client_secret: str, scope: str) -> str:
    status, payload = http_request(
        "POST",
        f"{catalog_uri.rstrip('/')}/v1/oauth/tokens",
        client_id=client_id,
        client_secret=client_secret,
        form={"grant_type": "client_credentials", "scope": scope},
    )
    if status != 200:
        raise SystemExit(f"Failed to request Polaris token ({status}): {payload}")
    return payload["access_token"]


def allowed_location_from_base(default_base_location: str) -> str:
    if not default_base_location.startswith("s3://"):
        raise SystemExit("POLARIS_DEFAULT_BASE_LOCATION must start with s3://")
    bucket = default_base_location[5:].split("/", 1)[0]
    return f"s3://{bucket}"


def warehouse_bucket_name(default_base_location: str) -> str:
    """First path segment of an s3:// warehouse URI (bucket name)."""
    if not default_base_location.startswith("s3://"):
        raise SystemExit("POLARIS_DEFAULT_BASE_LOCATION must start with s3://")
    return default_base_location[5:].split("/", 1)[0]


def _exit_minio_client_error(exc: Exception, endpoint_url: str) -> None:
    """Turn boto ClientError into a short, actionable message for smoke-test users."""
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        raise SystemExit(
            f"Cannot use MinIO at {endpoint_url!r} with the given S3 credentials: {exc}"
        ) from exc
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "InvalidAccessKeyId":
        raise SystemExit(
            "MinIO rejected POLARIS_S3_ACCESS_KEY_ID (InvalidAccessKeyId). "
            "POLARIS_S3_ACCESS_KEY_ID and POLARIS_S3_SECRET_ACCESS_KEY must match MinIO "
            "`rootUser` and `rootPassword` from secret minio/minio-root-credentials — "
            "the same values as polaris-storage-credentials (awsAccessKeyId / awsSecretAccessKey). "
            "They are not the same as POLARIS_CLIENT_SECRET (Polaris OAuth). "
            f"Endpoint: {endpoint_url!r}."
        ) from exc
    raise SystemExit(
        f"Cannot use MinIO at {endpoint_url!r} with the given S3 credentials: {exc}"
    ) from exc


def ensure_warehouse_bucket(
    *,
    default_base_location: str,
    endpoint_url: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Create the warehouse bucket in MinIO/S3 if it is missing (Polaris needs it to exist)."""
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise SystemExit(
            "boto3 is required to create the warehouse bucket automatically. "
            "Install with: uv pip install boto3 — or create the bucket yourself (e.g. "
            "`mc mb minio/iceberg-warehouse`) and set POLARIS_ENSURE_S3_BUCKET=0."
        ) from exc

    bucket = warehouse_bucket_name(default_base_location)
    # MinIO requires path-style addressing; virtual-hosted requests often return 403 on HeadBucket.
    s3_config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url.rstrip("/"),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=s3_config,
    )
    try:
        listed = client.list_buckets()
    except ClientError as exc:
        _exit_minio_client_error(exc, endpoint_url)

    existing = {b["Name"] for b in listed.get("Buckets", [])}
    if bucket in existing:
        print(f"[minio] bucket {bucket!r} already exists")
        return

    try:
        client.create_bucket(Bucket=bucket)
        print(f"[minio] created bucket {bucket!r}")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"[minio] bucket {bucket!r} already exists")
            return
        _exit_minio_client_error(exc, endpoint_url)


def ensure_catalog(
    management_uri: str,
    token: str,
    catalog_name: str,
    default_base_location: str,
    minio_endpoint: str,
    minio_internal_endpoint: str,
    region: str,
) -> None:
    status, payload = http_request(
        "GET", f"{management_uri.rstrip('/')}/catalogs/{catalog_name}", token=token
    )
    if status == 200:
        print(f"[polaris] catalog '{catalog_name}' already exists")
        return
    if status != 404:
        raise SystemExit(f"Failed to inspect Polaris catalog ({status}): {payload}")

    allowed_location = allowed_location_from_base(default_base_location)
    create_payload = {
        "catalog": {
            "name": catalog_name,
            "type": "INTERNAL",
            "readOnly": False,
            "properties": {
                "default-base-location": default_base_location,
            },
            "storageConfigInfo": {
                "storageType": "S3",
                "allowedLocations": [allowed_location],
                "endpoint": minio_endpoint,
                "endpointInternal": minio_internal_endpoint,
                "pathStyleAccess": True,
                "region": region,
                "stsUnavailable": True,
            },
        }
    }

    status, payload = http_request(
        "POST",
        f"{management_uri.rstrip('/')}/catalogs",
        token=token,
        body=create_payload,
    )
    if status not in (200, 201, 409):
        raise SystemExit(f"Failed to create Polaris catalog ({status}): {payload}")
    print(f"[polaris] ensured catalog '{catalog_name}'")


def rest_catalog_properties(
    *,
    region: str,
    minio_endpoint: str,
    use_vended_credentials: bool,
) -> dict[str, str]:
    """Build PyIceberg REST catalog properties.

    PyIceberg defaults to ``X-Iceberg-Access-Delegation: vended-credentials``, which makes
    Polaris authorize ``CREATE_TABLE_DIRECT_WITH_WRITE_DELEGATION``. The bootstrap
    ``root`` principal typically has catalog admin grants but not that delegation op, so
    table creation returns 403 unless you either grant that privilege in Polaris or
    disable access delegation and use static MinIO credentials (default for this script).
    """
    props: dict[str, str] = {"client.region": region}
    if not use_vended_credentials:
        # Override PyIceberg default so Polaris does not require credential-vending grants.
        props["header.X-Iceberg-Access-Delegation"] = ""
        access_key = getenv("POLARIS_S3_ACCESS_KEY_ID") or getenv("AWS_ACCESS_KEY_ID")
        secret_key = getenv("POLARIS_S3_SECRET_ACCESS_KEY") or getenv("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            raise SystemExit(
                "Static S3 credentials are required when POLARIS_USE_VENDED_CREDENTIALS is unset or 0. "
                "Set POLARIS_S3_ACCESS_KEY_ID and POLARIS_S3_SECRET_ACCESS_KEY (MinIO keys matching "
                "polaris-storage-credentials), or set POLARIS_USE_VENDED_CREDENTIALS=1 and grant "
                "Polaris privileges for credential vending / table creation."
            )
        props["s3.endpoint"] = minio_endpoint
        props["s3.access-key-id"] = access_key
        props["s3.secret-access-key"] = secret_key
        props["s3.region"] = region
    return props


def smoke_table(
    catalog,
    *,
    namespace_name: str,
    table_name: str,
    replace: bool,
) -> None:
    """Create an Iceberg table, append rows, and read them back."""
    identifier = f"{namespace_name}.{table_name}"
    if catalog.table_exists(identifier):
        if replace:
            catalog.drop_table(identifier)
            print(f"[pyiceberg] dropped existing table '{identifier}'")
        else:
            raise SystemExit(
                f"Table '{identifier}' already exists. "
                "Set POLARIS_TABLE_REPLACE=1 to drop and recreate, or choose another POLARIS_TABLE_NAME."
            )

    schema = Schema(
        NestedField(1, "id", LongType(), required=True),
        NestedField(2, "msg", StringType(), required=True),
    )
    table = catalog.create_table(
        identifier=identifier,
        schema=schema,
        partition_spec=PartitionSpec(),
    )
    print(f"[pyiceberg] created table '{identifier}'")

    # PyArrow defaults columns to nullable; Iceberg required fields must match non-nullable Arrow fields.
    arrow_schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("msg", pa.string(), nullable=False),
        ]
    )
    rows = pa.table(
        {"id": [42, 7], "msg": ["polaris-smoke", "append-read"]},
        schema=arrow_schema,
    )
    table.append(rows)
    print(f"[pyiceberg] appended {rows.num_rows} row(s)")

    read_back = table.scan().to_arrow()
    if read_back.num_rows != rows.num_rows:
        raise SystemExit(
            f"Row count mismatch: expected {rows.num_rows}, got {read_back.num_rows}"
        )
    got = read_back.to_pydict()
    pairs = sorted(zip(got["id"], got["msg"]))
    expected = sorted([(42, "polaris-smoke"), (7, "append-read")])
    if pairs != expected:
        raise SystemExit(f"Unexpected scan result (sorted by id): {pairs!r} != {expected!r}")
    print("[pyiceberg] scan result:", got)
    print("[pyiceberg] full table smoke test (create, append, scan) passed")


def main() -> int:
    catalog_uri = getenv("POLARIS_CATALOG_URI", "http://127.0.0.1:8181/api/catalog")
    management_uri = getenv("POLARIS_MANAGEMENT_URI", derive_management_uri(catalog_uri))
    client_id = getenv("POLARIS_CLIENT_ID", required=True)
    client_secret = getenv("POLARIS_CLIENT_SECRET", required=True)
    scope = getenv("POLARIS_SCOPE", "PRINCIPAL_ROLE:ALL")
    catalog_name = getenv("POLARIS_CATALOG_NAME", "quickstart_catalog")
    namespace_name = getenv("POLARIS_NAMESPACE", "smoke")
    table_name = getenv("POLARIS_TABLE_NAME", "smoke_test")
    table_replace = getenv("POLARIS_TABLE_REPLACE", "1") == "1"
    default_base_location = getenv(
        "POLARIS_DEFAULT_BASE_LOCATION", "s3://iceberg-warehouse/polaris"
    )
    minio_endpoint = getenv("POLARIS_MINIO_ENDPOINT", "http://127.0.0.1:9000")
    minio_internal_endpoint = getenv(
        "POLARIS_MINIO_INTERNAL_ENDPOINT", "http://minio.minio.svc.cluster.local:9000"
    )
    region = getenv("POLARIS_REGION", "us-east-1")
    use_vended_credentials = getenv("POLARIS_USE_VENDED_CREDENTIALS", "0") == "1"
    ensure_bucket = getenv("POLARIS_ENSURE_S3_BUCKET", "1") == "1"

    token = request_token(catalog_uri, client_id, client_secret, scope)
    ensure_catalog(
        management_uri,
        token,
        catalog_name,
        default_base_location,
        minio_endpoint,
        minio_internal_endpoint,
        region,
    )

    if ensure_bucket and not use_vended_credentials:
        access_key = getenv("POLARIS_S3_ACCESS_KEY_ID") or getenv("AWS_ACCESS_KEY_ID")
        secret_key = getenv("POLARIS_S3_SECRET_ACCESS_KEY") or getenv("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            ensure_warehouse_bucket(
                default_base_location=default_base_location,
                endpoint_url=minio_endpoint,
                region=region,
                access_key_id=access_key,
                secret_access_key=secret_key,
            )

    catalog = load_catalog(
        "polaris",
        type="rest",
        uri=catalog_uri,
        warehouse=catalog_name,
        scope=scope,
        credential=f"{client_id}:{client_secret}",
        **rest_catalog_properties(
            region=region,
            minio_endpoint=minio_endpoint,
            use_vended_credentials=use_vended_credentials,
        ),
    )

    namespaces = {".".join(namespace) for namespace in catalog.list_namespaces()}
    if namespace_name not in namespaces:
        catalog.create_namespace((namespace_name,))
        print(f"[pyiceberg] created namespace '{namespace_name}'")
    else:
        print(f"[pyiceberg] namespace '{namespace_name}' already exists")

    namespaces = sorted(".".join(namespace) for namespace in catalog.list_namespaces())
    print("[pyiceberg] visible namespaces:", ", ".join(namespaces) or "(none)")

    smoke_table(
        catalog,
        namespace_name=namespace_name,
        table_name=table_name,
        replace=table_replace,
    )
    print("[pyiceberg] Polaris REST catalog smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
