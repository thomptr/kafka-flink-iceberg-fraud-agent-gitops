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

The alert monitor worker starts automatically on app lifespan startup and polls
`transactions_scored` every 5 seconds.

---

## Deploying to Minikube

```bash
# Build and load the container image
docker build -t fraud-alert-agent:0.1.0 src/fraud-alert-agent/
minikube image load fraud-alert-agent:0.1.0 -p fraud-gitops

# Create the namespace and required secrets
kubectl apply -f apps/base/fraud-alert-agent/namespace.yaml

kubectl create secret generic fraud-agent-secrets -n fraud-agent \
  --from-literal=database-url="postgresql+asyncpg://fraud:fraud@postgres.fraud-agent.svc.cluster.local:5432/fraud_agent" \
  --from-literal=api-key="$(openssl rand -hex 32)" \
  --from-literal=slack-webhook-url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

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

Inject a synthetic high-probability scored transaction directly into the `transactions_scored`
Iceberg table and verify the agent produces a completed investigation.

```bash
# Port-forward the service
kubectl port-forward -n fraud-agent svc/fraud-alert-agent 8000:8000 &

API_KEY=$(kubectl get secret fraud-agent-secrets -n fraud-agent -o jsonpath='{.data.api-key}' | base64 -d)

# Poll for new alerts — should appear within 10 seconds of the Iceberg snapshot
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts?severity=critical&status=open" | python3 -m json.tool

# Wait ~60 seconds for investigation, then check it completed
ALERT_ID="<id from above>"
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigation" | python3 -m json.tool
```

**Expected**: investigation.status = `completed`; evidence array has ≥3 items; recommended_action is set.

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
