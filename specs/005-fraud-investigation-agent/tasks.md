# Tasks: Fraud Investigation Agent

**Input**: Design documents from `specs/005-fraud-investigation-agent/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/investigation-sessions-api.yaml, research.md

**Tests**: Automated tests required for all backend endpoints (security-sensitive), DB models
(regression risk), and the session graph (correctness of grounding). Streamlit UI validated
via integration tests against FastAPI TestClient and manual quickstart.md walkthrough.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths required in every task

**User Input Override**: Streamlit UI lives at `src/streamlit-ui/` (standalone project) with
direct dependencies: `streamlit`, `pandas`, `pyiceberg`, `httpx`. This overrides the plan's
`src/fraud-alert-agent/investigation_ui/` location.

**Amendment**: LangGraph session graph gains a 4th tool — `get_transaction_details(transaction_id: str)` — that queries `fraud.transactions` via the existing PyIceberg + Polaris catalog, returns the matched row, current snapshot ID/timestamp, and recent snapshot history for time-travel context. Tasks T049–T051 are added to Phase 2 (Foundational).

**Amendment 2**: LangGraph session graph gains a 5th tool — `get_user_history(user_id: str, days: int = 90)` — that aggregates velocity, location changes, and transaction timing patterns from `fraud.transactions` over a configurable window. Note: the `transactions` table has no device column (`transaction_id`, `user_id`, `amount`, `merchant`, `lat`, `lon`, `ts`, `processing_time`, `amount_velocity_5min`, `distance_from_home_km`) — transaction timing patterns (hour-of-day buckets, unusual-hour flag) are implemented as a proxy for device patterns. Tasks T052–T054 are added to Phase 2 (Foundational). Complements the existing `pattern_lookup_tool` (amount stats, hardcoded 30d) — `get_user_history` covers location/velocity/timing over a configurable window.

**Amendment 3**: LangGraph session graph gains a 6th tool — `explain_fraud_flag(transaction_json: str, user_history_json: str, fraud_score: float) -> str` — a synthesis tool that mirrors the existing `analysis_node.py` pattern but is callable by the ReAct agent as a `@tool`. It uses `get_llm_plain()` (plain-text mode, not JSON mode) with the prompt: `"Given this transaction details, user history, and model probability of {score}, provide a clear, concise reason why it was flagged as fraud. Highlight anomalies."` The agent calls this after gathering evidence from `get_transaction_details` and `get_user_history`. Tasks T055–T057 are added to Phase 2 (Foundational).

**Amendment 4**: Streamlit UI gains transaction visualizations in Phase 5 (US3): an Altair timeline (amount over time, flagged transaction highlighted) and a `st.map()` location plot using the `lat`/`lon` columns from `fraud.transactions`. `altair>=5.0` added to `src/streamlit-ui/pyproject.toml`. Tasks T058–T060 are added to Phase 5 (US3).

**Amendment 5**: Slack fraud alert notifications gain a deep-link to the Streamlit investigation UI: `"Investigate in UI: {INVESTIGATION_UI_BASE_URL}/?transaction_id={transaction_id}"`. New `INVESTIGATION_UI_BASE_URL` config setting added to `app/config.py` and Kubernetes ConfigMap. The Streamlit app handles the `?transaction_id=` query param on load to auto-select the alert. Tasks T061–T064 are added to Phase 7 (Polish).

**Amendment 6**: A new FastAPI entry-point endpoint `POST /api/v1/investigate` accepts `transaction_id` directly, resolves it to a `FraudAlert`, creates an investigation session, and runs the LangGraph session graph — returning the `OpenSessionResponse`. A companion lookup `GET /api/v1/alerts/by-transaction/{transaction_id}` is also added for direct alert resolution. The Streamlit `api_client` is updated to use `POST /api/v1/investigate` as the deep-link auto-open path. Tasks T065–T068 are added to Phase 7 (Polish).

**Amendment 7**: FluxCD GitOps wiring for the Streamlit investigation UI. The FluxCD `Kustomization` CRD at `clusters/minikube/apps.yaml` points to `./apps/minikube`; adding `fraud-investigation-ui` to `apps/minikube/kustomization.yaml` is the single change that causes FluxCD to begin reconciling the new Streamlit deployment after the manifests from T042/T043 are committed. The minikube overlay kustomization also requires an `images:` block (matching the `fraud-alert-agent` pattern) to enable GitOps image tag management. Tasks T069–T072 are added to Phase 7 (Polish).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create both project skeletons before story work begins

- [X] T001 Create `src/streamlit-ui/` directory structure: `src/streamlit-ui/app.py`, `src/streamlit-ui/api_client.py`, `src/streamlit-ui/components/` (empty), `src/streamlit-ui/README.md`
- [X] T002 Create `src/streamlit-ui/pyproject.toml` with project name `fraud-investigation-ui`, Python >=3.11, dependencies: `streamlit>=1.35`, `pandas>=2.0`, `pyiceberg[pyarrow,s3]==0.7.1`, `httpx>=0.27`; add `dev` extras: `pytest>=8`
- [X] T003 [P] Scaffold `src/streamlit-ui/app.py` with `st.set_page_config`, `st.sidebar` block (placeholder), and main chat area block (placeholder) — enough to run `streamlit run app.py` without errors
- [X] T004 [P] Identify and list all README and operational docs affected by this feature: `src/fraud-alert-agent/README.md`, `docs/runbooks/fraud-alert-agent.md`, `README.md` (root)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Backend DB schema, models, LangGraph session graph, and PII masking must exist before any user story endpoint can be implemented

**⚠️ CRITICAL**: No user story implementation can begin until this phase is complete

- [X] T005 Add `InvestigationSession`, `SessionTurn`, and `InvestigationConclusion` ORM models to `src/fraud-alert-agent/app/db/models.py` per `specs/005-fraud-investigation-agent/data-model.md` (status enums, FK relationships, indexes)
- [X] T006 Create Alembic migration `src/fraud-alert-agent/app/db/migrations/versions/XXXX_add_investigation_sessions_tables.py` — creates `investigation_sessions`, `session_turns`, `investigation_conclusions` tables with all indexes and constraints from data-model.md; verify `alembic upgrade head` and `alembic downgrade -1` both succeed
- [X] T007 [P] Create `src/fraud-alert-agent/app/tools/pii_masking.py` — `mask_pii(value: str | dict) -> str | dict` function that redacts card numbers to last 4 digits, SSNs, and email addresses using regex; apply as a wrapper in `transaction_history_tool.py`, `pattern_lookup_tool.py`, and `feature_context_tool.py`
- [X] T008 [P] Create `src/fraud-alert-agent/app/agents/investigation_session_state.py` — `InvestigationSessionState` TypedDict extending `MessagesState` with fields: `session_id: str`, `alert_id: str`, `analyst_id: str`
- [X] T009 Create `src/fraud-alert-agent/app/agents/investigation_session_graph.py` — `create_react_agent` graph with four tools: `transaction_history_tool`, `pattern_lookup_tool`, `feature_context_tool`, and `get_transaction_details` (added by T049); system prompt instructs the agent to ground every response in tool output, never fabricate, and use `get_transaction_details` when the analyst asks about a specific transaction ID or snapshot; expose `get_session_graph()` factory function; **depends on T049**
- [X] T010 Create `src/fraud-alert-agent/app/services/session_service.py` — async functions: `create_session(alert_id, analyst_id)`, `get_session(session_id)`, `create_turn(session_id, analyst_input, agent_response, tool_calls)`, `list_turns(session_id)`, `conclude_session(session_id, outcome, notes)` with Postgres row-level lock on conclude to detect concurrent conclusions (return `ConflictError` if `InvestigationConclusion.alert_id` unique constraint would be violated)
- [X] T011 [P] Create `src/fraud-alert-agent/tests/unit/test_pii_masking.py` — unit tests for `mask_pii`: card number masking, SSN masking, email masking, passthrough of non-PII values, nested dict handling
- [X] T012 [P] Capture performance baseline for initial session turn (Ollama inference + tool calls): document expected p95 latency in `specs/005-fraud-investigation-agent/plan.md` Performance Goals section (target ≤ 30s)
- [X] T049 [P] Create `src/fraud-alert-agent/app/tools/transaction_details_tool.py` — `@tool` function `get_transaction_details(transaction_id: str) -> TransactionDetailsResult` (TypedDict: `transaction: dict | None`, `snapshot_id: int | None`, `snapshot_timestamp_ms: int | None`, `table_history: list[dict]`, `error: str | None`); implementation: call `load_table("fraud", "transactions")` from `app.tools.iceberg_catalog`, scan with `row_filter=f"transaction_id = '{transaction_id}'"` and `limit=1`, call `table.current_snapshot()` for snapshot metadata, call `table.history()` for the 10 most recent history entries (each entry: `snapshot_id`, `timestamp_ms`), apply `mask_pii()` to the transaction row before returning; return `error` string and empty fields on any exception; import `mask_pii` from `app.tools.pii_masking` — **depends on T007**
- [X] T050 [P] Create `src/fraud-alert-agent/tests/unit/test_transaction_details_tool.py` — unit tests using `pytest-mock`: (1) mock `load_table` to return a table stub with a matching row — assert `transaction` populated and PII masked; (2) mock table to return empty scan — assert `transaction` is None and no error; (3) mock `load_table` to raise an exception — assert `error` field populated and `transaction` is None; (4) assert `table_history` contains at most 10 entries; (5) assert `snapshot_id` and `snapshot_timestamp_ms` match the mocked `current_snapshot()` return value
- [X] T051 Update `src/fraud-alert-agent/app/agents/investigation_session_graph.py` (task T009's output) to import `get_transaction_details` from `app.tools.transaction_details_tool` and include it in the tool list passed to `create_react_agent`; update the system prompt to state: "Use `get_transaction_details` when the analyst asks to see the full details of a specific transaction by ID, or asks about which snapshot or point-in-time the data comes from." — **depends on T049 and T009**
- [X] T052 [P] Create `src/fraud-alert-agent/app/tools/user_history_tool.py` — `@tool` function `get_user_history(user_id: str, days: int = 90) -> UserHistoryResult` (TypedDict: `transaction_count: int`, `total_amount: float`, `velocity_txns_per_day: float`, `unique_merchants: int`, `merchant_list: list[str]`, `unique_locations: int`, `avg_distance_from_home_km: float`, `max_distance_from_home_km: float`, `avg_amount_velocity_5min: float`, `peak_hour_buckets: dict[str, int]`, `unusual_hour_flag: bool`, `error: str | None`); implementation: compute `cutoff = datetime.now(timezone.utc) - timedelta(days=days)`, call `query_iceberg_table.invoke({"namespace": "fraud", "table_name": "transactions", "row_filter": f"user_id = {int(user_id)} AND ts >= '{cutoff.isoformat()}'", "limit": 5000})`, then aggregate using pure Python over `result["rows"]`: velocity = `transaction_count / days`, unique merchants = `len(set(r["merchant"] for r in rows))`, unique locations = `len(set((round(r["lat"],2), round(r["lon"],2)) for r in rows))`, avg/max `distance_from_home_km`, avg `amount_velocity_5min`, `peak_hour_buckets` = top-5 hours by count from `ts` parsed with `datetime.fromisoformat()`, `unusual_hour_flag` = True if any transaction `ts` hour is in range 2–5 (UTC); apply `mask_pii()` to merchant names in `merchant_list`; return error string and zero values on exception; import `mask_pii` from `app.tools.pii_masking` — **depends on T007**
- [X] T053 [P] Create `src/fraud-alert-agent/tests/unit/test_user_history_tool.py` — unit tests using `pytest-mock` to mock `query_iceberg_table.invoke`: (1) user with 10 rows across 3 merchants and 2 locations — assert `unique_merchants=3`, `unique_locations=2`, velocity = `10/90`, `merchant_list` length 3 and PII-masked; (2) user with no transactions — assert all numeric fields are 0.0, `merchant_list` empty, no error; (3) catalog exception — assert `error` populated and all numeric fields 0; (4) row with `ts` at hour 03:00 UTC — assert `unusual_hour_flag=True`; (5) custom `days=7` parameter — assert filter string contains the correct 7-day cutoff date
- [X] T054 Update `src/fraud-alert-agent/app/agents/investigation_session_graph.py` to import `get_user_history` from `app.tools.user_history_tool` and add it as the 5th tool in the `create_react_agent` tool list; update the system prompt to add: "Use `get_user_history` when the analyst asks about the user's transaction history, location patterns, velocity, or unusual timing — it aggregates behaviour over a configurable window (default 90 days). Prefer `get_user_history` over `pattern_lookup_tool` when the analyst asks about location, geographic spread, or time-of-day patterns; use `pattern_lookup_tool` when they ask specifically about amount statistics." — **depends on T052 and T051**
- [X] T055 [P] Create `src/fraud-alert-agent/app/tools/explanation_tool.py` — `@tool` function `explain_fraud_flag(transaction_json: str, user_history_json: str, fraud_score: float) -> str`; implementation: (1) parse inputs via `json.loads(transaction_json)` and `json.loads(user_history_json)`; (2) build `system_msg = f"Given this transaction details, user history, and model probability of {fraud_score:.2%}, provide a clear, concise reason why it was flagged as fraud. Highlight anomalies."`; (3) build `user_msg = json.dumps({"transaction": tx_dict, "user_history": history_dict}, default=str)`; (4) call `get_llm_plain()` from `app.agents.llm` using `concurrent.futures.ThreadPoolExecutor` with a `timeout=settings.ANALYSIS_TIMEOUT_SECONDS` second deadline (call `llm.invoke([{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}])`); (5) return `response.content` as a plain string; (6) on `concurrent.futures.TimeoutError` return `"Explanation timed out — review the transaction data manually."`; (7) on `json.JSONDecodeError` return `"Invalid input data — could not parse transaction or user history."`; (8) on any other exception return `f"Explanation unavailable: {exc}"`; log all errors and timeouts via `structlog` with fields `fraud_score`, `error`
- [X] T056 [P] Create `src/fraud-alert-agent/tests/unit/test_explanation_tool.py` — unit tests using `pytest-mock`: (1) mock `get_llm_plain()` to return a mock whose `.invoke()` returns `MagicMock(content="The transaction was flagged because of unusual amount.")` — assert returned string equals the content; (2) mock `ThreadPoolExecutor.submit().result()` to raise `concurrent.futures.TimeoutError` — assert return contains "timed out"; (3) mock LLM `.invoke()` to raise `RuntimeError("llm error")` — assert return starts with "Explanation unavailable"; (4) pass `fraud_score=0.92` and assert the string `"92.00%"` appears in the system message captured by the mock; (5) pass malformed `transaction_json='not-json'` — assert return starts with "Invalid input"
- [X] T057 Update `src/fraud-alert-agent/app/agents/investigation_session_graph.py` to import `explain_fraud_flag` from `app.tools.explanation_tool` and add it as the 6th tool in the `create_react_agent` tool list; update the system prompt to add: "Use `explain_fraud_flag` to synthesise a plain-language fraud explanation from gathered evidence — call it after you have already retrieved transaction details (via `get_transaction_details`) and user history (via `get_user_history`). Pass them as JSON strings using `json.dumps(...)` and include the alert's `fraud_score` as a float. This is the preferred tool for the initial explanation turn and for any analyst question asking 'why was this flagged?'" — **depends on T055, T052, T054**

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Open Investigation and Get Initial Explanation (Priority: P1) 🎯 MVP

**Goal**: Analyst opens a session for a fraud alert and the agent immediately returns a structured explanation with risk signals and supporting data values

**Independent Test**: `POST /api/v1/alerts/{alert_id}/investigation-sessions` with a valid alert ID; verify response includes `session_id`, `initial_turn.agent_response` with ≥3 risk signals, and the turn is persisted in `session_turns`

### Validation for User Story 1 ⚠️

- [X] T013 [P] [US1] Contract test for session open endpoint in `src/fraud-alert-agent/tests/contract/test_sessions_contract.py` — verify request/response schema matches `contracts/investigation-sessions-api.yaml`; test 201 on valid alert, 404 on unknown alert
- [X] T014 [P] [US1] Integration test for full session open flow in `src/fraud-alert-agent/tests/integration/test_investigation_session.py` — seed a `FraudAlert` row, call the endpoint, assert `InvestigationSession` row created, `SessionTurn` row persisted, LangGraph checkpoint written

### Implementation for User Story 1

- [X] T015 [US1] Create `src/fraud-alert-agent/app/api/sessions.py` — implement `POST /api/v1/alerts/{alert_id}/investigation-sessions`: verify alert exists, call `session_service.create_session()`, invoke `investigation_session_graph` with auto-generated initial prompt `"Explain why transaction {tx_id} was flagged as potentially fraudulent. Include the top risk signals and their supporting data values."`, persist Turn 1 via `session_service.create_turn()`, return `OpenSessionResponse`
- [X] T016 [US1] Register sessions router in `src/fraud-alert-agent/app/main.py` — include `sessions.router` under `/api/v1` prefix with `verify_api_key` dependency
- [X] T017 [US1] Add `X-Analyst-Id` header extraction to `src/fraud-alert-agent/app/api/deps.py` — return analyst identity for use in session creation; reject requests without the header with HTTP 400
- [X] T018 [US1] Implement sidebar alert selector in `src/streamlit-ui/components/sidebar.py` — `render_sidebar(api_client) -> tuple[str | None, str | None]` returns `(selected_alert_id, session_id)`; fetches open/in_review alerts from `GET /api/v1/alerts?status=open,in_review`; shows severity indicator and transaction ID; "Start Investigation" button calls `POST /api/v1/alerts/{id}/investigation-sessions`
- [X] T019 [US1] Create `src/streamlit-ui/api_client.py` — `FraudAgentClient(base_url, api_key, analyst_id)` with methods: `open_session(alert_id)`, `get_turns(session_id)`, `create_turn(session_id, question)`, `conclude_session(session_id, outcome, notes)`, `list_alerts(status)` — all using `httpx` with `X-API-Key` and `X-Analyst-Id` headers; raise `SessionConflictError` on HTTP 409
- [X] T020 [US1] Implement initial explanation display in `src/streamlit-ui/components/chat.py` — `render_chat_history(turns: list[dict])` displays each turn as `st.chat_message("user")` + `st.chat_message("assistant")`; highlight Turn 1 as "Initial Explanation" header
- [X] T021 [US1] Wire sidebar and chat into `src/streamlit-ui/app.py` — on session open: store `session_id` in `st.session_state`; fetch turns via `api_client.get_turns()`; call `render_chat_history()`; call `render_sidebar()` in `st.sidebar` block
- [X] T022 [US1] Update `src/fraud-alert-agent/README.md` — add "Investigation Sessions" section covering the new endpoints and the Streamlit UI

**Checkpoint**: Analyst can open a session and see the initial explanation — US1 independently testable

---

## Phase 4: User Story 2 — Ask Follow-Up Questions in Plain Language (Priority: P2)

**Goal**: Analyst types a natural-language question in the chat input; agent responds with tool-grounded evidence within 15 seconds

**Independent Test**: With an active session, `POST /api/v1/investigation-sessions/{session_id}/turns` with `{"question": "Has this merchant been associated with fraud before?"}` returns a non-empty `agent_response` referencing real data; turn is persisted in `session_turns`

### Validation for User Story 2 ⚠️

- [X] T023 [P] [US2] Contract test for `POST /turns` in `src/fraud-alert-agent/tests/contract/test_sessions_contract.py` — verify 200 with `SessionTurn` schema; 404 on unknown session; 409 on concluded session
- [X] T024 [P] [US2] Integration test for multi-turn conversation in `src/fraud-alert-agent/tests/integration/test_investigation_session.py` — open a session, submit 3 sequential questions, assert all 3 turns persisted with correct `turn_number`, assert agent references tool output in response

### Implementation for User Story 2

- [X] T025 [US2] Implement `POST /api/v1/investigation-sessions/{session_id}/turns` in `src/fraud-alert-agent/app/api/sessions.py` — validate session is `active`; invoke `investigation_session_graph` with the analyst's question appended as `HumanMessage` to the thread; persist the response as `SessionTurn`; update `last_active_at` on `InvestigationSession`; return `SessionTurn` response; return 409 if session status is `concluded` or `abandoned`
- [X] T026 [US2] Implement `GET /api/v1/investigation-sessions/{session_id}/turns` in `src/fraud-alert-agent/app/api/sessions.py` — return ordered list of `SessionTurn` records for the session
- [X] T027 [US2] Add chat input to `src/streamlit-ui/app.py` — `st.chat_input("Ask a question about this transaction…")` in the main area; on submit call `api_client.create_turn(session_id, question)`, append new turn to `st.session_state["turns"]`, rerender chat via `render_chat_history()`; disable input when session status is `concluded` or `abandoned`
- [X] T028 [US2] Add out-of-scope question handling display to `src/streamlit-ui/components/chat.py` — render assistant responses that begin with a refusal indicator in a distinct style (e.g., `st.info` callout)

**Checkpoint**: Full back-and-forth conversation works end-to-end — US1 + US2 both functional

---

## Phase 5: User Story 3 — Explore Underlying Evidence and Data (Priority: P3)

**Goal**: Analyst requests raw evidence (transaction history, ML feature values, merchant data); agent returns structured data viewable in the UI; optional direct Iceberg query for transaction history

**Independent Test**: In an active session, ask "Show me this user's last 10 transactions" and verify the response includes tabular transaction data; ask "Show me the ML feature values" and verify feature names with values and baselines are returned

### Validation for User Story 3 ⚠️

- [X] T029 [P] [US3] Integration test for evidence retrieval in `src/fraud-alert-agent/tests/integration/test_investigation_session.py` — ask tool-triggering questions and assert `tool_calls` field in `SessionTurn` is non-empty and matches expected tool names

### Implementation for User Story 3

- [X] T030 [US3] Create `src/streamlit-ui/components/evidence.py` — `render_evidence_table(data: list[dict], title: str)` using `pandas.DataFrame` + `st.dataframe(df, use_container_width=True)` with sensible column formatting; used when agent response includes structured tabular data in a fenced JSON block
- [X] T031 [US3] Add evidence block parser to `src/streamlit-ui/components/chat.py` — detect fenced `json` blocks in agent response text; if the block is a list of dicts, render via `render_evidence_table()` below the text response; otherwise render as `st.json()`
- [X] T032 [US3] Add direct Iceberg transaction history lookup to `src/streamlit-ui/api_client.py` — optional `get_transaction_history(user_id, limit=10)` method using `pyiceberg` to query the `transactions` Iceberg table directly (uses `ICEBERG_CATALOG_URI` env var); falls back gracefully if catalog is unreachable; used as a supplementary "View raw history" button in the sidebar
- [X] T033 [US3] Add "View raw transaction history" expander to `src/streamlit-ui/components/sidebar.py` — renders a collapsed `st.expander` that on expand calls `api_client.get_transaction_history()` and displays results via `render_evidence_table()`
- [X] T058 Add `altair>=5.0` to the `dependencies` list in `src/streamlit-ui/pyproject.toml` (alongside existing `streamlit`, `pandas`, `pyiceberg`, `httpx`)
- [X] T059 [P] [US3] Create `src/streamlit-ui/components/visualizations.py` with two functions: (1) `render_transaction_timeline(transactions: list[dict], flagged_transaction_id: str | None = None)` — builds a `pandas.DataFrame` from the list with columns `ts` (parsed to datetime), `amount`, `merchant`, `transaction_id`; constructs an Altair layered chart: a base line+point chart of `amount` over `ts` coloured by `merchant`, plus a second layer of red rule marks at rows where `transaction_id == flagged_transaction_id`; renders via `st.altair_chart(chart, use_container_width=True)`; shows `st.info("No transaction history available.")` if list is empty; (2) `render_location_map(transactions: list[dict])` — filters rows where both `lat` and `lon` are non-null, builds a `pandas.DataFrame` with columns `lat` (float) and `lon` (float) and `merchant` (str); renders via `st.map(df, zoom=10)`; shows `st.info("No location data available.")` if no valid coordinates exist
- [X] T060 [US3] Wire visualizations into `src/streamlit-ui/app.py` — after `render_chat_history()`, add a `st.expander("📈 Transaction Timeline & Locations", expanded=False)` that on expand: (a) calls `api_client.get_transaction_history(user_id=alert["user_id"], limit=100)` where `alert` is the selected alert fetched earlier; (b) calls `render_transaction_timeline(rows, flagged_transaction_id=alert["transaction_id"])` and `render_location_map(rows)` side-by-side in `st.columns(2)`; import both functions from `src/streamlit-ui/components/visualizations.py`

**Checkpoint**: Analyst can view structured evidence tables alongside agent explanations — US1 + US2 + US3 all functional

---

## Phase 6: User Story 4 — Record Investigation Conclusion (Priority: P4)

**Goal**: Analyst selects Confirmed Fraud / False Positive / Escalate, adds notes, submits; conclusion persisted with analyst identity and timestamp; alert status updated; session transitions to concluded

**Independent Test**: After an investigation, submit `POST /api/v1/investigation-sessions/{session_id}/conclude` with `{"outcome": "confirmed_fraud", "notes": "test"}` and verify `InvestigationConclusion` row created, `InvestigationSession.status` = `concluded`, parent `FraudAlert.status` = `resolved`; attempt a second conclude returns HTTP 409

### Validation for User Story 4 ⚠️

- [X] T034 [P] [US4] Contract test for `POST /conclude` and `GET /conclude` in `src/fraud-alert-agent/tests/contract/test_sessions_contract.py` — verify 201 schema, 409 conflict response schema, 404 on unknown session
- [X] T035 [P] [US4] Integration test for conclusion conflict detection in `src/fraud-alert-agent/tests/integration/test_investigation_session.py` — open two sessions for the same alert, conclude the first, attempt to conclude the second, assert 409 response with conflict details

### Implementation for User Story 4

- [X] T036 [US4] Implement `POST /api/v1/investigation-sessions/{session_id}/conclude` in `src/fraud-alert-agent/app/api/sessions.py` — call `session_service.conclude_session()`; on success also call `alert_service` to update `FraudAlert.status = "resolved"` and create a `DecisionEvent` via the existing decisions service; return `InvestigationConclusion` response; return 409 with prior conclusion detail on conflict
- [X] T037 [US4] Implement `GET /api/v1/investigation-sessions/{session_id}/conclude` in `src/fraud-alert-agent/app/api/sessions.py` — return the `InvestigationConclusion` for the session or 404 if none exists
- [X] T038 [US4] Add conclusion form to `src/streamlit-ui/components/sidebar.py` — `st.radio` for outcome selection (Confirmed Fraud / False Positive / Escalate); `st.text_area` for notes; "Submit Conclusion" button; on submit call `api_client.conclude_session()`; on 409 show `st.error` banner with prior analyst name and timestamp; on success show `st.success` and disable further input
- [X] T039 [US4] Show concluded session transcript in read-only mode in `src/streamlit-ui/app.py` — when session status is `concluded`, display a `st.info` banner "Investigation concluded — [outcome] by [analyst_id] at [timestamp]"; render full transcript via `render_chat_history()` in read-only mode (no chat input)

**Checkpoint**: Full investigation lifecycle complete — open, investigate, conclude — US1–US4 all functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Observability, operational docs, Kubernetes deployment, session timeout, and end-to-end validation

- [X] T040 [P] Extend `src/fraud-alert-agent/app/workers/sla_worker.py` — add session timeout sweep: query `investigation_sessions` where `status = 'active'` and `last_active_at < now() - SESSION_TIMEOUT_MINUTES`; set status to `abandoned`; log with `structlog` fields `session_id`, `analyst_id`, `idle_minutes`
- [X] T041 [P] Add new Prometheus metrics to `src/fraud-alert-agent/app/metrics.py`: `investigation_session_opens_total` (counter), `investigation_session_turn_duration_seconds` (histogram, buckets 1–30s), `investigation_conclusions_total` with `outcome` label (counter); instrument sessions endpoint handlers
- [X] T042 [P] Create Kubernetes manifests for the investigation UI at `apps/base/fraud-investigation-ui/deployment.yaml`, `apps/base/fraud-investigation-ui/service.yaml`, `apps/base/fraud-investigation-ui/configmap.yaml`, `apps/base/fraud-investigation-ui/kustomization.yaml` — Streamlit on port 8501; `FRAUD_AGENT_BASE_URL` pointing to `fraud-alert-agent` cluster-internal service; `FRAUD_API_KEY` from existing secret
- [X] T043 [P] Create Minikube overlay at `apps/minikube/fraud-investigation-ui/kustomization.yaml` — image tag patch, resource limits
- [X] T044 Create `src/streamlit-ui/Dockerfile` — `python:3.11-slim` base; install `src/streamlit-ui/pyproject.toml` deps; non-root user; `ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]`
- [X] T045 Update `docs/runbooks/fraud-alert-agent.md` — add section: "Investigation Sessions" covering how to open a session, resolve a 409 conflict, replay an abandoned session, and interpret PII-masked values
- [X] T046 Update `README.md` (repo root) — add fraud investigation UI to the architecture diagram and component table alongside `fraud-alert-agent`
- [X] T047 [P] Add `src/streamlit-ui/` to root `.gitignore` exclusions if needed (e.g., `__pycache__`, `.streamlit/secrets.toml`); add `.streamlit/secrets.toml` to `.gitleaks.toml` allowlist
- [X] T061 [P] Add `INVESTIGATION_UI_BASE_URL: str = ""` to `src/fraud-alert-agent/app/config.py` `Settings` class (default empty string; when empty, the deep link is omitted from Slack messages)
- [X] T062 [P] Update `src/fraud-alert-agent/app/services/notification_service.py` — in `send_slack_notification()`, after the existing `_Explanation_` line append: `if settings.INVESTIGATION_UI_BASE_URL: text += f"\n🔍 *Investigate in UI*: {settings.INVESTIGATION_UI_BASE_URL}/?transaction_id={transaction_id}"` so the Slack message includes the clickable deep-link when `INVESTIGATION_UI_BASE_URL` is configured; **depends on T061**
- [X] T063 [P] Add `INVESTIGATION_UI_BASE_URL` entry to `apps/base/fraud-alert-agent/configmap.yaml` with a comment indicating the value should point to the `fraud-investigation-ui` service, e.g. `http://fraud-investigation-ui.fraud-agent.svc.cluster.local:8501`; add a corresponding patch in `apps/minikube/fraud-alert-agent/kustomization.yaml` for local development using `http://localhost:8501`
- [X] T064 Update `src/streamlit-ui/app.py` — at startup, read `st.query_params.get("transaction_id")` (Streamlit ≥1.30 API); if a `transaction_id` value is present, look up the matching alert via `api_client.list_alerts()`, store the alert ID in `st.session_state["selected_alert_id"]`, and set `st.session_state["auto_open_session"] = True` so the session-open flow triggers immediately on first render without the analyst manually selecting from the sidebar; if no matching alert is found for the `transaction_id`, show `st.warning("No alert found for transaction_id {transaction_id}.")` and proceed normally
- [X] T065 [P] Add `GET /api/v1/alerts/by-transaction/{transaction_id}` to `src/fraud-alert-agent/app/api/alerts.py` — query `fraud_alerts` where `transaction_id = :transaction_id`; return the same `FraudAlertResponse` schema as `GET /api/v1/alerts/{alert_id}`; return HTTP 404 with `{"detail": "No alert found for transaction_id {transaction_id}"}` if not found; register the new route on the existing alerts router (no new router needed)
- [X] T066 Add `POST /api/v1/investigate` to `src/fraud-alert-agent/app/api/sessions.py` — request body `{"transaction_id": str, "analyst_id": str}`; (1) call `alert_service.get_alert_by_transaction_id(transaction_id)` to resolve to a `FraudAlert` (raise HTTP 404 if not found); (2) delegate to `session_service.create_session(alert_id=alert.id, analyst_id=analyst_id)` to create the `InvestigationSession`; (3) invoke the investigation session graph for the initial explanation turn (same logic as `POST /api/v1/alerts/{alert_id}/investigation-sessions` in T015); (4) return `OpenSessionResponse` with HTTP 201; **depends on T065**
- [X] T067 Update `src/streamlit-ui/api_client.py` — add `run_investigation(transaction_id: str) -> dict` that calls `POST /api/v1/investigate` with body `{"transaction_id": transaction_id, "analyst_id": st.session_state.get("analyst_id", "analyst")}` and returns the `OpenSessionResponse` dict; update `src/streamlit-ui/app.py` deep-link auto-open logic from T064 — replace the two-step `list_alerts()` + `open_session()` flow with a single `api_client.run_investigation(transaction_id)` call; store the returned `session_id` and `alert_id` in `st.session_state` and skip the sidebar alert-selection step; **depends on T066**
- [X] T068 [P] Update `specs/005-fraud-investigation-agent/contracts/investigation-sessions-api.yaml` — add `GET /api/v1/alerts/by-transaction/{transaction_id}` path (returns `FraudAlertResponse` or 404) and `POST /api/v1/investigate` path (request body `{transaction_id: string, analyst_id: string}`, returns `OpenSessionResponse` with 201, or 404 if transaction not found); add `ByTransactionRequest` schema to `components/schemas`
- [X] T069 Add `- fraud-investigation-ui` to the `resources:` list in `apps/minikube/kustomization.yaml` — this is the single change that registers the Streamlit UI with the FluxCD reconciliation loop; the FluxCD `Kustomization` CRD at `clusters/minikube/apps.yaml` already points to `./apps/minikube` with `prune: true`, so after this commit FluxCD will create/update the deployment on its next 10-minute interval; **depends on T042, T043**
- [X] T070 [P] Confirm `apps/base/fraud-investigation-ui/kustomization.yaml` (created by T042) lists exactly `[configmap.yaml, deployment.yaml, service.yaml]` under `resources:` and does NOT include a namespace resource — the `fraud-agent` namespace is already owned by `apps/base/fraud-alert-agent/namespace.yaml` and must not be duplicated; also confirm the `deployment.yaml` references `fraud-agent-secrets` for the `FRAUD_API_KEY` env var using `secretKeyRef` (same pattern as `apps/base/fraud-alert-agent/deployment.yaml`); fix any gaps from T042; **depends on T042**
- [X] T071 [P] Confirm `apps/minikube/fraud-investigation-ui/kustomization.yaml` (created by T043) has `resources: [../../base/fraud-investigation-ui]` and an `images:` block `[{name: fraud-investigation-ui, newTag: "0.1.0"}]` matching the pattern in `apps/minikube/fraud-alert-agent/kustomization.yaml`; if the `images:` block is absent, add it — this is required for GitOps tag management (operators update `newTag`, commit, FluxCD reconciles); also confirm resource patches set `requests: {memory: 256Mi, cpu: 250m}` and `limits: {memory: 512Mi, cpu: 500m}` (Streamlit is lighter than the FastAPI backend); **depends on T043**
- [X] T072 Extend `specs/005-fraud-investigation-agent/quickstart.md` — add "GitOps / FluxCD Deployment" section documenting: (1) build and push the Streamlit image: `docker build -t fraud-investigation-ui:0.1.0 src/streamlit-ui/ && docker push <registry>/fraud-investigation-ui:0.1.0`; (2) update `newTag` in `apps/minikube/fraud-investigation-ui/kustomization.yaml` to match the pushed tag, commit, and push to trigger reconciliation; (3) monitor: `flux get kustomizations -n flux-system` (shows reconciliation status and last-applied revision) and `kubectl rollout status deployment/fraud-investigation-ui -n fraud-agent` (confirms pod readiness); (4) force an immediate reconcile without waiting: `flux reconcile kustomization apps -n flux-system`
- [ ] T048 Run `quickstart.md` end-to-end validation: start backend, apply migration, open a session, submit 3 questions, view evidence table, record conclusion, verify 409 on second conclude attempt; document any deviations

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Requires Phase 1 complete — BLOCKS all user story phases
- **US1 (Phase 3)**: Requires Phase 2 complete — first story to implement
- **US2 (Phase 4)**: Requires Phase 2 complete — can start in parallel with US1 if staffed
- **US3 (Phase 5)**: Requires Phase 2 complete — can start in parallel with US1/US2 if staffed
- **US4 (Phase 6)**: Requires Phase 2 complete — depends on session creation (T015) for integration test; otherwise independent
- **Polish (Phase 7)**: Requires all desired user stories complete

