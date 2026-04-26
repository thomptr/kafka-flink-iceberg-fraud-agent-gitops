# Quickstart: Agentic Fraud Alert Orchestration

**Branch**: `004-fraud-alert-agent` | **Date**: 2026-04-25

This guide covers running the service locally (Docker Compose) and deploying it to the
Minikube cluster. It also provides integration test scenarios and verification commands.

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ | `python --version` |
| Docker | 24+ | `docker --version` |
| kubectl | 1.28+ | `kubectl version --client` |
| Minikube profile `fraud-gitops` | running | `minikube status -p fraud-gitops` |
| Ollama (cluster pod) | ≥0.1.32 | `kubectl get pod -n ollama` |
| `llama3:8b` model pulled | — | `kubectl exec -n ollama deploy/ollama -- ollama list` |

---

## Local Development (Docker Compose)

```bash
cd src/fraud-alert-agent

# Start Postgres + Ollama stub (or point to cluster Ollama via port-forward)
docker compose up -d postgres

# Install dependencies
pip install -e ".[dev]"

# Apply database migrations
alembic upgrade head

# Set required environment variables
export DATABASE_URL="postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_agent"
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3:8b"
export FRAUD_API_KEY="dev-test-key"
export SLACK_WEBHOOK_URL=""          # leave empty to skip Slack in dev
export ICEBERG_CATALOG_URI="http://localhost:8181/api/catalog"  # port-forward Polaris
export MINIO_ENDPOINT="http://localhost:9000"
export AWS_ACCESS_KEY_ID="minioadmin"
export AWS_SECRET_ACCESS_KEY="minioadmin"

# Run the service
uvicorn app.main:app --reload --port 8000
```

The alert monitor worker starts automatically on app lifespan startup and streams
messages from the `scored-transactions` Kafka topic via an `aiokafka` consumer loop.
Messages with `fraud_probability` below 0.50 are skipped; anything at or above that
threshold creates an alert and triggers a LangGraph investigation.

---

## Deploying to Minikube

```bash
# Build and load the container image
docker build -t fraud-alert-agent:0.1.0 src/fraud-alert-agent/
minikube image load fraud-alert-agent:0.1.0 -p fraud-gitops

# Create the namespace and required secrets
kubectl apply -f apps/base/fraud-alert-agent/namespace.yaml

export SLACK_WEBHOOK_URL={your-slack-webhook-url}

kubectl create secret generic fraud-agent-secrets -n fraud-agent \
  --from-literal=database-url="postgresql+asyncpg://fraud:fraud@postgres.fraud-agent.svc.cluster.local:5432/fraud_agent" \
  --from-literal=api-key="$(openssl rand -hex 32)" \
  --from-literal=slack-webhook-url=$SLACK_WEBHOOK_URL

# Deploy Postgres (dev/test only — use managed Postgres in production)
kubectl apply -f apps/base/fraud-alert-agent/postgres.yaml

# Deploy the agent service
kubectl apply -k apps/minikube/fraud-alert-agent/

# Verify
kubectl rollout status deployment/fraud-alert-agent -n fraud-agent
kubectl get pod -n fraud-agent
```

---

## Integration Test Scenarios

### Scenario 1: End-to-End Alert Investigation (P1 Story)

The agent is **event-driven**: it streams the `scored-transactions` Kafka topic and reacts
immediately when a message with `fraud_probability ≥ 0.50` arrives. Flink is the normal
producer; for testing, you inject the message directly with `kcat`.

**Routing thresholds** (set via `FRAUD_THRESHOLD_*` env vars, defaults shown):

| `fraud_probability` | Route | Slack channel |
|---------------------|-------|---------------|
| ≥ 0.85 | `CRITICAL` → full investigation | `#fraud-urgent` |
| 0.70 – 0.84 | `STANDARD` → full investigation | `#fraud-alerts` |
| 0.50 – 0.69 | `MONITOR_ONLY` → triage only | `#fraud-alerts` |
| < 0.50 | skipped — no alert created | — |

