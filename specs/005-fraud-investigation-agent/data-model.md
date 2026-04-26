# Data Model: Fraud Investigation Agent

**Feature**: 005-fraud-investigation-agent  
**Date**: 2026-04-26

---

## New Entities

### InvestigationSession

Represents an interactive investigation session between a fraud analyst and the LangGraph agent for a specific fraud alert.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Session identifier; also used as LangGraph `thread_id` |
| `alert_id` | UUID | FK → `fraud_alerts.id`, NOT NULL, indexed | The fraud alert being investigated |
| `analyst_id` | VARCHAR(255) | NOT NULL | Identity of the analyst who opened the session (from auth context) |
| `status` | VARCHAR(20) | NOT NULL, default `active` | Session lifecycle state |
| `created_at` | TIMESTAMP WITH TZ | NOT NULL, default `now()` | Session creation time |
| `updated_at` | TIMESTAMP WITH TZ | NOT NULL, default `now()` | Last modification time |
| `last_active_at` | TIMESTAMP WITH TZ | NOT NULL, default `now()` | Last turn submitted; used for inactivity timeout |

**Status values**: `active`, `concluded`, `abandoned`

**Validation rules**:
- `status` must be one of the three values above
- `analyst_id` must be non-empty
- `alert_id` must reference an existing `FraudAlert`

**State transitions**:
```
active → concluded  (analyst submits conclusion)
active → abandoned  (inactivity timeout via sla_worker sweep)
concluded → active  (not allowed; concluded sessions are read-only)
```

**Indexes**: `(alert_id)`, `(analyst_id, status)`, `(last_active_at)` for timeout sweep

---

### SessionTurn

A single exchange within an investigation session: the analyst's input and the agent's response.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Turn identifier |
| `session_id` | UUID | FK → `investigation_sessions.id`, NOT NULL, indexed | Parent session |
| `turn_number` | INTEGER | NOT NULL | Sequential position within the session (1-based) |
| `analyst_input` | TEXT | NOT NULL | The analyst's question or message |
| `agent_response` | TEXT | NOT NULL | The agent's grounded response |
| `tool_calls` | JSONB | nullable | List of tool names invoked during this turn (e.g., `["transaction_history_tool", "pattern_lookup_tool"]`) |
| `created_at` | TIMESTAMP WITH TZ | NOT NULL, default `now()` | Turn creation time |

**Validation rules**:
- `(session_id, turn_number)` unique constraint — prevents duplicate turns
- `turn_number` must be positive
- `analyst_input` and `agent_response` must be non-empty

**Indexes**: `(session_id, turn_number)` unique, `(session_id)`

---

### InvestigationConclusion

The analyst's recorded outcome for an investigation session.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `id` | UUID | PK | Conclusion identifier |
| `session_id` | UUID | FK → `investigation_sessions.id`, NOT NULL | The session that produced this conclusion |
| `alert_id` | UUID | FK → `fraud_alerts.id`, NOT NULL, UNIQUE | The alert resolved; unique enforces one conclusion per alert |
| `outcome` | VARCHAR(30) | NOT NULL | Analyst's determination |
| `notes` | TEXT | nullable | Free-text analyst notes |
| `analyst_id` | VARCHAR(255) | NOT NULL | Identity of the analyst who submitted the conclusion |
| `created_at` | TIMESTAMP WITH TZ | NOT NULL, default `now()` | Submission time |

**Outcome values**: `confirmed_fraud`, `false_positive`, `escalate`

**Validation rules**:
- `outcome` must be one of the three values above
- `alert_id` is unique — only one conclusion per alert (enforced at DB level; concurrent submissions return `HTTP 409`)
- `analyst_id` must match the session's `analyst_id`

**Indexes**: `(alert_id)` unique, `(session_id)`

---

## Relationships

```
FraudAlert (existing)
├── InvestigationSession (1:many — multiple analysts may investigate; one per analyst typical)
│   ├── SessionTurn (1:many — ordered sequence of Q&A exchanges)
│   └── InvestigationConclusion (1:1 via alert_id unique constraint)
└── Investigation (existing — automated triage, from 004)
```

---

## Impact on Existing Entities

No changes to existing tables. The three new tables are additive. The existing `FraudAlert` receives no new columns; the link to conclusions is via `InvestigationConclusion.alert_id`.

The existing `DecisionEvent` table (used for approve/override actions in the 004 flow) remains unchanged. When an analyst submits an `InvestigationConclusion`, the existing decisions endpoint (`POST /api/v1/alerts/{id}/decisions`) is also called to update the alert status in the `fraud_alerts` table and record the decision event — maintaining backward compatibility with the 004 SLA enforcement and status tracking.

---

## LangGraph Checkpoint Interaction

Each `InvestigationSession.id` (UUID) is used as the LangGraph `thread_id` for the session graph. The `langgraph_checkpoints` Postgres table (managed by `langgraph-checkpoint-postgres`) stores the `MessagesState` for each thread. Session transcript data lives in two places:

- **`langgraph_checkpoints`**: Full message graph state including intermediate tool call messages (used for graph resume after pod restart)
- **`session_turns`**: Human-readable turn pairs (analyst input + agent response) for the investigation UI and audit trail

The `session_turns` table is populated by the API layer after each successful `graph.ainvoke()` call; it is the authoritative source for the UI and the audit log.

---

## Alembic Migration

New migration: `add_investigation_sessions_tables`

```sql
-- investigation_sessions
CREATE TABLE investigation_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES fraud_alerts(id),
    analyst_id VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_investigation_sessions_alert_id ON investigation_sessions(alert_id);
CREATE INDEX ix_investigation_sessions_analyst_status ON investigation_sessions(analyst_id, status);
CREATE INDEX ix_investigation_sessions_last_active ON investigation_sessions(last_active_at);

-- session_turns
CREATE TABLE session_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES investigation_sessions(id),
    turn_number INTEGER NOT NULL,
    analyst_input TEXT NOT NULL,
    agent_response TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_number)
);
CREATE INDEX ix_session_turns_session_id ON session_turns(session_id);

-- investigation_conclusions
CREATE TABLE investigation_conclusions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES investigation_sessions(id),
    alert_id UUID NOT NULL UNIQUE REFERENCES fraud_alerts(id),
    outcome VARCHAR(30) NOT NULL,
    notes TEXT,
    analyst_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_investigation_conclusions_session_id ON investigation_conclusions(session_id);
```