### User Story Dependencies

- **US1 (P1)**: Independent after Foundational — required for MVP
- **US2 (P2)**: Independent after Foundational — `GET /turns` in T026 needed by US3; otherwise independent
- **US3 (P3)**: Independent after Foundational — enhanced display depends on US2's turn data structure (share data-model, no code dependency)
- **US4 (P4)**: Independent after Foundational — uses `session_service.conclude_session()` from T010; T036 depends on T015 (sessions router) being merged

### Within Each User Story

- Contract tests → Integration tests → Models/Services → Endpoint → UI component → README
- Foundational models (T005) and migration (T006) before all service implementations
- Session graph (T009) before any turn invocation (T015, T025)
- Session service (T010) before all endpoint implementations

### Parallel Opportunities

- T007 (PII masking) and T008 (state typedef) and T011 (PII tests) can run in parallel during Phase 2
- T013 (contract tests US1) and T014 (integration tests US1) can be written in parallel before T015–T021
- T018 (sidebar), T019 (api_client), T020 (chat component) can be written in parallel within US1
- T040 (sla worker), T041 (metrics), T042–T043 (k8s manifests), T044 (Dockerfile), T047 (gitignore) can all run in parallel in Phase 7

---

## Parallel Example: User Story 1 (Phase 3)

```text
Parallel: T013 (contract test) + T014 (integration test) + T019 (api_client)
Then sequential: T015 (POST endpoint) → T016 (register router) → T017 (analyst header)
Parallel: T018 (sidebar component) + T020 (chat component)
Then: T021 (wire app.py) → T022 (README update)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: US1 — open session + initial explanation
4. **STOP and VALIDATE**: run `streamlit run src/streamlit-ui/app.py`, open a session, read the explanation
5. Demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → Initial explanation works → Demo (MVP!)
3. US2 → Follow-up Q&A works → Demo
4. US3 → Evidence tables visible → Demo
5. US4 → Conclusion recording works → Full loop demo
6. Polish → Production-ready

### Parallel Team Strategy

With two developers:
- **Developer A**: Backend (Phases 2–6 backend tasks)
- **Developer B**: Frontend (src/streamlit-ui — Phases 3–6 UI tasks, after T019 api_client is done)

---

## Notes

- [P] tasks = different files, no dependencies within their phase
- [Story] label maps each task to the spec.md user story it delivers
- `src/streamlit-ui/` is a standalone project (own `pyproject.toml`, own Dockerfile) — not embedded in `src/fraud-alert-agent/`
- `pyiceberg` in `src/streamlit-ui/pyproject.toml` enables optional direct Iceberg reads (T032) as a supplement to REST API calls
- PII masking (T007) is foundational — it must be in place before the session graph (T009) is wired up
- Conclude conflict detection uses DB-level unique constraint + row-level lock — do not implement as application-level check only
- Do not defer README (T022, T045, T046), observability (T041), or Kubernetes (T042–T044) to a follow-up
- Verify required tests fail before implementing the corresponding feature