#### Step 1 — Set up port-forwards and capture the API key

```bash
kubectl port-forward -n fraud-agent svc/fraud-alert-agent 8000:8000 &
kubectl port-forward -n kafka svc/platform-cluster-kafka-bootstrap 9092:9092 &

API_KEY=$(kubectl get secret fraud-agent-secrets -n fraud-agent \
  -o jsonpath='{.data.api-key}' | base64 -d)
```

#### Step 2 — Inspect existing messages on the topic

Before injecting, check what real scored-transaction messages look like (reads from the
earliest offset using a temporary consumer group):

```bash
kcat -b localhost:9092 \
     -t scored-transactions \
     -o beginning \
     -C -c 5 \
     -f '%T  key=%k  value=%s\n'
```

A well-formed message looks like:

```json
{
  "transaction_id": "txn-abc123",
  "user_id": 42,
  "amount": 3250.00,
  "merchant": "Electronics Plus",
  "fraud_probability": 0.91,
  "model_version": "fraud-detector/v3",
  "scored_at": "2026-04-26T12:00:00Z"
}
```

If the topic is empty (no Flink job running), skip straight to Step 3.

#### Step 3 — Inject a synthetic critical fraud transaction

Pick a unique `transaction_id` so you can track it through logs.

```bash
TXN_ID="test-fraud-$(date +%s)"

# Produce a single JSON message keyed by transaction_id
echo "{
  \"transaction_id\": \"${TXN_ID}\",
  \"user_id\": 9001,
  \"amount\": 4750.00,
  \"merchant\": \"Luxury Watch Store\",
  \"fraud_probability\": 0.92,
  \"model_version\": \"fraud-detector/v3\",
  \"scored_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
}" | kcat -b localhost:9092 \
         -t scored-transactions \
         -P -k "${TXN_ID}"

echo "Injected transaction_id: ${TXN_ID}"
```

#### Step 4 — Verify the alert was created (within ~5 seconds)

```bash
sleep 5

curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts?severity=critical&status=open" \
  | python3 -m json.tool
```

Locate the entry where `transaction_id == "${TXN_ID}"` and capture its `id`:

```bash
ALERT_ID="<id from above>"
```

#### Step 5 — Follow the investigation to completion (~60 seconds)

```bash
# Watch agent log output for your transaction
kubectl logs -n fraud-agent deploy/fraud-alert-agent -f \
  | grep "\"transaction_id\":\"${TXN_ID}\""

# Poll the investigation endpoint until status = completed
watch -n 10 "curl -s -H 'X-API-Key: ${API_KEY}' \
  http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigation \
  | python3 -m json.tool"
```

#### Step 6 — Confirm all downstream side-effects

**Slack notification** — the escalation node fires during the investigation:

- `#fraud-urgent` receives a block message with `alert_id`, `transaction_id`, `amount`,
  `fraud_probability`, and the LLM-generated explanation.
- If `SLACK_WEBHOOK_URL` is empty (local dev), the notification is skipped gracefully and
  a `escalation_slack_error` log line is emitted instead.

**Kafka `fraud-alert-events` topic** — published by the escalation node:

```bash
kcat -b localhost:9092 -t fraud-alert-events -o beginning -C -c 5 \
  -f '%s\n' | python3 -m json.tool
```

Expected shape:
```json
{
  "event_type": "escalation_triggered",
  "source": "fraud-alert-agent",
  "payload": {
    "alert_id": "<ALERT_ID>",
    "final_action": "block",
    "severity": "critical",
    "fraud_probability": 0.92
  }
}
```

**Kafka `fraud-notifications` topic** — published by the report node after the Iceberg
investigation report is written:

```bash
kcat -b localhost:9092 -t fraud-notifications -o beginning -C -c 5 \
  -f '%s\n' | python3 -m json.tool
```

