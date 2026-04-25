# Flink SQL streaming job (Kafka → Iceberg via Polaris)

This directory GitOps-manages a `FlinkDeployment` that runs the shaded JAR
`jobs/flink-sql-runner` (`SqlRunner`), which executes `flink_streaming_job.sql` from a
ConfigMap mount at `/opt/flink/sql/`.

**Stack**: **Flink 1.20.3** on **Java 17** (`flink:1.20.3-java17`), **Iceberg 1.9.2** (`iceberg-flink-runtime-1.20`), Kafka SQL connector **3.3.0-1.20**. The in-repo **Flink Kubernetes Operator** chart (`1.14.0`) supports `flinkVersion: v1_20`.

## Operator pattern (T019)

- **Image**: build `apps/base/flink-jobs/Dockerfile` from the repo root after `mvn package` in `jobs/flink-sql-runner`.
- **Job**: `spec.job.jarURI` points at `local:///opt/flink/lib/sql-runner.jar`, with `entryClass` `org.example.fraud.flink.SqlRunner` and `args` containing the SQL file path.
- **SQL source of truth**: `flink_streaming_job.sql` is included via `configMapGenerator` in `kustomization.yaml` (ConfigMap `flink-streaming-sql`).

## Secrets and credentials

- **MinIO / S3**: TaskManagers and JobManagers expect `minio-flink-s3-credentials` in `flink-system` with keys `rootUser` and `rootPassword` matching your MinIO root user. Create it alongside other bootstrap secrets (see `docs/runbooks/bootstrap.md`). The deployment maps those to `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. The **`docker-entrypoint-wrapper.sh`** copies `/opt/flink/conf` to a writable directory (the operator mounts config from a **read-only** ConfigMap, so upstream `FLINK_PROPERTIES` merging often **does not** persist), appends **`fs.s3a.access.key`** / **`fs.s3a.secret.key`**, and sets **`FLINK_CONF_DIR`** to that copy before starting Flink. If MinIO returns **`InvalidAccessKeyId`** / “The Access Key Id you provided does not exist in our records”, the secret values do not match the live MinIO root user—fix the secret and restart Flink pods (see `docs/runbooks/flink-checkpoints.md`).
- **Polaris**: the sample SQL uses `'credential' = 'root:changeme'`. At runtime, `SqlRunner` replaces that line when **`POLARIS_OAUTH_CREDENTIAL`** (Secret `polaris-flink-oauth` / key `credential`, format `root:<password>`) or **`POLARIS_BOOTSTRAP_CREDENTIALS`** (same format as `polaris-bootstrap-credentials`) is set on the JobManager. It also injects static Iceberg S3 properties from `AWS_*` / `POLARIS_S3_*`, clears `X-Iceberg-Access-Delegation`, and forces **`io-impl=org.apache.iceberg.aws.s3.S3FileIO`** so the Flink Iceberg client can write `s3://...` MinIO paths without relying on Hadoop `FileSystem` scheme resolution. Create the secret per `docs/runbooks/bootstrap.md`. Without env substitution, the job keeps the Git placeholder and Polaris returns **`unauthorized_client`** if the password does not match.

## Iceberg commit latency metrics (T021–T022)

Pure SQL cannot register custom `MetricGroup` hooks. For dashboards, use Flink and Iceberg built-in task/operator metrics (for example metrics whose names contain `Iceberg` or checkpoint/commit timings) and document the exact PromQL in `docs/runbooks/grafana-dashboards.md` once you confirm names from your Flink version. A future thin Java sink wrapper could emit `user_scope_iceberg_commit_latency_ms` if you need a dedicated histogram.

## Model scoring job (Kafka → Iceberg → KServe → `transactions_scored`)

A second entry point, **`ModelScorerJob`**, reads the `transactions` Iceberg table as a streaming
source, calls the KServe fraud detection endpoint via Flink **Async I/O**, and writes enriched
records (all original columns + `fraud_probability DOUBLE`) to `transactions_scored`.

### Components

| File | Purpose |
|------|---------|
| `jobs/flink-sql-runner/src/main/java/…/ModelScorerJob.java` | Flink DataStream entry point; sets up Polaris catalog, async scoring, Iceberg sink |
| `jobs/flink-sql-runner/src/main/java/…/KServeAsyncFunction.java` | `RichAsyncFunction` that calls the KServe V2 endpoint; uses JDK `HttpClient` |
| `apps/base/flink-jobs/flink_scored_ddl.sql` | DDL-only SQL file run by `create-transactions-scored-table` K8s Job |
| `apps/base/flink-jobs/resources.yaml` | K8s Job + `fraud-score-enricher` FlinkDeployment |

