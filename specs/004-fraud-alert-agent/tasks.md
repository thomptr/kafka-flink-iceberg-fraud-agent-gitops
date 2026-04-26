# Tasks: Agentic Fraud Alert Orchestration

**Input**: Design documents from `/specs/004-fraud-alert-agent/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/alerts-api.yaml ✓, quickstart.md ✓

**Tests**: Automated tests are included for all security-sensitive, regression-risk, and integration-critical paths per the constitution.

**User input refinement**: US4 dashboard is implemented as a **Streamlit app** (live alerts table + investigation trace/chat panel), per the explicit user request, superseding the REST-only v1 plan in research D-008.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to ([US1]–[US4])

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, directory scaffolding, and tooling

- [X] T001 Create full project directory structure per plan.md under `src/fraud-alert-agent/` and `apps/base/fraud-alert-agent/`
- [X] T002 Write `src/fraud-alert-agent/pyproject.toml` with all runtime and dev dependencies (langgraph, langchain-ollama, fastapi, uvicorn, pyiceberg, sqlalchemy, asyncpg, alembic, httpx, pydantic-settings, prometheus-client, structlog, streamlit, pytest, pytest-asyncio)
- [X] T003 [P] Write multi-stage `src/fraud-alert-agent/Dockerfile` (python:3.11-slim base, non-root user, no dev deps in final stage)
- [X] T004 [P] Write `src/fraud-alert-agent/docker-compose.yml` for local dev (Postgres 15 service + Streamlit dashboard service)
- [X] T005 [P] Identify all README and operational docs that this feature must update (README.md, docs/FRAUD_SCORE_ENRICHER.md, docs/runbooks/fraud-alert-agent.md, src/fraud-alert-agent/README.md)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Implement `src/fraud-alert-agent/app/config.py` — pydantic-settings `Settings` class loading DATABASE_URL, OLLAMA_BASE_URL, OLLAMA_MODEL, FRAUD_API_KEY, SLACK_WEBHOOK_URL, FRAUD_THRESHOLD_CRITICAL (0.85), FRAUD_THRESHOLD_HIGH (0.70), FRAUD_THRESHOLD_MEDIUM (0.50), ICEBERG_CATALOG_URI, MINIO_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY from environment
- [X] T007 [P] Implement `src/fraud-alert-agent/app/db/base.py` — SQLAlchemy async engine + `AsyncSession` factory using asyncpg; pool size 10; export `get_session` dependency
- [X] T008 [P] Implement `src/fraud-alert-agent/app/api/deps.py` — `verify_api_key` FastAPI dependency that reads `X-API-Key` header and raises HTTP 401 if it does not match `settings.FRAUD_API_KEY`
- [X] T009 Implement all ORM models in `src/fraud-alert-agent/app/db/models.py` — `FraudAlert`, `Investigation`, `InvestigationStep`, `DecisionEvent`, `AlertMonitorCursor` with exact column types, constraints, and indexes from data-model.md (UUID PKs, UNIQUE on transaction_id, JSONB evidence, TIMESTAMPTZ columns, append-only DecisionEvent)
- [X] T010 Configure Alembic in `src/fraud-alert-agent/app/db/migrations/` — `alembic.ini`, `env.py` (async), and generate the initial migration creating all five tables and indexes
- [X] T011 Implement `src/fraud-alert-agent/app/main.py` — FastAPI app factory with `@asynccontextmanager` lifespan that starts `alert_monitor` and `sla_worker` coroutines on startup and cancels them on shutdown; mount all routers; configure structlog JSON logging; register `/healthz` and `/metrics` routes
- [X] T012 [P] Add structlog JSON logging configuration to `src/fraud-alert-agent/app/main.py` — fields: `alert_id`, `transaction_id`, `severity`, `step`, `duration_ms`, `outcome`; output to stdout
- [X] T013 [P] Implement `/healthz` endpoint inline in `src/fraud-alert-agent/app/main.py` — probe Postgres connectivity and Ollama reachability; return `HealthResponse` 200 when both OK, 503 otherwise (per contract schema)
- [X] T014 Write Kubernetes manifests in `apps/base/fraud-alert-agent/`: `namespace.yaml` (namespace: fraud-agent), `configmap.yaml` (non-secret env vars), `deployment.yaml` (single replica, liveness + readiness probes on /healthz, env from secret + configmap), `service.yaml` (ClusterIP port 8000), `postgres.yaml` (StatefulSet for dev/test), `kustomization.yaml`
- [X] T015 [P] Write `apps/minikube/fraud-alert-agent/kustomization.yaml` — Minikube overlay referencing base, image tag patch (fraud-alert-agent:0.1.0), resource limit patches

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 — Automated Alert Triage and Investigation (Priority: P1) 🎯 MVP

**Goal**: Alert monitor polls `transactions_scored`, creates FraudAlert records, and the LangGraph agent produces a structured investigation (severity, summary, evidence ≥3 items, recommended action) within 60 seconds.

**Independent Test**: Inject a synthetic scored transaction with `fraud_probability >= 0.85` into `transactions_scored`; verify that within 60 seconds `GET /api/v1/alerts/{id}/investigation` returns `status=completed` with `evidence` array length ≥ 3 and `recommended_action` set.

### Validation for User Story 1 ⚠️

- [X] T016 [P] [US1] Write contract test for `GET /api/v1/alerts` and `GET /api/v1/alerts/{id}` in `src/fraud-alert-agent/tests/contract/test_alerts_contract.py` — use FastAPI TestClient; assert response schemas match alerts-api.yaml (pagination fields, FraudAlert fields, 401 on missing key)
- [X] T017 [P] [US1] Write integration test for end-to-end alert pipeline in `src/fraud-alert-agent/tests/integration/test_alert_pipeline.py` — inject a mock Iceberg snapshot, assert FraudAlert is created with correct severity, assert investigation reaches `completed` status with evidence
- [X] T018 [US1] Validate API-key enforcement (401 without header), Iceberg read-only access (no write path), and Ollama endpoint is cluster-internal only (assert OLLAMA_BASE_URL not exposed in any response body)

### Implementation for User Story 1

- [X] T019 [P] [US1] Implement `src/fraud-alert-agent/app/agents/state.py` — `AgentState` TypedDict with fields: `alert_id`, `transaction_id`, `user_id`, `amount`, `merchant`, `fraud_probability`, `severity`, `evidence`, `reasoning`, `recommended_action`, `confidence`, `error`, `steps`
- [X] T020 [P] [US1] Implement `src/fraud-alert-agent/app/tools/transaction_history_tool.py` — PyIceberg async query returning last N transactions for a `user_id` from the `transactions` Iceberg table; handle table unavailable by returning empty list and setting error field
- [X] T021 [P] [US1] Implement `src/fraud-alert-agent/app/tools/pattern_lookup_tool.py` — compares current transaction merchant/location/amount against user's 30-day behavioural baseline from Iceberg; returns deviation score and description
- [X] T022 [P] [US1] Implement `src/fraud-alert-agent/app/tools/feature_context_tool.py` — reads ML feature values from the scored `transactions_scored` record for the given `transaction_id` and returns them as a dict
- [X] T023 [US1] Implement `src/fraud-alert-agent/app/agents/triage_node.py` — classifies severity from `fraud_probability` using configurable thresholds (Critical ≥0.85, High ≥0.70, Medium ≥0.50); sets `state.severity` and `state.sla_deadline`; logs `alert_id`, `severity`
- [X] T024 [US1] Implement `src/fraud-alert-agent/app/agents/investigation_node.py` — Ollama LLM node using `langchain-ollama` with tool binding; calls transaction_history_tool, pattern_lookup_tool, feature_context_tool; synthesises ranked `evidence` list (≥3 items when available) and `recommended_action`; persists each tool call as an `InvestigationStep`; handles tool timeout gracefully (returns partial evidence + sets error)
- [X] T025 [US1] Implement `src/fraud-alert-agent/app/agents/escalation_node.py` — routing node that reads `state.severity`, sends Slack notification for Critical alerts via `notification_service`, sets final `state.recommended_action`; also handles `error` path by routing to human review
- [X] T026 [US1] Assemble `src/fraud-alert-agent/app/agents/graph.py` — LangGraph `StateGraph` with nodes: triage → investigation → escalation → END; conditional edge from investigation to escalation or timeout; Postgres checkpointer via `langgraph-checkpoint-postgres` using `thread_id = str(alert_id)`
- [X] T027 [US1] Implement `src/fraud-alert-agent/app/services/alert_service.py` — async methods: `create_alert` (idempotency via UNIQUE on transaction_id, returns existing on conflict), `get_alert`, `list_alerts` (filter by severity, status, from_time, to_time, paginated), `update_alert_status`
- [X] T028 [US1] Implement `src/fraud-alert-agent/app/services/investigation_service.py` — `launch_investigation(alert_id)` starts the LangGraph graph as an asyncio background task; `get_investigation(alert_id)` reads Investigation + InvestigationSteps from DB
- [X] T029 [US1] Implement `src/fraud-alert-agent/app/workers/alert_monitor.py` — `async def run_alert_monitor()` infinite loop: reads `AlertMonitorCursor.last_snapshot_id` from DB, calls PyIceberg incremental scan on `transactions_scored` for new snapshots, filters records above `FRAUD_THRESHOLD_MEDIUM`, calls `alert_service.create_alert` then `investigation_service.launch_investigation`, updates cursor; 5-second poll interval; handles Iceberg unavailability with logged warning and retry backoff
- [X] T030 [US1] Implement `GET /api/v1/alerts` and `GET /api/v1/alerts/{id}` routes in `src/fraud-alert-agent/app/api/alerts.py` — use `alert_service.list_alerts` and `alert_service.get_alert`; require `verify_api_key` dependency; return `AlertListResponse` and `FraudAlert` schemas per contract
- [X] T031 [US1] Implement `GET /api/v1/alerts/{alert_id}/investigation` route in `src/fraud-alert-agent/app/api/investigations.py` — use `investigation_service.get_investigation`; return `Investigation` schema with nested `steps` array per contract; 404 if not found

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 — Multi-Step Investigation Reasoning (Priority: P2)

**Goal**: Every investigation records a complete ordered audit trail (InvestigationStep per tool call), idempotency prevents duplicate alerts/investigations, and investigations exceeding 5 minutes time out gracefully.

**Independent Test**: Replay a labelled transaction; verify that `GET /api/v1/alerts/{id}/investigation` returns `steps` array with one entry per tool call, ordered by `step_order`; submit the same transaction_id twice and verify alert count does not increase; let an investigation run >5 minutes (mock Ollama slow) and verify `investigation.status = timed_out` and alert is routed to human review.

### Validation for User Story 2 ⚠️

- [X] T032 [P] [US2] Write integration test for investigation graph in `src/fraud-alert-agent/tests/integration/test_investigation_graph.py` — assert step ordering, idempotency (duplicate transaction_id), and timeout routing
- [X] T033 [P] [US2] Write unit test for investigation timeout path in `src/fraud-alert-agent/tests/unit/test_investigation_timeout.py` — mock Ollama with a long-running response; assert `timed_out` status and DecisionEvent(actor="agent", action="escalate") created

### Implementation for User Story 2

- [X] T034 [P] [US2] Extend `src/fraud-alert-agent/app/agents/investigation_node.py` to persist each tool invocation as an `InvestigationStep` row (step_order, node_name, tool_name, input, output, duration_ms) inside the async DB session before moving to the next tool
- [X] T035 [P] [US2] Add 5-minute investigation timeout to `src/fraud-alert-agent/app/agents/graph.py` — wrap graph invocation with `asyncio.wait_for(timeout=300)`; on `TimeoutError` set `investigation.status = timed_out`, create `DecisionEvent(actor="agent", action="escalate")`, send supervisor notification
- [X] T036 [US2] Harden idempotency in `src/fraud-alert-agent/app/services/alert_service.py` and `investigation_service.py` — catch `UniqueViolation` from asyncpg on `transaction_id` insert, return existing record; guard `launch_investigation` to no-op if investigation already exists for alert_id

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 — Human-in-the-Loop Escalation and Feedback (Priority: P3)

**Goal**: Critical alerts trigger a Slack notification within 2 minutes of investigation completion; analysts can approve or override via `POST /api/v1/alerts/{id}/decisions`; the SLA worker auto-escalates unreviewed Critical alerts after 30 minutes.

**Independent Test**: Create a Critical alert record (skip investigation), verify Slack webhook receives a notification within 2 minutes; POST an approve and an override decision, confirm both are persisted with actor + timestamp; mark an alert's `sla_deadline` as past, run the SLA sweep, verify `status=sla_breached` and a new escalation DecisionEvent exists.

### Validation for User Story 3 ⚠️

- [X] T037 [P] [US3] Write contract test for `POST /api/v1/alerts/{id}/decisions` in `src/fraud-alert-agent/tests/contract/test_decisions_contract.py` — test approve, override (with and without reason), 400 on override without reason, 400 on decision for resolved alert, 401 on missing key
- [X] T038 [P] [US3] Write unit test for `notification_service` in `src/fraud-alert-agent/tests/unit/test_notification_service.py` — mock `httpx.AsyncClient.post`; assert Slack payload includes transaction summary and alert link; assert unreachable webhook raises logged warning without crashing
- [X] T039 [P] [US3] Write unit test for `sla_service` in `src/fraud-alert-agent/tests/unit/test_sla_service.py` — assert SLA deadline offsets per severity (Critical: 30 min, High: 2 hr, Medium: 8 hr); assert breach detection query returns only past-deadline open/in_review alerts
- [X] T040 [US3] Write integration test for human decision flow in `src/fraud-alert-agent/tests/integration/test_human_decision.py` — POST approve → assert status=resolved + DecisionEvent; POST override with reason → assert reason persisted; attempt second decision on resolved alert → assert 400
- [X] T041 [US3] Validate audit trail immutability: assert no UPDATE or DELETE SQL routes exist on `decision_events` table; assert `created_at` is set server-side and not overridable by request body

### Implementation for User Story 3

- [X] T042 [P] [US3] Implement `src/fraud-alert-agent/app/services/notification_service.py` — `async def send_alert_notification(alert: FraudAlert)` posts structured Slack message via `httpx.AsyncClient` to `SLACK_WEBHOOK_URL`; handles empty/missing URL as no-op (dev mode); handles HTTP errors with structlog warning and no re-raise
- [X] T043 [P] [US3] Implement `src/fraud-alert-agent/app/services/sla_service.py` — `compute_sla_deadline(severity, created_at)` returns `created_at + offset`; `get_breached_alerts(session)` queries FraudAlert where `sla_deadline < now()` and `status IN ('open', 'in_review')`
- [X] T044 [US3] Implement `src/fraud-alert-agent/app/workers/sla_worker.py` — `async def run_sla_worker()` infinite loop every 60 seconds: calls `sla_service.get_breached_alerts`, for each creates `DecisionEvent(actor="sla_bot", action="escalate")`, updates alert `status=sla_breached`, sends supervisor notification via `notification_service`
- [X] T045 [US3] Implement `POST /api/v1/alerts/{alert_id}/decisions` and `GET /api/v1/alerts/{alert_id}/decisions` routes in `src/fraud-alert-agent/app/api/decisions.py` — POST validates `DecisionRequest` (requires `reason` for override, requires `outcome` for approve); creates immutable `DecisionEvent`; updates `FraudAlert.status=resolved`; returns 201 DecisionEvent; GET returns ordered list of all DecisionEvents for alert
- [X] T046 [US3] Wire `notification_service.send_alert_notification` into `src/fraud-alert-agent/app/agents/escalation_node.py` for Critical-severity alerts — call after investigation completes, before returning state

**Checkpoint**: All user stories 1–3 should now be independently functional

---

## Phase 6: User Story 4 — Alert Dashboard and Case Management (Priority: P4)

**Goal**: Streamlit dashboard showing live alert queue (filterable by severity/status/time) + agent chat/trace panel displaying investigation steps for any selected alert. REST metrics endpoint backs both the dashboard and Prometheus.

**Independent Test**: Start the dashboard against a Postgres instance seeded with sample alerts; filter by "Critical / Open" and verify only matching alerts appear sorted by `created_at DESC`; click an alert and verify all investigation steps render in order; open the metrics panel and verify `alert_count`, `auto_resolution_rate`, `avg_time_to_decision_minutes`, `false_positive_rate`, `sla_breach_rate` are shown.

### Validation for User Story 4 ⚠️

- [X] T047 [P] [US4] Write contract test for `GET /api/v1/metrics` in `src/fraud-alert-agent/tests/contract/test_metrics_contract.py` — seed sample alert + decision records; assert `AlertMetrics` response fields match schema; assert window_hours parameter is respected

### Implementation for User Story 4

- [X] T048 [P] [US4] Implement metrics computation in `src/fraud-alert-agent/app/services/alert_service.py` — `get_metrics(window_hours)` queries: total alert count, fraction resolved by agent-only DecisionEvents (auto_resolution_rate), avg minutes from alert created_at to first human DecisionEvent (avg_time_to_decision_minutes), fraction of Critical alerts with override outcome=false_positive (false_positive_rate), fraction of Critical alerts with status=sla_breached (sla_breach_rate)
- [X] T049 [P] [US4] Implement `GET /api/v1/metrics` route in `src/fraud-alert-agent/app/api/metrics_api.py` — call `alert_service.get_metrics(window_hours)`; require `verify_api_key`; return `AlertMetrics` schema per contract
- [X] T050 [P] [US4] Add Prometheus metrics instrumentation to `src/fraud-alert-agent/app/main.py` — register `fraud_alerts_total` counter (labels: severity), `investigation_duration_seconds` histogram, `sla_breaches_total` counter, `ollama_inference_seconds` histogram; expose `GET /metrics` via `prometheus-client` ASGI app
- [X] T051 [US4] Build `src/fraud-alert-agent/dashboard/app.py` — Streamlit app that: (1) sidebar with severity multiselect, status multiselect, and date-range picker; (2) main panel showing paginated alert table (`st.dataframe`) fetched from `GET /api/v1/alerts` via `httpx`; auto-refreshes every 10 seconds via `st_autorefresh`; (3) clicking a row sets `st.session_state.selected_alert_id`
- [X] T052 [US4] Add investigation trace/chat panel to `src/fraud-alert-agent/dashboard/app.py` — when `selected_alert_id` is set, fetch `GET /api/v1/alerts/{id}/investigation` and render each `InvestigationStep` as an expandable `st.expander` (node name, tool name, input/output JSON, duration_ms); show LLM reasoning text in a `st.chat_message` styled block; show evidence list as a ranked `st.table`
- [X] T053 [US4] Add metrics summary panel to `src/fraud-alert-agent/dashboard/app.py` — fetch `GET /api/v1/metrics` and display `alert_count`, `auto_resolution_rate`, `avg_time_to_decision_minutes`, `false_positive_rate`, `sla_breach_rate` as `st.metric` cards in a top-of-page row
- [X] T054 [US4] Add Streamlit service to `src/fraud-alert-agent/docker-compose.yml` — `streamlit run dashboard/app.py` on port 8501; env vars: `FRAUD_AGENT_BASE_URL=http://fraud-alert-agent:8000`, `FRAUD_API_KEY`

