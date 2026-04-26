# Research: Fraud Investigation Agent

**Feature**: 005-fraud-investigation-agent  
**Date**: 2026-04-26  
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## Decision 1: Conversational LangGraph Pattern for Interactive Sessions

**Decision**: Each investigation session maps to a LangGraph thread (identified by `session_id` as `thread_id`) running a dedicated `investigation_session_graph`. The graph holds `MessagesState` (accumulated `HumanMessage` / `AIMessage` pairs). Creating a turn calls `graph.ainvoke({"messages": [HumanMessage(content=question)]}, config={"configurable": {"thread_id": session_id}})`, which appends to the thread's checkpoint state and returns the AI response.

**Rationale**: LangGraph's Postgres checkpoint backend (already deployed for the alert triage graph) provides durable, resumable session state at no additional infrastructure cost. The `thread_id` pattern maps cleanly to the `session_id` concept; session recovery after pod restart is automatic. Tool call traces are captured in checkpoint state, satisfying the spec's audit requirement for full session transcripts.

**Alternatives considered**:
- Stateless conversation history accumulated in a custom DB column — rejected because it duplicates LangGraph's checkpoint capability and loses tool call traces.
- A separate stateful session service — rejected as over-engineering; LangGraph already solves this.

---

## Decision 2: LangGraph Session Graph Topology

**Decision**: The session graph uses the `create_react_agent` factory (LangGraph ReAct agent) with the three existing investigation tools bound to the session LLM: `transaction_history_tool`, `pattern_lookup_tool`, and `feature_context_tool`. The LLM system prompt instructs the agent to ground every response in tool output and never fabricate values. On session open, an initial `HumanMessage("Explain why this transaction was flagged as potentially fraudulent. Transaction ID: {tx_id}")` is injected automatically to produce the initial explanation turn.

**Rationale**: ReAct (Reason + Act) agent pattern is the standard approach for tool-using conversational agents; LangGraph's `create_react_agent` handles the loop, tool dispatch, and message accumulation. Reusing the existing tools avoids duplicating data access logic and ensures grounding.

**Alternatives considered**:
- Custom StateGraph with explicit nodes per tool — rejected; ReAct agent is sufficient and far less code.
- Separate set of "investigation-specific" tools — rejected; the existing tools already fetch transaction history, ML features, and behavioural patterns, which cover all required evidence sources.

---

## Decision 3: Checkpoint Thread Namespace Isolation

**Decision**: No changes required to the checkpoint schema. The alert triage graph uses `alert_id` (UUID) as `thread_id`; the session graph uses `session_id` (UUID). Both are distinct UUID values generated independently, so they cannot collide in the shared `langgraph_checkpoints` Postgres table. The two graphs are also distinct graph names, providing a second isolation layer.

**Rationale**: LangGraph checkpoint tables key on `(thread_id, checkpoint_id)`. Since UUIDs are generated independently and the probability of collision is negligible (2^-122), no partitioning or namespace prefix is needed.

**Alternatives considered**:
- Prefix-based thread IDs (`alert-<uuid>` vs `session-<uuid>`) — considered but unnecessary; UUID uniqueness is sufficient.

---

## Decision 4: Streamlit Investigation UI Architecture

**Decision**: New Streamlit app at `src/fraud-alert-agent/investigation_ui/app.py`, separate from the existing `dashboard/app.py`. The UI has three views: (1) alert selector, (2) investigation chat (displays prior turns, accepts new input via `st.chat_input`, renders each turn with `st.chat_message`), and (3) conclusion recorder. The app is stateless between reruns — `st.session_state` holds `session_id` and turn count; full transcript is re-fetched from the backend on each rerun. No streaming for v1 (synchronous REST `POST /turns`).

**Rationale**: Separating the investigation UI from the operations dashboard keeps concerns clean — the dashboard is for managers/ops (alert queue, metrics), the investigation UI is for analysts actively working a case. Streamlit's native `st.chat_message` / `st.chat_input` components are purpose-built for this pattern. Stateless reruns plus backend fetch is consistent with the existing dashboard pattern (`dashboard/app.py` uses the same approach).