### Deploy order

1. Apply GitOps (`flux reconcile ks apps-flink-jobs`) — this creates the `flink-scored-ddl`
   ConfigMap and triggers the `create-transactions-scored-table` Job first.
2. Once that Job completes, the `fraud-score-enricher` FlinkDeployment starts.

Manually:

```bash
# 1. Create the scored table
kubectl -n flink-system create job create-transactions-scored-table \
  --from=cronjob/create-transactions-scored-table 2>/dev/null || true
kubectl -n flink-system wait job/create-transactions-scored-table --for=condition=complete --timeout=120s

# 2. Apply the FlinkDeployment (already in resources.yaml)
kubectl -n flink-system get flinkdeployment fraud-score-enricher
```

### Configuration

- **`KSERVE_ENDPOINT`** env var on the FlinkDeployment overrides the default in-cluster URL.
- Polaris and MinIO credentials use the same Secrets (`polaris-flink-oauth`,
  `polaris-bootstrap-credentials`, `minio-flink-s3-credentials`) as `sample-fraud-stream`.
- Error sentinel: if KServe returns non-200 or times out, `fraud_probability = -1.0` is written
  so the pipeline never stalls.

### Verify

```bash
# Check FlinkDeployment status
kubectl -n flink-system get flinkdeployment fraud-score-enricher

# Read transactions_scored via PyIceberg (port-forward Polaris + MinIO first)
python3 - <<'EOF'
import os; from pyiceberg.catalog import load_catalog
cat = load_catalog("polaris", type="rest",
    uri=os.environ["POLARIS_CATALOG_URI"], warehouse="quickstart_catalog",
    credential=f'{os.environ["POLARIS_CLIENT_ID"]}:{os.environ["POLARIS_CLIENT_SECRET"]}',
    **{"s3.endpoint": os.environ["POLARIS_MINIO_ENDPOINT"],
       "s3.access-key-id": os.environ["POLARIS_S3_ACCESS_KEY_ID"],
       "s3.secret-access-key": os.environ["POLARIS_S3_SECRET_ACCESS_KEY"],
       "header.X-Iceberg-Access-Delegation": ""})
df = cat.load_table(("default", "transactions_scored")).scan().limit(5).to_arrow()
print(df.select(["transaction_id", "fraud_probability"]))
EOF
```

## Build and load (Minikube)

The shaded JAR targets **Java 17** (`maven.compiler.release` in `jobs/flink-sql-runner/pom.xml`), matching the **`flink:1.20.3-java17`** base image in `Dockerfile`. If you see `UnsupportedClassVersionError`, rebuild the JAR after changing the POM, rebuild the image, and reload it into the cluster.

**Use the repository root as the Docker build context.** Do not run `docker build .` from `apps/base/flink-jobs`: the `COPY` instructions reference `jobs/` and `apps/` paths that only exist when the context is the repo root.

```bash
cd /path/to/kafka-flink-iceberg-fraud-agent-gitops   # repository root
cd jobs/flink-sql-runner && mvn -DskipTests package && cd ../..
docker build -f apps/base/flink-jobs/Dockerfile -t flink-sql-runner:1.20 .
# Confirm the S3 entrypoint wrapper is in the image (must print OK):
docker run --rm flink-sql-runner:1.20 sh -c 'test -f /docker-entrypoint.orig.sh && echo OK'
minikube image load flink-sql-runner:1.20
```

`FlinkDeployment` **`spec.image`** is **`flink-sql-runner:1.20`** — build, verify, and load **that exact tag**. If you only tagged **`latest`**, either rebuild with **`-t flink-sql-runner:1.20`** or **`docker tag flink-sql-runner:latest flink-sql-runner:1.20`** then **`minikube image load flink-sql-runner:1.20`**.

Kubernetes **`imagePullPolicy: IfNotPresent`** can leave an **old** image on the node under the same tag. After rebuilding, restart Flink pods or bump **`restartNonce`** on the `FlinkDeployment`. Use **`docker build --no-cache ...`** if the verify step fails after changes.