**Checkpoint**: Full stack — pipeline + dashboard — independently deployable and demonstrable

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, observability, and operational sign-off across all stories

- [ ] T055 [P] Update `docs/FRAUD_SCORE_ENRICHER.md` to describe how `transactions_scored` feeds into the fraud-alert-agent (DI-001) — add "Downstream consumers" section pointing to alert monitor poll interval, threshold values, and snapshot cursor mechanism
- [ ] T056 [P] Create `docs/runbooks/fraud-alert-agent.md` operational runbook (DI-002) — cover: reconfiguring alert thresholds (env var update + rollout), adding/removing notification channels, replaying a failed investigation (Postgres checkpoint reset procedure), interpreting agent evidence output, Ollama model swap, Postgres failover
- [ ] T057 [P] Update root `README.md` to include fraud-alert-agent in the system architecture diagram and stack table (DI-003)
- [ ] T058 [P] Write `src/fraud-alert-agent/README.md` — purpose, prerequisites (per quickstart.md), local dev steps, required env vars table, Docker Compose usage, Minikube deployment steps, Streamlit dashboard URL, troubleshooting section
- [ ] T059 Validate all quickstart.md integration scenarios manually: Scenario 1 (end-to-end alert), Scenario 2 (idempotency), Scenario 3 (approval), Scenario 4 (override), Scenario 5 (metrics), Scenario 6 (health check); document any deviations
- [ ] T060 Performance validation: run load test injecting 500 synthetic scored transactions over 1 hour; verify P95 investigation latency ≤ 60 seconds and Prometheus `investigation_duration_seconds` histogram reflects this; verify `fraud_alerts_total` counter increments correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Story Phases (3–6)**: All depend on Phase 2 completion
  - Stories can proceed in priority order (P1 → P2 → P3 → P4) or in parallel if staffed
  - US2 lightly extends US1 investigation_node and graph — should follow US1 completion
  - US3 extends escalation_node (US1) and needs notification_service before SLA worker
  - US4 (dashboard) is fully independent of US2/US3 — can start after Phase 2
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2 — no other story dependencies; self-contained MVP
- **US2 (P2)**: Extends US1 investigation_node and graph — implement after US1 checkpoint
- **US3 (P3)**: Requires escalation_node (US1) and notification_service; can proceed after US1
- **US4 (P4)**: Only depends on Phase 2 (DB + API foundation) and US1 alerts endpoint; dashboard and metrics are additive

