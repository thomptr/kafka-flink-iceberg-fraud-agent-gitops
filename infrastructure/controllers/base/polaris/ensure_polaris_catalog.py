#!/usr/bin/env python3
"""Create the MinIO warehouse bucket (if missing), then register the Polaris Iceberg catalog.

Polaris/Iceberg need the S3 bucket from `POLARIS_DEFAULT_BASE_LOCATION` to exist or table
creation returns 404 "bucket does not exist". The in-cluster Job installs boto3 and uses
`polaris-storage-credentials` (same keys as MinIO root). See ensure-catalog-job.yaml.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


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
    if not default_base_location.startswith("s3://"):
        raise SystemExit("POLARIS_DEFAULT_BASE_LOCATION must start with s3://")
    return default_base_location[5:].split("/", 1)[0]


def _exit_minio_client_error(exc: Exception, endpoint_url: str) -> None:
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        raise SystemExit(
            f"Cannot use MinIO at {endpoint_url!r} with the given S3 credentials: {exc}"
        ) from exc
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "InvalidAccessKeyId":
        raise SystemExit(
            "MinIO rejected access key. POLARIS_S3_ACCESS_KEY_ID / POLARIS_S3_SECRET_ACCESS_KEY "
            "must match polaris-storage-credentials (same as MinIO root user/password)."
            f" Endpoint: {endpoint_url!r}."
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
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError as exc:
        raise SystemExit(
            "boto3 is required to create the warehouse bucket. "
            "Install boto3 (the Job uses: pip install boto3) or create the bucket manually "
            "(e.g. mc mb minio/iceberg-warehouse) and set POLARIS_ENSURE_S3_BUCKET=0."
        ) from exc

    bucket = warehouse_bucket_name(default_base_location)
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


def resolve_client_credentials() -> tuple[str, str]:
    boot = os.environ.get("POLARIS_BOOTSTRAP_CREDENTIALS")
    if boot:
        parts = boot.split(",", 2)
        if len(parts) == 3:
            return parts[1], parts[2]
    cid = os.environ.get("POLARIS_CLIENT_ID")
    sec = os.environ.get("POLARIS_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    raise SystemExit(
        "Set POLARIS_BOOTSTRAP_CREDENTIALS (REALM,client_id,secret) or POLARIS_CLIENT_ID and POLARIS_CLIENT_SECRET"
    )


def main() -> int:
    catalog_uri = os.environ.get(
        "POLARIS_CATALOG_URI", "http://polaris.polaris.svc.cluster.local:8181/api/catalog"
    )
    management_uri = os.environ.get("POLARIS_MANAGEMENT_URI") or derive_management_uri(catalog_uri)
    client_id, client_secret = resolve_client_credentials()
    scope = os.environ.get("POLARIS_SCOPE", "PRINCIPAL_ROLE:ALL")
    catalog_name = os.environ.get("POLARIS_CATALOG_NAME", "quickstart_catalog")
    default_base_location = os.environ.get(
        "POLARIS_DEFAULT_BASE_LOCATION", "s3://iceberg-warehouse/polaris"
    )
    minio_endpoint = os.environ.get(
        "POLARIS_MINIO_ENDPOINT", "http://minio.minio.svc.cluster.local:9000"
    )
    minio_internal_endpoint = os.environ.get(
        "POLARIS_MINIO_INTERNAL_ENDPOINT", "http://minio.minio.svc.cluster.local:9000"
    )
    region = os.environ.get("POLARIS_REGION", "us-east-1")

    if os.environ.get("POLARIS_ENSURE_S3_BUCKET", "1") == "1":
        access_key = os.environ.get("POLARIS_S3_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("POLARIS_S3_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            raise SystemExit(
                "POLARIS_ENSURE_S3_BUCKET=1 requires POLARIS_S3_ACCESS_KEY_ID and "
                "POLARIS_S3_SECRET_ACCESS_KEY (e.g. from polaris-storage-credentials)."
            )
        ensure_warehouse_bucket(
            default_base_location=default_base_location,
            endpoint_url=minio_internal_endpoint,
            region=region,
            access_key_id=access_key,
            secret_access_key=secret_key,
        )

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
    print(f"[ok] Polaris catalog '{catalog_name}' is ready for Iceberg (warehouse name matches Flink SQL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
