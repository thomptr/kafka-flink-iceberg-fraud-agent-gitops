# Data Model: Agentic Fraud Alert Orchestration

**Branch**: `004-fraud-alert-agent` | **Date**: 2026-04-25

All entities are persisted in Postgres. Migrations are managed by Alembic.
The LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) are
created automatically by `langgraph-checkpoint-postgres` and are not documented here.

---

## Entity: FraudAlert

Primary record created when a scored transaction crosses the fraud threshold.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | PK, default gen_random_uuid() | |
| `transaction_id` | TEXT | NOT NULL, UNIQUE | Source: `transactions_scored.transaction_id` |
| `user_id` | INTEGER | NOT NULL | Source: `transactions_scored.user_id` |
| `amount` | NUMERIC(12,2) | NOT NULL | |
| `merchant` | TEXT | | |
| `fraud_probability` | NUMERIC(5,4) | NOT NULL | Range 0.0–1.0 |
| `severity` | TEXT | NOT NULL | Enum: `critical`, `high`, `medium`, `low` |
| `status` | TEXT | NOT NULL, default `open` | Enum: `open`, `in_review`, `resolved`, `escalated`, `sla_breached` |
| `recommended_action` | TEXT | | Enum: `block`, `review`, `monitor`; set after investigation |
| `summary` | TEXT | | Human-readable investigation summary; set after investigation |
| `sla_deadline` | TIMESTAMPTZ | NOT NULL | Created_at + severity-based offset (Critical: 30 min) |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default now() | Updated on any status/field change |
| `investigation_id` | UUID | FK → Investigation(id), nullable | Null until investigation starts |

**Indexes**: `idx_fraud_alerts_status_severity` on `(status, severity)`; `idx_fraud_alerts_created_at` on `created_at DESC`  
**Unique constraint**: `uq_fraud_alerts_transaction_id` on `transaction_id` (idempotency guard)

**Severity thresholds** (configurable via env var `FRAUD_THRESHOLD_*`):
- `critical`: `fraud_probability >= 0.85`
- `high`: `0.70 <= fraud_probability < 0.85`
- `medium`: `0.50 <= fraud_probability < 0.70`
- `low`: `fraud_probability < 0.50` (not currently alerted; reserved for future use)

**SLA offsets by severity**:
- `critical`: 30 minutes
- `high`: 2 hours
- `medium`: 8 hours

---

## Entity: Investigation

The agent's structured work product for a given alert. One investigation per alert.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | PK, default gen_random_uuid() | Also used as LangGraph `thread_id` |
| `alert_id` | UUID | NOT NULL, UNIQUE, FK → FraudAlert(id) | One investigation per alert |
| `status` | TEXT | NOT NULL, default `pending` | Enum: `pending`, `running`, `completed`, `timed_out`, `error` |
| `evidence` | JSONB | | Array of EvidenceItem objects (see below) |
| `confidence` | NUMERIC(5,4) | | Agent's self-reported confidence in recommendation (0.0–1.0) |
| `reasoning` | TEXT | | Full LLM reasoning chain (concatenated node outputs) |
| `started_at` | TIMESTAMPTZ | | Set when first node executes |
| `completed_at` | TIMESTAMPTZ | | Set when graph reaches END node |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | |

**EvidenceItem** (JSONB array element):
```json
{
  "rank": 1,
  "type": "transaction_history | pattern_deviation | feature_value | rule_match",
  "description": "User made 8 transactions in the last 5 minutes (avg: 1.2/hour)",
  "weight": "high | medium | low"
}
```

---

## Entity: InvestigationStep

Ordered audit trail of every tool call and node execution within an investigation.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | PK, default gen_random_uuid() | |
| `investigation_id` | UUID | NOT NULL, FK → Investigation(id) | |
| `step_order` | INTEGER | NOT NULL | 1-based sequential position in the graph |
| `node_name` | TEXT | NOT NULL | LangGraph node name (e.g., `triage_node`, `investigation_node`) |
| `tool_name` | TEXT | | Populated when step is a tool call (e.g., `transaction_history_tool`) |
| `input` | JSONB | | Serialised tool/node input |
| `output` | JSONB | | Serialised tool/node output |
| `duration_ms` | INTEGER | | Wall-clock duration of this step |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | |

**Index**: `idx_investigation_steps_investigation_id` on `(investigation_id, step_order)`

---

## Entity: DecisionEvent

Append-only record of every human or automated decision against an alert.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | PK, default gen_random_uuid() | |
| `alert_id` | UUID | NOT NULL, FK → FraudAlert(id) | |
| `actor` | TEXT | NOT NULL | Analyst identifier, `"agent"`, or `"sla_bot"` |
| `action` | TEXT | NOT NULL | Enum: `approve`, `override`, `escalate`, `reassign` |
| `outcome` | TEXT | | Final outcome value (e.g., `"block"`, `"monitor"`, `"false_positive"`) |
| `reason` | TEXT | | Free-text reason (required for `override`) |
| `created_at` | TIMESTAMPTZ | NOT NULL, default now() | Immutable; no updates allowed |

**Index**: `idx_decision_events_alert_id` on `(alert_id, created_at)`  
**Constraint**: No UPDATE or DELETE routes are exposed on this table.

---

## Entity: AlertMonitorCursor

Tracks the last-processed Iceberg snapshot to enable exactly-once alert creation.

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PK, default 1 | Singleton row |
| `last_snapshot_id` | BIGINT | | Last Iceberg snapshot ID processed from `transactions_scored` |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default now() | |

---

## Entity Relationships

```
FraudAlert (1) ──────────── (0..1) Investigation
     │                                    │
     │                           (1) ─── (*) InvestigationStep
     │
     └───────────────────────── (*) DecisionEvent
```

---

## State Transitions

### FraudAlert.status

```
open
 │
 ├──[agent investigation completes]──► open  (stays open, awaiting human for Critical/High)
 ├──[analyst opens alert]────────────► in_review
 ├──[analyst approves/overrides]─────► resolved
 ├──[SLA deadline exceeded]──────────► sla_breached → escalated
 └──[supervisor resolves]────────────► resolved
```

### Investigation.status

```
pending → running → completed
                 └→ timed_out   (investigation ran > 5 minutes)
                 └→ error       (unhandled exception; alert routed to human)
```