### Within Each User Story

- Validation tasks (contract + integration tests) should be written first so they fail before implementation
- Models (state, ORM) → services → workers → API routes → tests pass
- README and operational doc updates before story sign-off

### Parallel Opportunities

- All [P]-marked tasks within the same phase can run simultaneously
- T019–T022 (state + tools) can all be implemented in parallel within US1
- T037–T039 (US3 validation tests) can all be written in parallel
- T048–T050 (metrics + Prometheus) are independent of each other
- T055–T058 (all doc updates) are fully independent of each other

---

## Parallel Example: User Story 1

```bash
# Write all validation tasks simultaneously:
Task T016: contract test for GET /api/v1/alerts in tests/contract/test_alerts_contract.py
Task T017: integration test for alert pipeline in tests/integration/test_alert_pipeline.py

# Then implement state and tools simultaneously:
Task T019: AgentState TypedDict in app/agents/state.py
Task T020: transaction_history_tool in app/tools/transaction_history_tool.py
Task T021: pattern_lookup_tool in app/tools/pattern_lookup_tool.py
Task T022: feature_context_tool in app/tools/feature_context_tool.py

# Then sequentially: triage_node → investigation_node → escalation_node → graph → services → worker → routes
```

## Parallel Example: User Story 4

```bash
# Metrics backend and Prometheus are independent of Streamlit UI:
Task T048: metrics computation in alert_service.py
Task T049: GET /api/v1/metrics route in app/api/metrics_api.py
Task T050: Prometheus instrumentation in app/main.py

# Streamlit panels build on each other sequentially:
Task T051: live alerts table → Task T052: trace panel → Task T053: metrics panel
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (alert monitor + LangGraph triage + investigation + REST read endpoints)
4. **STOP and VALIDATE**: Inject synthetic transaction, verify alert + investigation within 60s
5. Deploy to Minikube and demo

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → Alert pipeline live, basic REST API — **MVP demo**
3. US2 → Full audit trail, idempotency hardened
4. US3 → Human approval/override + Slack notifications + SLA enforcement
5. US4 → Streamlit dashboard (live alerts table + investigation trace/chat panel)
6. Phase 7 → Docs, runbook, performance validation → Production-ready

### Parallel Team Strategy

With multiple developers, once Phase 2 is complete:

- **Developer A**: US1 (alert monitor, LangGraph graph, investigation pipeline)
- **Developer B**: US4 (Streamlit dashboard, metrics endpoint, Prometheus)
- **Developer C**: US3 (notification service, SLA worker, decisions API)
- US2 polish applied by Developer A once US1 checkpoint passes

---

## Notes

- [P] tasks = different files, no shared state dependencies — safe to parallelise
- [Story] label maps every task to a specific user story for traceability
- Tests are mandatory for security-sensitive (auth), regression-risk (idempotency), and integration-critical (pipeline, decisions) paths
- Streamlit dashboard (`src/fraud-alert-agent/dashboard/app.py`) communicates with the FastAPI service via the same `GET /api/v1/alerts` and `GET /api/v1/alerts/{id}/investigation` endpoints defined in the contract — no additional backend changes required
- Do not defer README, security, observability, or performance work to an undefined follow-up
- Commit after each task or logical group
- Stop at any checkpoint to validate the story independently before proceeding
