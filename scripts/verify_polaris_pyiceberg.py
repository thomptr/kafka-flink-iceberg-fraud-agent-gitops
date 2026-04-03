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

from pyiceberg.catalog import load_catalog


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


def main() -> int:
    catalog_uri = getenv("POLARIS_CATALOG_URI", "http://127.0.0.1:8181/api/catalog")
    management_uri = getenv("POLARIS_MANAGEMENT_URI", derive_management_uri(catalog_uri))
    client_id = getenv("POLARIS_CLIENT_ID", required=True)
    client_secret = getenv("POLARIS_CLIENT_SECRET", required=True)
    scope = getenv("POLARIS_SCOPE", "PRINCIPAL_ROLE:ALL")
    catalog_name = getenv("POLARIS_CATALOG_NAME", "quickstart_catalog")
    namespace_name = getenv("POLARIS_NAMESPACE", "smoke")
    default_base_location = getenv(
        "POLARIS_DEFAULT_BASE_LOCATION", "s3://iceberg-warehouse/polaris"
    )
    minio_endpoint = getenv("POLARIS_MINIO_ENDPOINT", "http://127.0.0.1:9000")
    minio_internal_endpoint = getenv(
        "POLARIS_MINIO_INTERNAL_ENDPOINT", "http://minio.minio.svc.cluster.local:9000"
    )
    region = getenv("POLARIS_REGION", "us-east-1")

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

    catalog = load_catalog(
        "polaris",
        type="rest",
        uri=catalog_uri,
        warehouse=catalog_name,
        scope=scope,
        credential=f"{client_id}:{client_secret}",
        **{
            "client.region": region,
        },
    )

    namespaces = {".".join(namespace) for namespace in catalog.list_namespaces()}
    if namespace_name not in namespaces:
        catalog.create_namespace((namespace_name,))
        print(f"[pyiceberg] created namespace '{namespace_name}'")
    else:
        print(f"[pyiceberg] namespace '{namespace_name}' already exists")

    namespaces = sorted(".".join(namespace) for namespace in catalog.list_namespaces())
    print("[pyiceberg] visible namespaces:", ", ".join(namespaces) or "(none)")
    print("[pyiceberg] Polaris REST catalog smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
