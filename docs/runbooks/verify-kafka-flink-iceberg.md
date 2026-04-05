# Verify Kafka → Flink → Iceberg (Polaris / MinIO)

Use this after the synthetic producer is running and `FlinkDeployment` **sample-fraud-stream** is **RUNNING** (see `specs/002-e2e-streaming-pipeline/quickstart.md`).

**Pipeline in this repo**

| Stage | What to check |
|-------|----------------|
| **Kafka** | Topic **`transactions`** receives JSON events; consumer lag for Flink stays bounded. |
| **Flink** | Job **RUNNING**; checkpoints **COMPLETED**; sink operator **numRecordsOut** (or logs) increasing. |
| **Iceberg** | Table **`quickstart_catalog`.`default`.`transactions`** (from `flink_streaming_job.sql`) has rows; MinIO bucket **`iceberg-warehouse`** gains data files. |

---

## 1. Kafka: traffic on `transactions`

**Topic exists**

```bash
kubectl -n kafka get kafkatopic transactions
```

**Message flow (Kafka UI)**  
Open the topic in Kafka UI and confirm the message rate / latest offsets move while the producer runs.

**Offsets from a broker pod** (Strimzi 0.40+ paths may vary; adjust container name if needed)

```bash
POD=$(kubectl -n kafka get pod -l strimzi.io/name=platform-cluster-kafka -o jsonpath='{.items[0].metadata.name}')
kubectl -n kafka exec "$POD" -c kafka -- \
  bin/kafka-run-class.sh kafka.tools.GetOffsetShell \
  --broker-list localhost:9092 --topic transactions
```

Run twice a few seconds apart: partition **offsets** should **increase** if the producer is sending.

**Consumer lag (Flink reading the topic)**  
In Kafka UI, find the consumer group for the Flink SQL Kafka source (name often contains **`sample-fraud-stream`** or **`flink`**). **Lag** should stay bounded under steady load (not grow forever); brief spikes are normal.

---

## 2. Flink: job healthy and processing

**Deployment / job status**

```bash
kubectl -n flink-system get flinkdeployment sample-fraud-stream -o wide
kubectl -n flink-system get pods -l app.kubernetes.io/managed-by=flink-kubernetes-operator
```

Expect **Job status RUNNING** and TaskManager pod(s) **Running**.

**Checkpointing** (Iceberg commits align with successful checkpoints in this setup)

```bash
JM=$(kubectl -n flink-system get pods -l app=sample-fraud-stream,component=jobmanager -o jsonpath='{.items[0].metadata.name}')
kubectl -n flink-system logs "$JM" -c flink-main-container --tail=200 | rg -i checkpoint
```

If the label selector returns nothing, run `kubectl -n flink-system get pods --show-labels` and pick the JobManager pod name manually.

Look for **completed** checkpoints, not repeated **failure** messages.

**REST API (metrics)** — port-forward the JobManager REST service (name may differ slightly):

```bash
kubectl -n flink-system get svc | rg sample-fraud
kubectl -n flink-system port-forward svc/<rest-service-name> 8081:8081
```

The REST Service is usually named like **`sample-fraud-stream-rest`** (suffix **`rest`**). Then open `http://127.0.0.1:8081` and check the running job: **Records Received** / **Records Sent** (or sink **numRecordsOut**) should increase over time.

---

## 3. Iceberg: rows in `default.transactions`

The SQL job creates **`polaris_catalog.default.transactions`** (namespace **`default`**, table **`transactions`**). In `flink_streaming_job.sql` the three-part name is written with **backticks** around `default` because **`default` is a reserved SQL keyword** in Flink/Calcite.

**Option A — PyIceberg (read-only scan)**  

From the repo root, with the same Polaris / MinIO env pattern as `specs/001-fluxcd-gitops-repo/quickstart.md` (port-forward **Polaris 8181** if querying from your laptop):

```bash
kubectl -n polaris port-forward svc/polaris 8181:8181
```

Install once: `uv pip install pyiceberg pyarrow boto3` (or `pip install`).

