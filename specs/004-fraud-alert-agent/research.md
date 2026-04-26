# Research: Agentic Fraud Alert Orchestration

**Branch**: `004-fraud-alert-agent` | **Date**: 2026-04-25

## Decision Log

---

### D-001: Multi-Agent Orchestration — LangGraph

**Decision**: Use LangGraph (`langgraph>=0.2`) as the agent graph framework.

**Rationale**: LangGraph models the investigation pipeline as a directed state graph with explicit nodes (triage, investigation, escalation) and conditional edges. State is a typed Python dataclass, making it inspectable and testable. Postgres checkpointing via `langgraph-checkpoint-postgres` enables graph resume after pod restart and enforces idempotency by keying checkpoint state on `thread_id = transaction_id`.

**Alternatives considered**:
- LangChain AgentExecutor: single-agent loop, no first-class multi-step graph model, no built-in checkpoint store
- CrewAI: higher-level abstraction but less control over step ordering and tool invocation; checkpoint support is immature
- Raw asyncio task chain: no state persistence, no resume semantics, reinvents what LangGraph provides

---

### D-002: Streaming Ingestion — PyIceberg Polling Worker

**Decision**: The alert monitor worker polls `transactions_scored` via PyIceberg every 5 seconds, tracking the last-processed Iceberg snapshot ID in Postgres to ensure exactly-once alert creation.

**Rationale**: The `transactions_scored` Iceberg table is already written by the `fraud-score-enricher` Flink job. Rather than adding a second Flink job purely for threshold filtering, a lightweight Python coroutine within the FastAPI process reads new Iceberg snapshots using PyIceberg's incremental scan API. The `apache-flink` PyFlink dependency is retained in `pyproject.toml` for future migration to a Flink-native Python consumer if throughput requirements exceed what polling can sustain.

**Alternatives considered**:
- Dedicated PyFlink streaming job: higher operational overhead (separate FlinkDeployment); justified only at >10k alerts/hour
- Kafka topic between Flink and agent: adds a broker dependency; the Iceberg table is the source of truth and polling is simpler for v1 throughput targets
- Flink Table API Python UDF: tight coupling between scoring and alerting pipelines; harder to deploy independently

---

### D-003: LLM Backend — Ollama (local)

**Decision**: Use Ollama running in the cluster (`ollama.ollama.svc.cluster.local:11434`) with `llama3:8b` as the default model for investigation reasoning. LangChain's `langchain-ollama` integration is used for tool-calling and structured output.

**Rationale**: Fraud investigation data is sensitive; routing it through an external API (OpenAI, Anthropic) creates a data-residency concern. Ollama runs on the same Minikube node, keeping all inference local. `llama3:8b` fits in ≤8GB VRAM (or runs on CPU in ~15–20s/call). The model is swappable via the `OLLAMA_MODEL` environment variable.

**Alternatives considered**:
- OpenAI GPT-4o: best reasoning quality but data leaves the cluster and incurs per-token cost; not acceptable for v1 sensitive data constraint
- Anthropic Claude API: same data-residency concern
- llama3:70b: better accuracy but requires >40GB VRAM; not available in local Minikube; future upgrade path

---

### D-004: Postgres Checkpointing for LangGraph

**Decision**: Use `langgraph-checkpoint-postgres` with an async asyncpg connection pool. The checkpoint key is `thread_id = alert_id` (UUID). The same Postgres instance also stores FraudAlert, Investigation, and DecisionEvent tables.

**Rationale**: Collocating application data and LangGraph checkpoint state in a single Postgres instance reduces operational overhead. Alembic manages all schema migrations. LangGraph's checkpoint semantics guarantee that if the investigation worker crashes mid-graph, the next alert monitor cycle resumes from the last completed node rather than re-running from scratch.

**Alternatives considered**:
- Redis checkpoint backend: fast but no persistent durability; state lost on Redis restart without AOF
- SQLite: not suitable for multi-process/multi-replica access
- In-memory: no persistence; defeats the purpose of checkpointing

---

### D-005: Notification Channel — Slack Webhook (v1)

**Decision**: Critical alert notifications are sent via an incoming Slack webhook URL stored as a Kubernetes secret. The `notification_service` sends a structured message with alert summary and a deep link to the review endpoint.

**Rationale**: Slack is the lowest-friction channel for fraud ops teams. Incoming webhooks require no OAuth flow and no Slack App installation, which keeps setup simple for a local Minikube deployment. The `NotificationService` interface abstracts the channel so email or PagerDuty can be added later without changing the escalation node.

**Alternatives considered**:
- PagerDuty: appropriate for on-call workflows but overkill for v1; Slack covers the review use case
- Email (SMTP): slower, no interactive approval link; reasonable for audit copies in future

---

### D-006: API Authentication — API Key (v1)

**Decision**: FastAPI routes are protected by an `X-API-Key` header validated against a secret injected via Kubernetes Secret. Unauthenticated requests return 401.

**Rationale**: The service is cluster-internal in v1; mTLS or OAuth2/OIDC are the correct long-term controls but are out of scope for this iteration. API key provides a meaningful auth boundary against accidental or misconfigured access. The key is rotatable by updating the Kubernetes Secret and rolling the pod.

**Alternatives considered**:
- No auth: violates constitution Security by Default principle
- OAuth2/OIDC: correct for production but requires an identity provider integration not yet present in the cluster

---

### D-007: SLA Enforcement — Periodic Background Sweep

**Decision**: A background coroutine (`sla_worker`) runs every 60 seconds, queries Postgres for Open/In Review alerts past their SLA deadline, and escalates them by creating a `DecisionEvent(actor="sla_bot", action="escalate")` and sending a supervisor notification.

**Rationale**: A database sweep is simple, transparent, and tolerates pod restarts (each sweep re-evaluates all open alerts). Accuracy is ±60s, which is acceptable given the 30-minute SLA window. This avoids per-alert timers (e.g., asyncio `sleep`) that are lost on restart.

**Alternatives considered**:
- Per-alert `asyncio.create_task` with sleep: lost on restart; not durable
- Kubernetes CronJob: external to the app; requires additional RBAC and coupling
- Celery beat: adds a Redis/broker dependency and operational complexity

---

### D-008: Alert Dashboard — FastAPI REST + Future Frontend

**Decision**: v1 exposes REST endpoints for alert listing, filtering, and investigation trace retrieval. No browser UI is included in v1. A future iteration adds a React/Next.js frontend or Grafana plugin consuming these endpoints.

**Rationale**: The spec defines a dashboard as P4 priority. Delivering the REST API first unblocks analyst tooling (curl, Postman, notebook) immediately, and any future frontend has a stable contract to build against. Grafana has table and detail panels that can render the API data without a dedicated UI.

**Alternatives considered**:
- Streamlit app: fast to build but not production-grade; layout is limited
- Grafana plugin: good for metrics view but not interactive approval/override workflow
- Full React SPA in v1: out of scope given P4 priority and investigation-first focus
