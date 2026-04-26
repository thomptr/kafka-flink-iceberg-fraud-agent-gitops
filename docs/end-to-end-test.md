# End-to-End Test: Fraud Detection Pipeline

## Pipeline Overview

```
transactions (Kafka)
  → sample-fraud-stream (Flink, streaming)
    → polaris_catalog.default.transactions (Iceberg)
      → fraud-score-enricher (Flink, streaming → KServe)
        → polaris_catalog.default.transactions_scored (Iceberg)
          → fraud-score-kafka-publisher (Flink, batch — must be restarted per run)
            → scored-transactions (Kafka)
              → fraud-alert-agent (Python consumer)
                → Postgres alert + LangGraph investigation
                  → Slack (#fraud-urgent / #fraud-escalations / #fraud-alerts)
```

Thresholds (from `fraud-agent-config` ConfigMap):
- `fraud_probability >= 0.85` → `critical` severity → `#fraud-urgent`
- `fraud_probability >= 0.70` → `high` severity → `#fraud-escalations`
- `fraud_probability >= 0.50` → `medium` severity → `#fraud-alerts`
- Below `0.50` → dropped silently by `alert_monitor.py`

---

## Path A: Full Pipeline (transactions → Flink → Iceberg → Kafka → agent → Slack)

### Step 1 — Verify all Flink jobs are running

```bash
kubectl get pods -n flink-system
```

Expected running pods: `sample-fraud-stream-*`, `sample-fraud-stream-taskmanager-*`,
`fraud-score-enricher-*`, `fraud-score-enricher-taskmanager-*`.

The `fraud-score-kafka-publisher` pod will not be present — it is a batch job that finishes
after each run and must be restarted manually (see Step 4).

### Step 2 — Send a transaction to the `transactions` topic

Use `-it` only for the producer (interactive input). Do not use multi-line backslash
continuation when pasting — run as a single line:

```bash
kubectl exec -it platform-cluster-kafka-0 -n kafka -- /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic transactions
```

At the `>` prompt paste this JSON, press **Enter**, then **Ctrl+C**:

```json
{"transaction_id":"e2e-test-001","user_id":99999,"amount":4999.99,"merchant":"Suspicious Corp LLC","lat":51.5074,"lon":-0.1278,"ts":"2026-04-26T20:00:00.000Z"}
```

Confirm it landed (no `-it`, single line):

```bash
kubectl exec -n kafka platform-cluster-kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic transactions --from-beginning --max-messages 1 --timeout-ms 10000
```

### Step 3 — Wait for Flink to score the transaction (~60–90 seconds)

`sample-fraud-stream` writes to Iceberg on its checkpoint interval (60 s).
`fraud-score-enricher` polls Iceberg for new snapshots (5 s interval) and calls KServe
to produce `fraud_probability`, then writes to `transactions_scored`.

Watch `fraud-score-enricher` for new snapshot activity:

```bash
kubectl logs -n flink-system -l app=fraud-score-enricher --tail=20 -f
```

Look for a log line that is NOT `Current table snapshot is already enumerated` — that
indicates a new snapshot was picked up and scored.

### Step 4 — Restart `fraud-score-kafka-publisher` to publish scored records to Kafka

This job is a batch FlinkDeployment that reads all unread rows from `transactions_scored`
and exits. It does not run continuously. To trigger a fresh run, delete the existing
FlinkDeployment and let FluxCD reconcile it (or apply directly):

```bash
kubectl delete flinkdeployment fraud-score-kafka-publisher -n flink-system
kubectl apply -f apps/base/flink-jobs/resources.yaml
```

Wait ~30 seconds for the job to start, run, and finish:

```bash
kubectl get pods -n flink-system -w
```

The pod sequence is: `Pending` → `Running` → the job manager logs
`Job switched from RUNNING to FINISHED` → taskmanager pod is released.

Watch logs to confirm rows were published:

```bash
kubectl logs -n flink-system -l app=fraud-score-kafka-publisher --tail=30
```

### Step 5 — Verify the record arrived in `scored-transactions`

```bash
kubectl exec -n kafka platform-cluster-kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic scored-transactions --from-beginning --max-messages 5 --timeout-ms 10000
```

Expected: a JSON record with `transaction_id`, `fraud_probability`, `amount_velocity_5min`,
`distance_from_home_km`, `ts`, `processing_time`.

---

## Path B: Bypass Flink — inject directly into `scored-transactions` (fast agent test)