Expected shape:
```json
{
  "event_type": "investigation_completed",
  "source": "fraud-alert-agent",
  "payload": {
    "alert_id": "<ALERT_ID>",
    "final_action": "block",
    "iceberg_snapshot_id": 1234567890,
    "investigation_id": "<UUID>"
  }
}
```

**Investigation report in Iceberg** — the report node writes a row to the
`fraud.investigation_reports` Iceberg table via the Polaris catalog. Verify via
the agent's own query tool or `pyiceberg`:

```bash
kubectl exec -n fraud-agent deploy/fraud-alert-agent -- python3 -c "
from app.tools.iceberg_catalog import get_catalog
cat = get_catalog()
t = cat.load_table('fraud.investigation_reports')
print(t.scan(limit=5).to_pandas()[['alert_id','final_action','completed_at']])
"
```

#### Expected final state

| Check | Expected value |
|-------|----------------|
| `investigation.status` | `completed` |
| `investigation.evidence` | ≥ 3 items |
| `investigation.recommended_action` | `block` (for probability 0.92) |
| Slack `#fraud-urgent` | message received |
| `fraud-alert-events` topic | `escalation_triggered` event present |
| `fraud-notifications` topic | `investigation_completed` event present |
| Iceberg `fraud.investigation_reports` | row with matching `alert_id` |

---

### Scenario 1b: Impossible-Travel Fraud via Raw `transactions` Topic

This variant exercises the **full upstream pipeline** instead of bypassing it.
A message injected into the raw `transactions` topic flows through:

```
transactions (Kafka)
  → Flink streaming job  (computes amount_velocity_5min, distance_from_home_km)
  → transactions (Iceberg)
  → ML scorer            (writes fraud_probability to transactions_scored Iceberg)
  → Flink Kafka publisher
  → scored-transactions (Kafka)
  → fraud-alert-agent
```

Flink's feature engineering uses San Francisco **(37.7749, -122.4194)** as the
hardcoded home location. Putting the fraudulent transaction in a city far from SF
produces a large `distance_from_home_km` that drives the ML fraud score up.

> **Pipeline lag**: allow ~60–90 s for Flink feature engineering. End-to-end time
> depends on how frequently the ML scoring job runs — check with
> `kubectl get cronworkflow -n kubeflow` if alerts do not appear.

#### Step A — Port-forward Kafka and the producer control API

```bash
# Kafka (if not already forwarded from Scenario 1)
kubectl port-forward -n kafka svc/platform-cluster-kafka-bootstrap 9092:9092 &

# Synthetic-transaction-producer control API
kubectl port-forward -n kafka deploy/synthetic-transaction-producer 8080:8080 &
```

#### Step B — Read recent transactions and pick a target user

Read the last 10 messages from the raw `transactions` topic to find a real `user_id`
and understand the message schema:

```bash
kcat -b localhost:9092 \
     -t transactions \
     -o -10 \
     -C -e \
     -f '%s\n' | python3 -m json.tool
```

A raw transaction looks like:

```json
{
  "transaction_id": "3f2e1d4c-...",
  "user_id": 18432,
  "amount": 47.50,
  "merchant": "Corner Bakery",
  "lat": 37.8044,
  "lon": -122.2712,
  "ts": "2026-04-26T14:32:07.441Z"
}
```

Note the `user_id` and `ts` of a recent transaction — you will reuse the same
`user_id` and a `ts` within a minute of the original to simulate a simultaneous
purchase in a different part of the world.

#### Step C — Inject the impossible-travel twin transaction

Two approaches are available. **Option 1** uses the producer's `/inject` HTTP
endpoint (simpler, no shell quoting issues). **Option 2** uses `kcat` directly.

**Option 1 — producer `/inject` endpoint (recommended)**

