# Fraud Score Enricher

## What It Does

`fraud-score-enricher` is a persistent Flink streaming job (`ModelScorerJob`) that scores every incoming transaction in real time:

1. **Source** — Reads the `transactions` Iceberg table as a streaming source, polling for new snapshots every 5 seconds
2. **Enrich** — For each row, makes an async HTTP call to the KServe V2 inference endpoint with 3 features: `amount`, `amount_velocity_5min`, `distance_from_home_km`
3. **Sink** — Appends `fraud_probability` (0.0–1.0) to the row and writes it to the `transactions_scored` Iceberg table
4. **Fault tolerance** — Checkpoints to S3 every 60s using a RocksDB state backend. On KServe timeout or HTTP error, emits `fraud_probability = -1.0` as a sentinel so the pipeline never stalls

**KServe endpoint** (configured via `KSERVE_ENDPOINT` env var):
```
http://fraud-detector.kubeflow-user-example-com.svc.cluster.local/v2/models/fraud-detector/infer
```

**Source table**: `polaris_catalog.default.transactions`  
**Sink table**: `polaris_catalog.default.transactions_scored`

### Output Schema

| Column | Type | Notes |
|--------|------|-------|
| `transaction_id` | STRING | |
| `user_id` | INT | |
| `amount` | DOUBLE | |
| `merchant` | STRING | |
| `lat` | DOUBLE | |
| `lon` | DOUBLE | |
| `ts` | TIMESTAMP(3) | |
| `processing_time` | TIMESTAMP(3) | |
| `amount_velocity_5min` | DOUBLE | |
| `distance_from_home_km` | DOUBLE | |
| `fraud_probability` | DOUBLE | `-1.0` = KServe error/timeout |

---

## Confirming It Is Working

### 1. Check job status

```bash
kubectl get flinkdeployment -n flink-system fraud-score-enricher
```

Expected: `JOB STATUS = RUNNING`, `LIFECYCLE STATE = STABLE`

### 2. Check record counts (source in / sink out)

```bash
JM_POD=$(kubectl get pod -n flink-system -l component=jobmanager,app=fraud-score-enricher -o jsonpath='{.items[0].metadata.name}')
JOB_ID=$(kubectl exec -n flink-system $JM_POD -- curl -s http://localhost:8081/jobs | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
kubectl exec -n flink-system $JM_POD -- curl -s "http://localhost:8081/jobs/${JOB_ID}" \
  | python3 -c "
import json, sys
for v in json.load(sys.stdin)['vertices']:
    print(v['name'][:70], '| in:', v['metrics'].get('read-records','?'), '| out:', v['metrics'].get('write-records','?'))
"
```

The `in` counter should increase as new transactions arrive. If the synthetic producer is paused, the counter will be static — that is expected.

### 3. Confirm checkpoints are completing

```bash
kubectl logs -n flink-system $JM_POD --tail=30 | grep "Completed checkpoint"
```

A new checkpoint should appear approximately every 60 seconds while the job is running.

### 4. Check for KServe errors (fraud_probability = -1.0)

```bash
kubectl logs -n flink-system $JM_POD --tail=50 | grep -i "kserve\|error\|exception"
```

Occasional `-1.0` sentinel values are tolerable. Continuous errors indicate the `fraud-detector` InferenceService is not ready.

Check KServe model status:

```bash
kubectl get inferenceservice -n kubeflow-user-example-com fraud-detector
```

### 5. Check the Iceberg sink is receiving data

When the producer is running, new Iceberg snapshots should appear in the sink table every few minutes (Flink buffers rows before committing a file):

```bash
kubectl exec -n minio $(kubectl get pod -n minio -l app=minio -o jsonpath='{.items[0].metadata.name}') \
  -- mc ls --recursive myminio/iceberg-warehouse/polaris/default/transactions_scored/data/ | tail -5
```

---

## Source Code

| File | Purpose |
|------|---------|
| `jobs/flink-sql-runner/src/main/java/org/example/fraud/flink/ModelScorerJob.java` | Job entry point — sets up Iceberg source, async enrichment, and Iceberg sink |
| `jobs/flink-sql-runner/src/main/java/org/example/fraud/flink/KServeAsyncFunction.java` | Async I/O function — builds KServe V2 payload, parses response, emits enriched row |

---

## Dependencies

The job requires these services to be healthy before starting:

| Service | Namespace | Check |
|---------|-----------|-------|
| Polaris REST catalog | `polaris` | `kubectl get pod -n polaris -l app=polaris` |
| MinIO | `minio` | `kubectl get pod -n minio -l app=minio` |
| KServe `fraud-detector` | `kubeflow-user-example-com` | `kubectl get inferenceservice -n kubeflow-user-example-com fraud-detector` |

If any of these are unavailable at startup the job will fail. See [FLINK.md](FLINK.md) for how to restart a failed FlinkDeployment.


---

## Downstream: fraud-score-enricher → Fraud Alert Agent

The `fraud-score-enricher` Flink job writes scored rows to Iceberg `polaris_catalog.default.transactions_scored`.
A second Flink job (`fraud-score-kafka-publisher`) reads this table in streaming mode and publishes each row
to the `scored-transactions` Kafka topic (3 partitions). The fraud alert agent consumes this topic:

```
fraud-score-enricher (Flink ModelScorerJob)
  └─► Iceberg polaris_catalog.default.transactions_scored
         └─► Flink fraud-score-kafka-publisher (apps/base/flink-jobs/flink_scored_kafka_publisher.sql)
                └─► Kafka scored-transactions (partitions=3)
                       └─► alert_monitor (AIOKafkaConsumer, group=fraud-alert-agent)
                              └─► LangGraph 7-node investigation graph
                                     └─► fraud.investigations Iceberg table
```

**Sub-5s alert latency**: `alert_monitor` processes each Kafka message within ~5s of Flink publishing it.

**Triggering a test investigation** (bypasses ML pipeline, useful in dev):
```bash
kubectl port-forward svc/synthetic-transaction-producer -n kafka 8080:8080
curl -X POST http://localhost:8080/inject/scored \
  -H "Content-Type: application/json" \
  -d '{"user_id": 99999, "amount": 8500.00, "fraud_probability": 0.95, "merchant": "Test Merchant"}'
```

**Verify the pipeline end-to-end:**
```bash
# 1. Check Flink publisher is running
kubectl get pod -n flink-system -l app=fraud-score-kafka-publisher

# 2. Check scored-transactions has messages
kubectl exec -n kafka ... -- kafka-console-consumer.sh \
  --bootstrap-server platform-cluster-kafka-bootstrap:9092 \
  --topic scored-transactions --max-messages 3

# 3. Check alert_monitor consumer lag (should be 0 or decreasing)
kubectl exec -n kafka ... -- kafka-consumer-groups.sh \
  --bootstrap-server platform-cluster-kafka-bootstrap:9092 \
  --describe --group fraud-alert-agent
```
