# Quickstart: Validate Kafka → Flink → Iceberg (Polaris) pipeline

**Feature**: `002-e2e-streaming-pipeline`  
**Date**: 2026-04-04

Prerequisites: Minikube cluster bootstrapped per `specs/001-fluxcd-gitops-repo/quickstart.md` (Flux, Strimzi Kafka, Flink Operator, Polaris, MinIO, secrets applied). Create `minio-flink-s3-credentials` in `flink-system` as documented in `docs/runbooks/bootstrap.md`.

## 1. Confirm platform components

```bash
kubectl get kafka -n kafka
kubectl get flinkdeployment -n flink-system
kubectl get pods -n polaris
kubectl get pods -n minio
```

## 2. Confirm Kafka topic

The `transactions` topic is declared as a Strimzi `KafkaTopic` in `infrastructure/configs/base/kafka/kafka-topic-transactions.yaml` and is included from `infrastructure/configs/minikube` (Flux `infra-configs`).

```bash
kubectl -n kafka get kafkatopic transactions
```

If you see **NotFound**, the `KafkaTopic` custom resource was never applied: Flux may not have reconciled yet, your cluster may be tracking another Git branch, or you are testing before pushing. From the **repository root**, apply configs (or wait for Flux to catch up):

```bash
kubectl apply -k infrastructure/configs/minikube
# or, if you use Flux on this clone:
flux reconcile kustomization infra-configs --with-source
```

Then confirm again: `kubectl -n kafka get kafkatopic transactions`.

## 3. Build and load Flink image

Stay in the **repository root** for `docker build` (the final `.` is the build context). Running `docker build` from `apps/base/flink-jobs` will fail: the Dockerfile copies `jobs/...` and `apps/...` paths that only exist when the context is the repo root.

After `mvn -DskipTests package` in `jobs/flink-sql-runner`:

```bash
docker build -f apps/base/flink-jobs/Dockerfile -t flink-sql-runner:1.20 .
minikube image load flink-sql-runner:1.20
```

(Tag must match `FlinkDeployment` `spec.image` in `apps/base/flink-jobs/resources.yaml`.)

Build and load the **synthetic producer** (required — there is no registry image):

```bash
docker build -t synthetic-transaction-producer:latest -f apps/base/synthetic-transaction-producer/Dockerfile apps/base/synthetic-transaction-producer
minikube image load synthetic-transaction-producer:latest
```

## 4. Confirm Flink job

```bash
kubectl -n flink-system get flinkdeployment sample-fraud-stream -o wide
```

Job should reach **RUNNING** with **RUNNING** job status in Flink UI or operator status. Align `flink_streaming_job.sql` Polaris `credential` with your `polaris-bootstrap-credentials` password (replace the `changeme` placeholder in-cluster via ConfigMap edit or GitOps patch — do not commit real passwords).

## 5. Produce test events

Deploy the synthetic producer via `apps/minikube` (Flux or `kubectl apply -k apps/minikube`). Alternatively use `kubectl run` + `kafka-console-producer` with a payload matching `contracts/kafka-transaction-event.md`.

## 6. Verify Kafka → Flink → Iceberg end-to-end

Use **`docs/runbooks/verify-kafka-flink-iceberg.md`** for step-by-step checks: topic offsets / consumer lag, Flink job + checkpoints + REST metrics, then a **PyIceberg** read of **`default.transactions`** or MinIO paths under **`iceberg-warehouse`**.

**Shortcut:** `scripts/verify_polaris_pyiceberg.py` validates Polaris + MinIO + PyIceberg (smoke table), not the Flink-owned **`transactions`** table — use the runbook’s scan for pipeline verification.

Success: Kafka **offsets move**, Flink job **RUNNING** with **checkpoints completing**, Iceberg table **`default.transactions`** returns **rows** whose columns match the SQL pipeline.

## 7. Observe health

- **Kafka**: consumer lag for Flink consumer group.  
- **Flink**: checkpoints completed, `uptime`, no restarts in loop.  
- **Polaris / MinIO**: no 5xx on catalog; bucket objects growing.

## 8. Troubleshooting pointers

| Symptom | Check |
|---------|--------|
| `kafkatopic transactions` NotFound | CR not applied — `kubectl apply -k infrastructure/configs/minikube` or Flux reconcile; ensure `Kafka` `platform-cluster` is Ready and the topic operator is running |
| Flink job not starting | `kubectl logs -n flink-system deploy/flink-kubernetes-operator`; Flink pod logs |
| No Iceberg files | S3/MinIO credentials on TM/JM; Polaris catalog URI; Iceberg connector logs |
| Lag growing | TM CPU/memory; Kafka broker disk; increase parallelism in FlinkDeployment |