```bash
USER_ID=18432                         # replace with the user_id from Step B
ORIG_TS="2026-04-26T14:32:07.441Z"   # replace with the ts from Step B
TXN_ID="fraud-travel-$(date +%s)"

curl -s -X POST http://localhost:8080/inject \
  -H "Content-Type: application/json" \
  -d "{
    \"transaction_id\": \"${TXN_ID}\",
    \"user_id\": ${USER_ID},
    \"amount\": 4890.00,
    \"merchant\": \"Tokyo Electronics Akihabara\",
    \"lat\": 35.6995,
    \"lon\": 139.7711,
    \"ts\": \"${ORIG_TS}\"
  }" | python3 -m json.tool

echo "Injected transaction_id: ${TXN_ID}"
```

**Option 2 — `kcat` direct produce**

```bash
USER_ID=18432
ORIG_TS="2026-04-26T14:32:07.441Z"
TXN_ID="fraud-travel-$(date +%s)"

echo "{
  \"transaction_id\": \"${TXN_ID}\",
  \"user_id\": ${USER_ID},
  \"amount\": 4890.00,
  \"merchant\": \"Tokyo Electronics Akihabara\",
  \"lat\": 35.6995,
  \"lon\": 139.7711,
  \"ts\": \"${ORIG_TS}\"
}" | kcat -b localhost:9092 \
         -t transactions \
         -P -k "${USER_ID}"
```

**Why these coordinates?** Flink computes:
```
distance_from_home_km = SQRT(POWER(lat - 37.7749, 2) + POWER(lon - (-122.4194), 2)) * 111
```
Tokyo `(35.6995, 139.7711)` → **≈ 29,100 km** from the SF home anchor.
Any city more than ~500 km from San Francisco will produce a meaningfully elevated
feature value. A few useful alternatives:

| City | lat | lon | Approx distance from SF |
|------|-----|-----|--------------------------|
| Tokyo | 35.6995 | 139.7711 | ~29,100 km |
| London | 51.5074 | -0.1278 | ~13,600 km |
| São Paulo | -23.5505 | -46.6333 | ~11,600 km |
| Sydney | -33.8688 | 151.2093 | ~11,900 km |

#### Step D — Confirm Flink picked up the message

Check the Flink job manager logs for a processed record count increase:

```bash
kubectl logs -n flink deploy/flink-sql-runner --tail=50 | grep -i "records\|checkpoint"
```

Then query the Iceberg `transactions` table to confirm the row landed with the
computed features:

```bash
kubectl exec -n fraud-agent deploy/fraud-alert-agent -- python3 -c "
from app.tools.iceberg_catalog import get_catalog
cat = get_catalog()
t = cat.load_table('default.transactions')
df = t.scan(limit=5).to_pandas()
print(df[['transaction_id','user_id','amount','distance_from_home_km','amount_velocity_5min']].to_string())
"
```

The injected row should show `distance_from_home_km ≈ 29100` and an elevated
`amount_velocity_5min` because the same `user_id` made another purchase within the
same 5-minute window.

#### Step E — Wait for ML scoring and verify the alert

Once the ML scorer runs and the `flink_scored_kafka_publisher` emits the record to
`scored-transactions`, the agent consumer will pick it up automatically. Follow
**Steps 4–6 from Scenario 1** to verify the alert, investigation, Slack notification,
and downstream Kafka events — the expected final state is identical.

To check whether the scored record arrived on the Kafka topic yet:

```bash
kcat -b localhost:9092 -t scored-transactions -o -20 -C -e -f '%s\n' \
  | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    if '${TXN_ID}' in r.get('transaction_id',''):
        print(json.dumps(r, indent=2))
"
```

---

### Scenario 2: Idempotency Check (P2 Story)

Verify that injecting the same transaction ID twice does not create duplicate alerts.

```bash
# Get current alert count
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts" | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"

# The alert monitor will attempt to process the duplicate snapshot entry
# Wait 15 seconds, then recheck count — total must not have increased
sleep 15
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts" | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"
```

**Expected**: Alert count unchanged.

---