Use this when you want to test the agent/Slack path without waiting for the full Flink
pipeline or when `fraud-score-kafka-publisher` is not running.

Write a pre-scored record directly (single line, `-it` for producer):

```bash
kubectl exec -it platform-cluster-kafka-0 -n kafka -- /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic scored-transactions
```

At the `>` prompt paste this JSON, press **Enter**, then **Ctrl+C**:

```json
{"transaction_id":"e2e-test-direct-001","user_id":99999,"amount":4999.99,"merchant":"Suspicious Corp LLC","fraud_probability":0.9850,"amount_velocity_5min":9500.00,"distance_from_home_km":487.50,"ts":"2026-04-26T20:00:00.000Z","processing_time":"2026-04-26T20:00:00.000Z"}
```

Verify it landed:

```bash
kubectl exec -n kafka platform-cluster-kafka-0 -- /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic scored-transactions --from-beginning --max-messages 1 --timeout-ms 10000
```

---

## Step 6 — Verify the agent processed the alert

### Watch agent logs in real time

```bash
kubectl logs -n fraud-agent -l app=fraud-alert-agent --tail=40 -f
```

Look for log events: `alert_monitor_message`, then the LangGraph node sequence
(`triage_node`, `analysis_node`, `recommendation_node`, `report_node`), then
`slack_notification` or `kafka_delivered`.

Expected time from message consumed to Slack: **30–90 seconds** (dominated by Ollama
LLM inference; `llama3.1:8b` on CPU takes ~15–25 s per call).

### Query the alert via the REST API

Port-forward the agent service:

```bash
kubectl port-forward svc/fraud-alert-agent 8000:8000 -n fraud-agent
```

In a second terminal, look up the alert by transaction ID:

```bash
curl -s -H "X-API-Key: dev-test-key" http://localhost:8000/alerts/by-transaction/e2e-test-direct-001 | python3 -m json.tool
```

Or list all recent alerts:

```bash
curl -s -H "X-API-Key: dev-test-key" "http://localhost:8000/alerts?page_size=5" | python3 -m json.tool
```

A completed alert will have `"status": "completed"` and a non-empty `"final_action"`
(`block`, `escalate`, or `notify`).

---

## Step 7 — Verify Slack notification

Check the appropriate Slack channel based on `final_action`:

| `final_action` | Channel |
|---|---|
| `block` | `#fraud-urgent` |
| `escalate` | `#fraud-escalations` |
| `notify` | `#fraud-alerts` |

The notification includes: alert ID, transaction ID, severity, amount, fraud probability,
LLM explanation (truncated to 300 chars), and a link to the investigation UI.

If no Slack message appears, check whether `SLACK_WEBHOOK_URL` is set:

```bash
kubectl get secret fraud-agent-secrets -n fraud-agent -o jsonpath='{.data.slack-webhook-url}' | base64 -d && echo
```

An empty value means the agent skips Slack silently (see `notification_service.py:16`).

---

## Clearing Topics Between Test Runs

The `scored-transactions` topic has a 24-hour retention (`retention.ms=86400000`).
To start clean, delete and recreate the KafkaTopic CR (Strimzi handles the rest):

```bash
kubectl delete kafkatopic scored-transactions -n kafka
kubectl apply -f apps/base/flink-jobs/kafka-topic-scored-transactions.yaml
```

To avoid duplicate alert creation for the same `transaction_id` (the agent uses
`ON CONFLICT DO NOTHING`), use a unique `transaction_id` in each test run or reset
the Postgres `alerts` table:

```bash
kubectl exec -it postgres-0 -n fraud-agent -- psql -U fraud_agent -d fraud_agent -c "DELETE FROM alerts;"
```

---

## Known Issues

| Issue | Impact | Workaround |
|---|---|---|
| `fraud-score-kafka-publisher` runs as a batch job and exits | New scored rows in Iceberg are not published to Kafka until the job is manually restarted | Use Path B (direct inject) or restart the FlinkDeployment (Step 4) |
| `fraud-investigation-ui` pod in `ImagePullBackOff` | Investigation UI link in Slack 404s | Build and load image: `minikube image load fraud-investigation-ui:latest` |
| `fraud-alert-agent` has a second pod in `Init:CrashLoopBackOff` | Does not affect the running pod; indicates a pending migration conflict | Check `kubectl logs fraud-alert-agent-<new-pod> -n fraud-agent -c migrate` |
