# Contract: Flink Iceberg sink → Polaris REST catalog

**Purpose**: Document the integration surface between the Flink job and Apache Polaris so GitOps manifests and job config stay aligned.

## Catalog

| Property | Example / note |
|----------|----------------|
| Catalog type | `iceberg` (Flink) |
| Catalog implementation | `org.apache.iceberg.flink.CatalogLoader` with **REST** |
| URI | `http://polaris.polaris.svc.cluster.local:8181/api/catalog` (in-cluster); port-forward for laptop debugging |
| Warehouse | Polaris catalog name (e.g. `quickstart_catalog`) — matches `client.region` / OAuth scope patterns from runbooks |
| Auth | OAuth2 client credentials (`client.id` / `client.secret`) from **`polaris-bootstrap-credentials`** material |

## Storage (MinIO / S3)

| Property | Note |
|----------|------|
| `s3.endpoint` | Internal MinIO service URL for TaskManagers |
| Path style | `true` for MinIO compatibility |
| Credentials | Kubernetes Secret (same trust model as `polaris-storage-credentials`) |

## Table

- **Identifier**: `fraud.analytics.enriched_txn` (illustrative — finalize in implementation).  
- **Write mode**: Append-only stream for v1.  
- **Checkpoint commit**: Iceberg commits on Flink checkpoint success (connector-dependent).

## Failure signals

- **Catalog 403/401**: OAuth scope or Polaris RBAC; compare with PyIceberg smoke test docs.  
- **S3 403/404**: Bucket missing or wrong keys; ensure warehouse bucket exists.  
- **Commit timeout**: MinIO latency or checkpoint interval too aggressive for Minikube resources.
