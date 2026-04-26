# Implementation Plan: Agentic Fraud Alert Orchestration

**Branch**: `004-fraud-alert-agent` | **Date**: 2026-04-25 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/004-fraud-alert-agent/spec.md`

## Summary

Build a LangGraph multi-agent pipeline that continuously monitors the `transactions_scored`
Iceberg table (written by `fraud-score-enricher`), triggers a multi-step LLM-driven
investigation for every transaction above the fraud threshold, and surfaces actionable
alerts — with human-in-the-loop escalation, audit trail, and an operational dashboard —
via a containerised FastAPI service deployed to the same Minikube cluster.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**:
- `langgraph>=0.2` — multi-agent state machine orchestration
- `langgraph-checkpoint-postgres` — durable graph state checkpointing in Postgres
- `apache-flink` (PyFlink) — stream processing worker that ingests from `transactions_scored`
- `langchain-ollama` — Ollama LLM integration for investigation reasoning
- `fastapi>=0.111` + `uvicorn` — REST API service and web server
- `pyiceberg[pyarrow,s3]==0.7.1` — Iceberg table reads (transaction history lookups)
- `sqlalchemy>=2.0` + `asyncpg` — async Postgres ORM for alert/decision persistence
- `alembic` — database migrations
- `httpx` — async HTTP client for Slack notifications and internal calls
- `pydantic-settings` — environment-based configuration
- `prometheus-client` — metrics endpoint

**Storage**:
- Postgres 15 — primary store for FraudAlert, Investigation, InvestigationStep, DecisionEvent records; also serves as LangGraph checkpoint backend
- Iceberg (read-only via PyIceberg) — source of truth for transaction history used by investigation tools

**Testing**: pytest + pytest-asyncio; contract tests against FastAPI TestClient; integration tests against a local Postgres container

**Target Platform**: Kubernetes (Minikube, namespace `fraud-agent`)  
**Project Type**: Web service + background worker (containerised FastAPI + LangGraph worker)

**Performance Goals**:
- P95 investigation latency ≤ 60 seconds per alert (end-to-end, including Ollama inference)
- Notification delivery for Critical alerts ≤ 2 minutes from investigation completion
- Throughput: 500 alerts/hour sustained without backpressure (≈ 0.14 alerts/second)
- Ollama inference: llama3:8b or mistral:7b, target ≤ 20s per investigation reasoning call on CPU (GPU if available)

**Constraints**:
- Ollama runs as a separate pod in the cluster; LLM calls are async and must not block the FastAPI event loop
- All credentials injected via Kubernetes secrets; no plaintext in manifests or code
- The `transactions_scored` Iceberg table is read-only from this service
- Postgres must tolerate pod restarts — LangGraph checkpoint enables graph resume
- SLA enforcement timer is approximate (±30s accuracy is acceptable)

**Scale/Scope**: ~500 alerts/hour peak; single-replica for v1 with horizontal scale path via stateless FastAPI workers and shared Postgres checkpoint store

## Constitution Check

### I. Security by Default ✓
- All external credentials (Postgres, Slack webhook, MinIO S3, Ollama endpoint) injected via Kubernetes Secrets; referenced in `configmap.yaml` + `deployment.yaml` only
- FastAPI endpoints protected by API-key header (`X-API-Key`) validated against a cluster secret; anonymous access rejected with 401
- Audit trail (DecisionEvent) is append-only — no update/delete routes exposed
- Iceberg access is read-only; no write path to `transactions_scored` or `transactions`
- Ollama endpoint is cluster-internal only (`ollama.ollama.svc.cluster.local`); not exposed externally
- Trust boundary: only the internal alert ingestor worker (runs in same pod) and the FastAPI API key holder can create FraudAlert records

### II. Production-Grade Engineering ✓
- Migrations managed by Alembic; rollback via `alembic downgrade -1`
- LangGraph graph state checkpointed to Postgres — agent resumes cleanly after pod restart
- Idempotency enforced at the database level via unique constraint on `transaction_id` in `fraud_alerts`
- Investigation timeout (5 min) terminates runaway LLM calls and routes alert to human review
- Health check endpoint (`/healthz`) probes Postgres connectivity and Ollama reachability
- Container image built from `python:3.11-slim`; multi-stage build; non-root user

### III. README-Driven Documentation ✓
- `apps/fraud-alert-agent/README.md` — purpose, prerequisites, local dev, env vars, deployment, troubleshooting
- `docs/FRAUD_SCORE_ENRICHER.md` — update to describe handoff to this service
- `README.md` — update stack and architecture sections
- New operational runbook: `docs/runbooks/fraud-alert-agent.md`

### IV. Performance Is a Feature ✓
- Baseline: Ollama llama3:8b on CPU ~15–20s/call (benchmarked against local Minikube); GPU acceleration reduces to ~3–5s
- Alert monitor polls `transactions_scored` every 5s (same interval as Flink's Iceberg streaming source) — maximum alert lag is 5s + investigation time
- Postgres connection pool: 10 connections; sized for single replica + LangGraph checkpointer concurrency
- Prometheus metrics: `fraud_alerts_total`, `investigation_duration_seconds`, `sla_breaches_total`, `ollama_inference_seconds`

### V. Observable and Operable Systems ✓
- Structured JSON logs via `structlog` with fields: `alert_id`, `transaction_id`, `severity`, `step`, `duration_ms`, `outcome`
- `/metrics` endpoint exposes Prometheus counters and histograms (scraped by existing cluster Prometheus)
- `/healthz` returns 200 when Postgres and Ollama are reachable; 503 otherwise (used by liveness + readiness probes)
- Grafana dashboard provisioned: alert volume, investigation latency p50/p95, SLA breach rate, Ollama inference time
- Runbook documents: threshold reconfiguration, investigation replay, Ollama model swap, Postgres failover

## Project Structure

### Documentation (this feature)

```text
specs/004-fraud-alert-agent/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── alerts-api.yaml
│   └── investigation-api.yaml
└── tasks.md             # Phase 2 output (/speckit-tasks — not created by /speckit-plan)
```

### Source Code

Application source code lives under `src/` at the repo root, separate from all
Flux/GitOps YAML. Kubernetes manifests live under `apps/` as they do for other
workloads in this repo. This separates infrastructure-as-code from application code.

```text
src/fraud-alert-agent/               # Application source — no k8s YAML here
├── app/
│   ├── main.py                        # FastAPI app factory + lifespan
│   ├── config.py                      # Pydantic Settings (env-driven)
│   ├── agents/
│   │   ├── graph.py                   # LangGraph StateGraph definition
│   │   ├── state.py                   # AgentState TypedDict
│   │   ├── triage_node.py             # Severity classification node
│   │   ├── investigation_node.py      # Multi-step LLM investigation node
│   │   └── escalation_node.py         # Routing + notification trigger node
│   ├── api/
│   │   ├── deps.py                    # Auth dependency (API key check)
│   │   ├── alerts.py                  # GET /api/v1/alerts, GET /api/v1/alerts/{id}
│   │   ├── decisions.py               # POST /api/v1/alerts/{id}/decisions
│   │   ├── investigations.py          # GET /api/v1/alerts/{id}/investigation
│   │   └── metrics_api.py             # GET /api/v1/metrics (aggregate stats)
│   ├── db/
│   │   ├── base.py                    # SQLAlchemy async engine + session factory
│   │   ├── models.py                  # ORM models (FraudAlert, Investigation, …)
│   │   └── migrations/                # Alembic migrations directory
│   ├── services/
│   │   ├── alert_service.py           # Alert create/read/update + dedup guard
│   │   ├── investigation_service.py   # Launch/retrieve LangGraph investigations
│   │   ├── notification_service.py    # Slack webhook sender
│   │   └── sla_service.py             # SLA deadline computation + breach escalation
│   ├── tools/
│   │   ├── transaction_history_tool.py  # PyIceberg query: last N txns for user
│   │   ├── pattern_lookup_tool.py       # Behavioural baseline comparison
│   │   └── feature_context_tool.py      # Read ML feature values from scored record
│   └── workers/
│       ├── alert_monitor.py             # Polls transactions_scored; creates alerts
│       └── sla_worker.py                # Periodic SLA sweep; emits escalations
├── tests/
│   ├── contract/
│   │   ├── test_alerts_contract.py
│   │   └── test_decisions_contract.py
│   ├── integration/
│   │   ├── test_alert_pipeline.py
│   │   └── test_investigation_graph.py
│   └── unit/
│       ├── test_triage_node.py
│       ├── test_sla_service.py
│       └── test_notification_service.py
├── Dockerfile
├── pyproject.toml
└── README.md

apps/base/fraud-alert-agent/          # Kubernetes manifests only — no source code
├── namespace.yaml
├── deployment.yaml
├── service.yaml
├── configmap.yaml
├── postgres.yaml                      # Postgres StatefulSet (dev/test only)
└── kustomization.yaml

apps/minikube/fraud-alert-agent/      # Minikube-specific Kustomize overlay
└── kustomization.yaml                 # image tag, namespace patch, resource limits
```

**Structure Decision**: `src/` at repo root holds all non-Flux application source code.
`apps/base/` and `apps/minikube/` hold only Kubernetes manifests and Kustomize overlays,
consistent with the rest of the GitOps repo. FastAPI handles REST; LangGraph workers run
as asyncio background tasks within the same process (lifespan context), sharing the
Postgres connection pool. The alert monitor worker is a long-running coroutine started
on app startup.

## Complexity Tracking

No constitution violations. All five gates pass with documented mitigations.
