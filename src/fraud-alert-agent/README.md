# Fraud Alert Agent

LangGraph multi-agent service that continuously investigates fraud alerts via a 7-node graph,
surfaces actionable decisions with a 6-step audit trail, and ships traces to Grafana Tempo.

## Architecture

See [`docs/architecture.md`](../../docs/architecture.md) for full end-to-end diagrams.

### 7-Node LangGraph Graph

```
START → supervisor_node
  CRITICAL/STANDARD → triage_node → data_query_node → analysis_node
                                   → recommendation_node → escalation_node → report_node → END
  MONITOR_ONLY      → triage_node → escalation_node → report_node → END
  FALSE_POSITIVE    → escalation_node → report_node → END
```

| Node | LLM? | Iceberg? | MLflow? | Kafka? | Responsibility |
|------|------|----------|---------|--------|----------------|
| `supervisor_node` | No | No | No | No | Deterministic routing on fraud_probability |
| `triage_node` | No | No | No | No | Severity + SLA deadline |
| `data_query_node` | No | Read | No | No | Parallel evidence fetch (asyncio.gather) |
| `analysis_node` | Yes (LLaMA 3.1:8b) | No | Yes | No | LLM reasoning with MLflow provenance |
| `recommendation_node` | No | No | No | No | Rule-based: block/notify/escalate |
| `escalation_node` | No | No | No | Yes (fraud-alert-events) | Execute final_action + Slack |
| `report_node` | No | Write | No | Yes (fraud-notifications) | Persist report + Kafka event |

### Recommendation Node Decision Rules

| Rule | Condition | final_action | rule_matched |
|------|-----------|-------------|--------------|
| Block threshold | recommended_action=block AND confidence ≥ 0.85 AND severity in (critical, high) | block | block_threshold |
| Escalate critical | severity=critical OR confidence ≥ 0.90 OR error set | escalate | escalate_critical |
| Default | All other cases | notify | notify_default |

### 7 Registered LangChain Tools

| Tool | Purpose |
|------|---------|
| `query_iceberg_table` | Ad-hoc Iceberg table scan via Polaris REST catalog |
| `list_iceberg_tables` | List tables in a namespace |
| `get_latest_model_version` | MLflow model registry lookup |
| `get_run_details` | MLflow run metrics/params |
| `publish_kafka_event` | Publish structured event to Kafka topic |
| `list_kafka_topics` | List available Kafka topics |
| `read_recent_kafka_messages` | Read recent messages from a topic (inspection) |

### Kafka Topics

| Topic | Direction | Producer | Consumer |
|-------|-----------|----------|----------|
| `scored-transactions` | In | Flink fraud-score-kafka-publisher | `alert_monitor` |
| `fraud-alert-events` | Out | `escalation_node` | Downstream systems |
| `fraud-notifications` | Out | `report_node` | Downstream systems |

## End-to-End Demo

Assumes Minikube is running with port-forwards active:

```bash
kubectl port-forward svc/fraud-alert-agent -n fraud-agent 8000:8000 &
kubectl port-forward svc/synthetic-transaction-producer -n kafka 8080:8080 &
```

**Step 1 — Inject a high-probability scored transaction:**
```bash
curl -X POST http://localhost:8080/inject/scored \
  -H "Content-Type: application/json" \
  -d '{"user_id": 99999, "amount": 8500.00, "fraud_probability": 0.95, "merchant": "Test Fraud Merchant", "distance_from_home_km": 450.0}'
```

**Step 2 — Poll for the alert (within ~5s):**
```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts?severity=critical&status=open"
```

**Step 3 — Watch investigation complete (~60s):**
```bash
curl -H "X-API-Key: $API_KEY" \
  "http://localhost:8000/api/v1/alerts/{ALERT_ID}/investigation"
```

**Step 4 — Approve or override:**
```bash
curl -X POST -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/alerts/{ALERT_ID}/decisions" \
  -d '{"actor": "demo@example.com", "action": "approve", "outcome": "block"}'
```

**Step 5 — View trace logs:**
```bash
kubectl logs -n fraud-agent deploy/fraud-alert-agent | grep node_end
```

## LangGraph Trace Logging

`FraudGraphTraceCallback` instruments every node, tool call, and LLM invocation:

| Callback | Trigger | Log event | Level |
|----------|---------|-----------|-------|
| `on_chain_start` | Node starts | `node_start` | DEBUG |
| `on_chain_end` | Node completes | `node_end` (+ duration_ms) | INFO |
| `on_tool_start` | Tool called | `tool_start` | DEBUG |
| `on_tool_end` | Tool returns | `tool_end` (+ output_length) | INFO |
| `on_llm_start` | Ollama called | `llm_start` | DEBUG |
| `on_llm_end` | Ollama responds | `llm_end` (+ token counts) | INFO |

Enable LangSmith remote tracing:
```bash
kubectl create secret generic fraud-agent-secrets --from-literal=langchain-api-key=<your-langsmith-api-key>
# Set LANGCHAIN_TRACING_V2=true in configmap.yaml
```

## Distributed Tracing (OTEL + Tempo)

Every investigation emits a root span `investigation` (alert_id attribute) with child spans for each node (`node.<name>`), tool (`tool.<name>`), and LLM call (`llm.ollama`). Spans flow:

```
fraud-alert-agent → OTel Collector (4317 gRPC) → Grafana Tempo (3200 HTTP) → Grafana
```

Explore traces:
```bash
kubectl port-forward -n fraud-agent svc/tempo 3200:3200
curl "http://localhost:3200/api/search?service.name=fraud-alert-agent"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Postgres async URL (secret) |
| `OLLAMA_BASE_URL` | `http://ollama.ollama.svc.cluster.local:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model name |
| `FRAUD_API_KEY` | — | API key for REST endpoints (secret) |
| `FRAUD_THRESHOLD_CRITICAL` | `0.85` | Critical severity threshold |
| `OTEL_TRACES_ENABLED` | `true` | Enable OTLP span export |
| `LANGCHAIN_TRACING_V2` | `false` | Enable LangSmith remote tracing |

See `configmap.yaml` for the full list.

## Local Development

```bash
cd src/fraud-alert-agent
docker compose up -d postgres        # or use a local Postgres
pip install -e ".[dev]"
DATABASE_URL=postgresql+asyncpg://... alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Deploy to Minikube

```bash
eval $(minikube docker-env)
docker build -t fraud-alert-agent:0.1.0 src/fraud-alert-agent/
kubectl apply -k apps/minikube/fraud-alert-agent/
```
