# Flink SQL streaming job (Kafka → Iceberg via Polaris)

This directory GitOps-manages a `FlinkDeployment` that runs the shaded JAR
`jobs/flink-sql-runner` (`SqlRunner`), which executes `flink_streaming_job.sql` from a
ConfigMap mount at `/opt/flink/sql/`.

## Operator pattern (T019)

- **Image**: build `apps/base/flink-jobs/Dockerfile` from the repo root after `mvn package` in `jobs/flink-sql-runner`.
- **Job**: `spec.job.jarURI` points at `local:///opt/flink/lib/sql-runner.jar`, with `entryClass` `org.example.fraud.flink.SqlRunner` and `args` containing the SQL file path.
- **SQL source of truth**: `flink_streaming_job.sql` is included via `configMapGenerator` in `kustomization.yaml` (ConfigMap `flink-streaming-sql`).

## Secrets and credentials

- **MinIO / S3**: TaskManagers and JobManagers expect `minio-flink-s3-credentials` in `flink-system` with keys `rootUser` and `rootPassword` matching your MinIO root user. Create it alongside other bootstrap secrets (see `docs/runbooks/bootstrap.md`).
- **Polaris**: the `credential` in `flink_streaming_job.sql` must match the Polaris root password you configured (same spirit as `polaris-bootstrap-credentials`). Use fake placeholders in Git; align values in-cluster only.

## Iceberg commit latency metrics (T021–T022)

Pure SQL cannot register custom `MetricGroup` hooks. For dashboards, use Flink and Iceberg built-in task/operator metrics (for example metrics whose names contain `Iceberg` or checkpoint/commit timings) and document the exact PromQL in `docs/runbooks/grafana-dashboards.md` once you confirm names from your Flink version. A future thin Java sink wrapper could emit `user_scope_iceberg_commit_latency_ms` if you need a dedicated histogram.

## Build and load (Minikube)

**Use the repository root as the Docker build context.** Do not run `docker build .` from `apps/base/flink-jobs`: the `COPY` instructions reference `jobs/` and `apps/` paths that only exist when the context is the repo root.

```bash
cd /path/to/kafka-flink-iceberg-fraud-agent-gitops   # repository root
cd jobs/flink-sql-runner && mvn -DskipTests package && cd ../..
docker build -f apps/base/flink-jobs/Dockerfile -t flink-sql-runner:1.18 .
minikube image load flink-sql-runner:1.18
```
