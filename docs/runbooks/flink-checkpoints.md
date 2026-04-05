# Flink checkpoints and savepoints on MinIO (S3A)

Flink state checkpoints and savepoints for `sample-fraud-stream` are configured with `s3://` URIs under bucket `iceberg-warehouse` (see `apps/base/flink-jobs/resources.yaml` `spec.flinkConfiguration`).

## Required configuration keys (no secrets in Git)

| Key | Purpose |
|-----|---------|
| `state.checkpoints.dir` | Periodic checkpoint storage (S3A). |
| `state.savepoints.dir` | Savepoint base path. |
| `fs.s3a.endpoint` | MinIO API inside the cluster (`http://minio.minio.svc.cluster.local:9000`). |
| `fs.s3a.path.style.access` | `true` for MinIO. |
| `fs.s3a.connection.ssl.enabled` | `false` for plain HTTP inside the cluster. |
| `fs.s3a.aws.credentials.provider` | `org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider` (reads `fs.s3a.access.key` / `fs.s3a.secret.key` in Hadoop config). |
| Image entrypoint | `apps/base/flink-jobs/docker-entrypoint-wrapper.sh` copies `/opt/flink/conf` to a writable directory (the operator mounts config from a **read-only** ConfigMap, so upstream `FLINK_PROPERTIES` merging often cannot persist), appends **`fs.s3a.access.key`** / **`fs.s3a.secret.key`**, and sets **`FLINK_CONF_DIR`** to that copy. It still exports **`FLINK_PROPERTIES`** for any code path that can merge from env. |

Flink still prepends its dynamic STS provider first; the chain then uses the static keys above.

## Hadoop / S3 plugin

The Flink image built from `apps/base/flink-jobs/Dockerfile` installs `flink-s3-fs-hadoop` under `/opt/flink/plugins/s3-fs-hadoop/` so the `s3://` filesystem is available to the JobManager and TaskManagers.

## Kubernetes secrets

Pods expect `minio-flink-s3-credentials` in `flink-system` with keys `rootUser` and `rootPassword` (same values as MinIO root credentials). Create this secret locally; do not commit it. See `docs/runbooks/bootstrap.md`.

## Failure signals

- Rising checkpoint duration or failed checkpoints in Flink UI / metrics.  
- MinIO 403/404: wrong bucket, keys, or endpoint.  
- Polaris/Iceberg catalog errors if warehouse paths are inconsistent with Polaris configuration.

### `AmazonS3Exception` / `InvalidAccessKeyId` / “The Access Key Id you provided does not exist in our records”

S3A **is** sending credentials; MinIO is rejecting the **access key** (HTTP 403). That almost always means **`minio-flink-s3-credentials`** in `flink-system` does **not** match the **actual** MinIO root user/password the MinIO server was deployed with.

Align it with the same values you use for:

- `minio/minio-root-credentials` (keys `rootUser` / `rootPassword`), and  
- `polaris/polaris-storage-credentials` (`awsAccessKeyId` / `awsSecretAccessKey`) — Polaris and Flink should use the **same** MinIO root material.

Recreate the Flink secret if you rotated MinIO or copied placeholders:

```bash
kubectl -n flink-system delete secret minio-flink-s3-credentials --ignore-not-found
kubectl -n flink-system create secret generic minio-flink-s3-credentials \
  --from-literal=rootUser='<same-as-minio-rootUser>' \
  --from-literal=rootPassword='<same-as-minio-rootPassword>'
```

Then restart the Flink pods (or bump `restartNonce` on the `FlinkDeployment`) so JobManagers/TaskManagers pick up the new secret.

**Sanity check** (from your machine, with MinIO reachable, e.g. port-forward to `:9000`):

```bash
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... aws --endpoint-url http://127.0.0.1:9000 s3 ls
```

If that fails with the same error, the keys are wrong for MinIO—not a Flink bug.
