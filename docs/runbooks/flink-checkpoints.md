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
| `fs.s3a.aws.credentials.provider` | `org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider` (uses `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` from the pod environment). |

## Hadoop / S3 plugin

The Flink image built from `apps/base/flink-jobs/Dockerfile` installs `flink-s3-fs-hadoop` under `/opt/flink/plugins/s3-fs-hadoop/` so the `s3://` filesystem is available to the JobManager and TaskManagers.

## Kubernetes secrets

Pods expect `minio-flink-s3-credentials` in `flink-system` with keys `rootUser` and `rootPassword` (same values as MinIO root credentials). Create this secret locally; do not commit it. See `docs/runbooks/bootstrap.md`.

## Failure signals

- Rising checkpoint duration or failed checkpoints in Flink UI / metrics.  
- MinIO 403/404: wrong bucket, keys, or endpoint.  
- Polaris/Iceberg catalog errors if warehouse paths are inconsistent with Polaris configuration.