```bash
export POLARIS_CATALOG_URI="http://127.0.0.1:8181/api/catalog"
export POLARIS_CLIENT_ID="root"
export POLARIS_CLIENT_SECRET='<same as polaris-bootstrap-credentials client secret>'
export POLARIS_SCOPE="PRINCIPAL_ROLE:ALL"
export POLARIS_S3_ACCESS_KEY_ID='<minio root user>'
export POLARIS_S3_SECRET_ACCESS_KEY='<minio root password>'
export POLARIS_MINIO_ENDPOINT="http://127.0.0.1:9000"   # or minikube service URL if forwarded
```

```python
import os
from pyiceberg.catalog import load_catalog

def rest_props():
    return {
        "client.region": "us-east-1",
        "header.X-Iceberg-Access-Delegation": "",
        "s3.endpoint": os.environ["POLARIS_MINIO_ENDPOINT"],
        "s3.access-key-id": os.environ["POLARIS_S3_ACCESS_KEY_ID"],
        "s3.secret-access-key": os.environ["POLARIS_S3_SECRET_ACCESS_KEY"],
        "s3.region": "us-east-1",
    }

cat = load_catalog(
    "polaris",
    type="rest",
    uri=os.environ["POLARIS_CATALOG_URI"],
    warehouse="quickstart_catalog",
    credential=f'{os.environ["POLARIS_CLIENT_ID"]}:{os.environ["POLARIS_CLIENT_SECRET"]}',
    **rest_props(),
)
t = cat.load_table(("default", "transactions"))
df = t.scan().limit(10).to_arrow()
print("rows (up to 10):", df.num_rows)
print(df)
```

**Success:** `rows` **> 0** and columns match the SQL pipeline (**transaction_id**, **user_id**, **amount**, …).

**Option B — MinIO object growth**

```bash
kubectl -n minio port-forward svc/minio 9000:9000
# mc alias set local http://127.0.0.1:9000 <user> <password>
# mc ls --recursive local/iceberg-warehouse/ | rg transactions | tail
```

New **`.parquet`** (or Iceberg data) paths under the warehouse for **`default`** / **`transactions`** indicate commits.

---

## 4. When something is wrong

| Symptom | Where to look |
|---------|----------------|
| Offsets **not** increasing | Synthetic producer paused or down; `kubectl -n kafka get pods`. |
| Offsets up, Flink lag **grows** forever | Flink job failing or backpressured; TM logs, checkpoint errors. |
| Flink **RUNNING**, Iceberg **empty** | Polaris **401/403** / **`unauthorized_client`**: missing **`polaris-flink-oauth`** in `flink-system` or password not matching **`polaris-bootstrap-credentials`** (see `docs/runbooks/bootstrap.md`); MinIO credentials on Flink TM; Polaris catalog **warehouse** path. |
| **`Unable to find warehouse quickstart_catalog`** | Register the catalog in Polaris: wait for Job **`polaris-ensure-quickstart-catalog`** (namespace **`polaris`**) to succeed, or run `python3 infrastructure/controllers/base/polaris/ensure_polaris_catalog.py` (see `docs/runbooks/bootstrap.md`). |
| **`NoSuchNamespaceException` (namespace `default`)** | The Iceberg namespace must exist in Polaris before creating a table. `flink_streaming_job.sql` runs `CREATE DATABASE IF NOT EXISTS` for `polaris_catalog` and the `default` namespace before `CREATE TABLE`. Reconcile the Flink SQL ConfigMap and restart the job. |
| **S3 / MinIO `The specified bucket does not exist` (404)** | Create the **`iceberg-warehouse`** bucket in MinIO (same name as the first segment of `POLARIS_DEFAULT_BASE_LOCATION`). The **`polaris-ensure-quickstart-catalog`** Job does this automatically when it runs with `polaris-storage-credentials`. Or: `mc mb` / Console, then restart the Flink job. |
| PyIceberg **table not found** | Flink never created the table (job not started or SQL error); or wrong **namespace** (**default**) / **table** name. |

SQL catalog password must match **`polaris-bootstrap-credentials`** (replace **`changeme`** in-cluster — do not commit real secrets). See `apps/base/flink-jobs/README.md` and `specs/002-e2e-streaming-pipeline/quickstart.md`.
