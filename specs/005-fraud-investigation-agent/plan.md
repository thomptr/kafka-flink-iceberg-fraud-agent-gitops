# Implementation Plan: Fraud Investigation Agent

**Branch**: `005-fraud-investigation-agent` | **Date**: 2026-04-26 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/005-fraud-investigation-agent/spec.md`

## Summary

Extend the existing `fraud-alert-agent` FastAPI/LangGraph service with interactive investigation
session endpoints and a new conversational ReAct LangGraph graph, persist session state (turns,
conclusions) to the shared Postgres database, and deliver a new Streamlit frontend
(`investigation_ui/app.py`) that lets analysts chat with the agent to explore why a transaction
was flagged — then record a binding conclusion that closes the alert.

## Technical Context

**Language/Version**: Python 3.11 (same as `fraud-alert-agent`)

**Primary Dependencies**:
- `langgraph>=0.2` — existing; session graph uses `create_react_agent` with `MessagesState`
- `langgraph-checkpoint-postgres` — existing; each `session_id` becomes a LangGraph `thread_id`
- `langchain-ollama` — existing; Ollama LLM used for session graph reasoning
- `fastapi>=0.111` + `uvicorn` — existing; five new endpoints added to `fraud-alert-agent`
- `sqlalchemy>=2.0` + `asyncpg` — existing; three new ORM models added
- `alembic` — existing; one new migration (`add_investigation_sessions_tables`)
- `streamlit>=1.35` — existing in `dashboard` extras; investigation UI reuses this extras group
- `httpx` — existing; used by investigation UI to call FastAPI
- `prometheus-client` — existing; new session metrics added to `/metrics`

**Storage**:
- Postgres 15 (shared with `fraud-alert-agent`): three new tables
  - `investigation_sessions` — session lifecycle state
  - `session_turns` — Q&A transcript pairs
  - `investigation_conclusions` — analyst verdict per alert (unique per `alert_id`)
- LangGraph checkpoint (`langgraph_checkpoints` table): session graph threads keyed on `session_id`

**Testing**: pytest + pytest-asyncio; contract tests against FastAPI TestClient; integration
tests against a local Postgres container (same `testcontainers` pattern as `fraud-alert-agent`)

**Target Platform**: Kubernetes (Minikube, namespace `fraud-agent`) — same cluster as
`fraud-alert-agent`; investigation UI deployed as a separate `Deployment` + `Service`

**Project Type**: Extension to existing web service + new Streamlit UI container

**Performance Goals**:
- Session open + initial explanation: P95 ≤ 30 seconds (dominated by first Ollama inference call)
  - Baseline (llama3.1:8b on CPU, no GPU): ~15–25s per LLM call; ≤ 30s with single tool call
  - Measured via `investigation_session_turn_duration_seconds` histogram p95 in Prometheus
- Follow-up turn response: P90 ≤ 15 seconds
  - Same LLM baseline; subsequent calls use LangGraph thread context (no full re-summarisation)
- Investigation UI page load: ≤ 2 seconds (Streamlit render + single GET /turns call)
- Session inactivity timeout: 60 minutes (configurable via `SESSION_TIMEOUT_MINUTES`)

**Constraints**:
- Investigation UI communicates with the FastAPI service only via REST (`X-API-Key` auth)
- No new LLM providers; reuses existing Ollama endpoint (`ollama.ollama.svc.cluster.local`)
- Session graph reuses existing tools: `transaction_history_tool`, `pattern_lookup_tool`,
  `feature_context_tool` — wrapped with PII masking before LLM ingestion
- The investigation UI is advisory only; no direct DB access from Streamlit
- v1 uses synchronous (non-streaming) turn responses

**Scale/Scope**: ~10 concurrent investigation sessions under normal analyst load; the same
Postgres connection pool (10 connections) sized for `fraud-alert-agent` is sufficient

## Constitution Check

### I. Security by Default ✓
- All new endpoints inherit the existing `verify_api_key` FastAPI dependency — no unauthenticated
  access
- `X-Analyst-Id` header carries analyst identity for session ownership and conclusion authorship;
  the API does not expose other analysts' in-progress session transcripts without elevated scope
- PII masking applied at the tool output boundary before any value reaches the LLM or is stored
  in `session_turns`; card numbers masked to last 4 digits, SSNs and email addresses redacted
- Investigation UI credentials (`FRAUD_API_KEY`) injected via Kubernetes Secret; never hardcoded
  or logged
- `InvestigationConclusion.alert_id` unique constraint + Postgres row-level lock on conclude
  endpoint prevents silent concurrent overwrite; returns `HTTP 409` with prior conclusion details
- Session transcripts retained for 7 years (inherits the existing Postgres retention policy from
  the `fraud-alert-agent` deployment)

### II. Production-Grade Engineering ✓
- Single Alembic migration (`add_investigation_sessions_tables`) covers all three new tables;
  `alembic downgrade -1` rolls them back cleanly
- LangGraph session graph threads are durable via the existing Postgres checkpointer — pod restart
  does not lose in-flight session state
- `sla_worker.py` extended (not replaced) to sweep and abandon inactive sessions; no new
  background task introduced
- Investigation UI is a stateless Streamlit process; all state lives in the backend; UI restarts
  are safe
- New endpoints follow the same FastAPI router + dependency injection pattern as existing
  `alerts.py`, `decisions.py`, `investigations.py`

### III. README-Driven Documentation ✓
- `src/fraud-alert-agent/README.md` updated: new "Investigation UI" section covering purpose,
  local dev steps, env vars, and Kubernetes deployment
- `docs/runbooks/fraud-alert-agent.md` updated: investigation session lifecycle, how to replay
  a session, how to resolve a concurrent-conclusion conflict
- `README.md` (repo root) updated: investigation UI added to the architecture overview
- `specs/005-fraud-investigation-agent/quickstart.md` created (this feature's operational guide)

### IV. Performance Is a Feature ✓
- Initial explanation budget: 1 Ollama inference call; same llama3:8b baseline (~15–20s on CPU)
  as existing alert investigations — within the 30s spec target
- Follow-up turns: 1 Ollama inference call each; same baseline — within the 15s spec target
- New Prometheus metrics:
  - `investigation_session_opens_total` (counter)
  - `investigation_session_turn_duration_seconds` (histogram, p50/p95)
  - `investigation_conclusions_total` by outcome label
- Grafana dashboard updated with session panel: open sessions, turn latency p95, conclusion rate

### V. Observable and Operable Systems ✓
- Structured logs (via existing `structlog`) on all new endpoints: `session_id`, `analyst_id`,
  `alert_id`, `turn_number`, `duration_ms`, `tool_calls`
- Investigation UI logs API errors to `structlog` in the backend; Streamlit surfaces friendly
  error banners to the analyst
- `/healthz` endpoint unchanged — already covers Postgres and Ollama reachability; session
  functionality depends on both
- Runbook documents: opening a session, resolving a 409 conflict, re-running a session after
  abandonment, interpreting PII-masked values

## Project Structure

### Documentation (this feature)

```text
specs/005-fraud-investigation-agent/
├── plan.md                        # This file
├── research.md                    # Phase 0 output
├── data-model.md                  # Phase 1 output
├── quickstart.md                  # Phase 1 output
├── contracts/
│   └── investigation-sessions-api.yaml  # Phase 1 output
└── tasks.md                       # Phase 2 output (/speckit-tasks — not created by /speckit-plan)
```

### Source Code

This feature extends the existing `src/fraud-alert-agent/` project. No new top-level `src/`
directory is created. The investigation UI is a new Streamlit app within the same project,
deployed as a separate container. Kubernetes manifests follow the existing `apps/base/` pattern.

```text
src/fraud-alert-agent/
├── app/
│   ├── agents/
│   │   ├── investigation_session_graph.py   # NEW — ReAct session graph (create_react_agent)
│   │   └── investigation_session_state.py   # NEW — session AgentState / MessagesState typedef
│   ├── api/
│   │   └── sessions.py                      # NEW — 5 new investigation session endpoints
│   ├── db/
│   │   ├── models.py                        # UPDATED — 3 new ORM models added
│   │   └── migrations/versions/
│   │       └── XXXX_add_investigation_sessions_tables.py  # NEW Alembic migration
│   ├── services/
│   │   └── session_service.py               # NEW — session CRUD, turn management, conclude logic
│   ├── tools/
│   │   └── pii_masking.py                   # NEW — mask_pii() utility; applied in tool wrappers
│   ├── workers/
│   │   └── sla_worker.py                    # UPDATED — adds session timeout sweep
│   ├── main.py                              # UPDATED — register sessions router
│   └── metrics.py                           # UPDATED — 3 new Prometheus metrics
├── investigation_ui/
│   ├── __init__.py                          # NEW
│   └── app.py                               # NEW — Streamlit investigation chat UI
├── tests/
│   ├── contract/
│   │   └── test_sessions_contract.py        # NEW — contract tests for session endpoints
│   ├── integration/
│   │   └── test_investigation_session.py    # NEW — full session lifecycle integration test
│   └── unit/
│       ├── test_session_service.py          # NEW — session CRUD unit tests
│       └── test_pii_masking.py              # NEW — PII masking unit tests
└── pyproject.toml                           # UPDATED — add investigation_ui to packages.find

apps/base/fraud-investigation-ui/            # NEW — k8s manifests for the Streamlit UI
├── deployment.yaml
├── service.yaml
├── configmap.yaml
└── kustomization.yaml

apps/minikube/fraud-investigation-ui/        # NEW — Minikube overlay
└── kustomization.yaml
```

**Structure Decision**: The investigation UI lives inside `src/fraud-alert-agent/` as a new
`investigation_ui/` package, sharing `pyproject.toml`, the existing `dashboard` optional extras
(Streamlit + httpx), and the same Docker build context. It is deployed as a separate container
(separate Deployment + Service) so restarts are independent. This avoids creating a second top-
level `src/` project for what is effectively a thin REST client UI.

## Complexity Tracking

No constitution violations. All five gates pass with documented mitigations.