### Scenario 3: Human Approval (P3 Story)

```bash
ALERT_ID="<alert id from scenario 1>"

# Approve the agent's recommendation
curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/alerts/${ALERT_ID}/decisions" \
  -d '{"actor": "analyst@example.com", "action": "approve", "outcome": "block"}' \
  | python3 -m json.tool

# Verify alert status changed to resolved
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts/${ALERT_ID}" | python3 -c \
  "import sys,json; a=json.load(sys.stdin); print('status:', a['status'])"
```

**Expected**: alert.status = `resolved`.

---

### Scenario 4: Override with Reason (P3 Story)

```bash
ALERT_ID="<a different alert id>"

curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/alerts/${ALERT_ID}/decisions" \
  -d '{"actor": "senior-analyst@example.com", "action": "override", "outcome": "monitor", "reason": "Known customer travelling abroad; confirmed via phone"}' \
  | python3 -m json.tool
```

**Expected**: Decision recorded with reason; alert.status = `resolved`.

---

### Scenario 5: Metrics Endpoint (P4 Story)

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/metrics?window_hours=24" | python3 -m json.tool
```

**Expected**: JSON with `alert_count`, `auto_resolution_rate`, `avg_time_to_decision_minutes`, `false_positive_rate`, `sla_breach_rate`.

---

### Scenario 6: Health Check

```bash
curl -s http://localhost:8000/healthz | python3 -m json.tool
```

**Expected**: `{"status": "ok", "postgres": "ok", "ollama": "ok"}`

---

## Checking Logs

```bash
# Structured JSON logs — filter by alert_id
kubectl logs -n fraud-agent deploy/fraud-alert-agent --tail=100 \
  | grep '"alert_id":"<your-alert-id>"'

# Investigation node activity
kubectl logs -n fraud-agent deploy/fraud-alert-agent --tail=100 \
  | grep '"node_name":"investigation_node"'

# SLA breach events
kubectl logs -n fraud-agent deploy/fraud-alert-agent --tail=100 \
  | grep '"action":"escalate"'
```

---

## Grafana Dashboard

After deployment, open Grafana (`kubectl port-forward -n monitoring svc/grafana 3000:3000`)
and navigate to the **Fraud Alert Agent** dashboard. Key panels:

- Alert volume by severity (last 24h)
- Investigation latency p50 / p95
- Ollama inference duration
- SLA breach rate
- Open Critical alerts requiring review

---

## Grafana Trace Exploration

1. **Ensure Tempo is running:**
   ```bash
   kubectl get pod -n fraud-agent -l app=tempo
   ```

2. **Port-forward Grafana:**
   ```bash
   kubectl port-forward -n monitoring svc/grafana 3000:3000
   ```

3. **Explore traces:** Navigate to **Explore** → select the **Fraud-Agent-Tempo** datasource →
   enter TraceQL to find a specific investigation:
   ```
   {.investigation.alert_id="<alert-id>"}
   ```
   This shows the full investigation trace with `node.*`, `tool.*`, and `llm.ollama` child spans
   with durations and status codes.

4. **Open the LangGraph traces dashboard:**
   Go to **Dashboards → Fraud Alert Agent — LangGraph Traces** for aggregated panels:
   - Node execution duration p95 (by node name)
   - Tool call duration p95
   - LLM inference latency
   - Node error rate timeseries
   - Total investigations count (24h)

5. **Troubleshoot the tracing pipeline:**
   ```bash
   # Check OTel Collector is receiving spans
   kubectl logs -n fraud-agent deploy/otel-collector | grep -E "(Everything is ready|error)"

   # Check Tempo is ingesting
   kubectl logs -n fraud-agent statefulset/tempo | grep -E "(started|error)"

   # Verify Tempo HTTP API is up (via port-forward)
   kubectl port-forward -n fraud-agent svc/tempo 3200:3200 &
   curl http://localhost:3200/ready
   ```