**Alternatives considered**:
- Embedding a chat panel inside the existing dashboard — rejected; mixing use cases in one app increases cognitive load for both user types.
- React/Next.js frontend — rejected as disproportionate to a POC/analyst tool; Streamlit delivers analyst value with minimal complexity.
- Streaming responses via SSE — deferred to v2; adds complexity to both FastAPI and Streamlit without blocking core functionality.

---

## Decision 5: Concurrent Conclusion Conflict Detection

**Decision**: The `POST /sessions/{session_id}/conclude` endpoint uses a Postgres `SELECT ... FOR UPDATE` lock on the `fraud_alerts` row. If the alert already has an `InvestigationConclusion` record (unique constraint on `alert_id`), the endpoint returns `HTTP 409 Conflict` with the prior conclusion's analyst and timestamp. The Streamlit UI surfaces this as an error banner before the analyst submits.

**Rationale**: Database-level locking is the only reliable way to prevent race conditions between concurrent sessions concluding the same alert. The unique constraint on `InvestigationConclusion.alert_id` acts as a hard guard; the `FOR UPDATE` lock ensures the constraint check and insert are atomic.

**Alternatives considered**:
- Optimistic locking (version column) — rejected; pessimistic locking is simpler to reason about for low-concurrency fraud analyst workflows.
- Application-level semaphore — rejected; not durable across pod restarts.

---

## Decision 6: PII Masking Strategy

**Decision**: PII masking is applied at the tool output boundary, before the LLM processes the data. A `mask_pii` utility function (regex-based) redacts: card numbers (PAN → last 4 digits), SSNs, and email addresses from tool output strings and dicts before they are returned to the LangGraph graph state. This ensures masked values also appear in the session transcript stored in the DB.

**Rationale**: Masking at the tool layer (not the LLM output layer) ensures the LLM never receives raw PII, reducing the risk of verbatim repetition in responses. It is simpler than post-processing LLM output and easier to audit.

**Alternatives considered**:
- Masking in the API response serialiser only — rejected; LLM would still process raw PII internally.
- Field-level encryption in Postgres — deferred; out of scope for v1.

---

## Decision 7: Session Inactivity Timeout

**Decision**: The existing `sla_worker.py` background task is extended to also sweep `investigation_sessions` for sessions with `last_active_at` older than `SESSION_TIMEOUT_MINUTES` (default 60, configurable). Stale sessions are marked `abandoned`. The Streamlit UI detects `abandoned` status on the next GET and shows a "Session expired — start a new session" message.

**Rationale**: Extending `sla_worker.py` avoids introducing a second background task, keeping the worker loop simple. The 60-minute timeout matches the spec assumption and is appropriate for an analyst workflow.

**Alternatives considered**:
- Per-session asyncio timeout — rejected; not durable across pod restarts.
- Redis TTL — rejected; no Redis in the current stack.

---

## Decision 8: Deployment — Investigation UI as a Separate Container

**Decision**: The Streamlit investigation UI is packaged as a separate Docker container using the same base image as the `fraud-alert-agent` but with only the `investigation_ui` optional dependencies installed (`streamlit`, `httpx`). It is deployed as a separate `Deployment` and `Service` in the `fraud-agent` namespace, pointing to the existing `fraud-alert-agent` service via cluster-internal DNS.

**Rationale**: Separating the Streamlit app into its own container allows independent scaling and restarts without affecting the backend API. The Streamlit process is stateless (session state lives in the backend), so horizontal scaling (if needed) is trivial.

**Alternatives considered**:
- Running Streamlit in the same container as FastAPI — rejected; Streamlit's blocking event loop conflicts with uvicorn's async event loop.
- A separate Git repository — rejected; keeping everything in the GitOps mono-repo maintains consistent CI/CD and Kustomize overlay management.
