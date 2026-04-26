# Tasks: Agentic Fraud Alert Orchestration

**Input**: Design documents from `specs/004-fraud-alert-agent/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Validation tasks are included for security-sensitive and performance-critical paths.
**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

**User input incorporated**: (1) "Add LangGraph trace logging for observability." — LangGraph trace logging is a first-class concern in Phase 4 (US2). T056 creates a dedicated `FraudGraphTraceCallback` handler capturing every node, tool, and LLM event; T057 wires it into `investigation_service.py` with optional LangSmith remote tracing. Prometheus per-node histograms and structlog trace events are in Phase 7 (T071–T072) but only exercise if T056–T057 are in place. (2) "Add LangGraph tracing with Grafana using an OpenTelemetry collector and Grafana Tempo to store the traces." — OTEL infrastructure (Tempo StatefulSet + OTel Collector Deployment) is in Phase 2 (T083–T090); `FraudGraphTraceCallback` is extended in Phase 4 (T091) to emit OTLP spans for every LangGraph node, tool call, and LLM invocation — each investigation becomes a root trace with structured child spans shipped through the OTel Collector to Tempo; Grafana Tempo datasource and "Fraud Alert Agent — LangGraph Traces" dashboard are provisioned in Phase 7 (T092–T093).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup

**Purpose**: Create the project skeleton and Flux directory layout before any code is written.

- [X] T001 Create src/fraud-alert-agent/ directory tree matching plan.md: app/agents/, app/api/, app/db/migrations/, app/services/, app/tools/, app/workers/, tests/contract/, tests/integration/, tests/unit/
- [X] T002 Create src/fraud-alert-agent/pyproject.toml with all dependencies: langgraph>=0.2, langgraph-checkpoint-postgres, langchain-ollama, langchain-core, fastapi>=0.111, uvicorn, pyiceberg[pyarrow,s3]==0.7.1, sqlalchemy>=2.0, asyncpg, alembic, httpx, pydantic-settings, prometheus-client, structlog, mlflow>=2.11, confluent-kafka>=2.3, aiokafka>=0.11; dev deps: pytest, pytest-asyncio, httpx
- [X] T003 [P] Create apps/base/ollama/ directory for Flux Ollama manifests
- [X] T004 [P] Create apps/base/fraud-alert-agent/ directory for Flux agent manifests
- [X] T005 [P] Create apps/minikube/ollama/ and apps/minikube/fraud-alert-agent/ Kustomize overlay directories

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Ollama GitOps deployment, Postgres, FastAPI skeleton, ORM foundation, Polaris REST catalog singleton, general-purpose Iceberg query tools, MLFlow client tools, Kafka producer/consumer tools, a new Flink Iceberg-to-Kafka publisher job, and shared LLM factory.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Ollama Flux Deployment (RTX 3070 — 8GB VRAM)

- [X] T006 Create apps/base/ollama/namespace.yaml — Kubernetes Namespace `ollama`
- [X] T007 Create apps/base/ollama/resources.yaml — Ollama Deployment (image: `ollama/ollama:latest`): `resources.limits: {nvidia.com/gpu: "1"}`, PVC `ollama-models` (10Gi) at `/root/.ollama`, `OLLAMA_KEEP_ALIVE=24h`, liveness probe `GET /api/tags` port 11434, ClusterIP Service port 11434
- [X] T008 Create apps/base/ollama/model-pull-job.yaml — Kubernetes Job `ollama-pull-llama3`: `ollama pull llama3.1:8b`, `initContainers` wait for Ollama, `restartPolicy: OnFailure`
- [X] T009 Create apps/base/ollama/kustomization.yaml — Kustomize base referencing namespace.yaml, resources.yaml, model-pull-job.yaml
- [X] T010 Create apps/minikube/ollama/kustomization.yaml — Kustomize overlay: `tolerations: [{key: "nvidia.com/gpu", operator: Exists, effect: NoSchedule}]`
- [X] T011 Add apps/minikube/ollama/ reference to apps/minikube/kustomization.yaml

### Postgres and Agent Manifests

- [X] T012 Create apps/base/fraud-alert-agent/namespace.yaml — Kubernetes Namespace `fraud-agent`
- [X] T013 Create apps/base/fraud-alert-agent/postgres.yaml — Postgres 15 StatefulSet + headless Service: PVC `postgres-data` (5Gi), env from secret `fraud-agent-secrets`, liveness probe `pg_isready`
- [X] T014 Create apps/base/fraud-alert-agent/configmap.yaml — ConfigMap `fraud-agent-config`: OLLAMA_BASE_URL, OLLAMA_MODEL=llama3.1:8b, ANALYSIS_TIMEOUT_SECONDS=30, FRAUD_THRESHOLD_CRITICAL=0.85, FRAUD_THRESHOLD_HIGH=0.70, FRAUD_THRESHOLD_MEDIUM=0.50, BLOCK_CONFIDENCE_THRESHOLD=0.85, ESCALATE_CONFIDENCE_THRESHOLD=0.90, ICEBERG_CATALOG_URI, ICEBERG_WAREHOUSE=fraud_warehouse, ICEBERG_INVESTIGATIONS_NAMESPACE=fraud, MINIO_ENDPOINT, MLFLOW_TRACKING_URI=http://mlflow.mlflow.svc.cluster.local:5000, MLFLOW_FRAUD_MODEL_NAME=fraud-score-xgboost, KAFKA_BOOTSTRAP_SERVERS=platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092, KAFKA_FRAUD_ALERTS_TOPIC=fraud-alert-events, KAFKA_FRAUD_NOTIFICATIONS_TOPIC=fraud-notifications, KAFKA_SCORED_TRANSACTIONS_TOPIC=scored-transactions, KAFKA_CONSUMER_GROUP_ID=fraud-alert-agent, LANGCHAIN_TRACING_V2=false, LANGCHAIN_PROJECT=fraud-alert-agent, LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
- [X] T015 Create apps/base/fraud-alert-agent/deployment.yaml — Deployment `fraud-alert-agent`: envFrom ConfigMap + Secret `fraud-agent-secrets` (DATABASE_URL, FRAUD_API_KEY, SLACK_WEBHOOK_URL, POLARIS_CREDENTIAL, AWS credentials, LANGCHAIN_API_KEY with `optional: true`), liveness/readiness `GET /healthz`, init container `alembic upgrade head`
- [X] T016 Create apps/base/fraud-alert-agent/service.yaml — ClusterIP Service `fraud-alert-agent` port 8000
- [X] T017 Create apps/base/fraud-alert-agent/kustomization.yaml — Kustomize base referencing all manifests
- [X] T018 Create apps/minikube/fraud-alert-agent/kustomization.yaml — Kustomize overlay for image tag and Minikube resource limits
- [X] T019 Add apps/minikube/fraud-alert-agent/ reference to apps/minikube/kustomization.yaml

### OpenTelemetry Collector and Grafana Tempo (Tracing Infrastructure)

- [X] T083 [P] Add opentelemetry-sdk>=1.24, opentelemetry-exporter-otlp-proto-grpc>=1.24, opentelemetry-instrumentation-fastapi>=0.45b0 to src/fraud-alert-agent/pyproject.toml dependencies list
- [X] T084 Create apps/base/fraud-alert-agent/tempo.yaml — Grafana Tempo in monolithic mode: ConfigMap `tempo-config` with tempo.yaml (server.http_listen_port=3200, distributor.receivers.otlp.protocols.grpc.endpoint=0.0.0.0:4317, storage.trace.backend=local path=/var/tempo, compactor.block_retention=72h, ingester.trace_idle_period=10s); StatefulSet `tempo` (grafana/tempo:2.4.1, volumeMount ConfigMap at /etc/tempo/tempo.yaml, PVC `tempo-data` 2Gi at /var/tempo); ClusterIP Service `tempo` ports 3200 (HTTP API for Grafana query) and 4317 (OTLP gRPC ingest from OTel Collector)
- [X] T085 Create apps/base/fraud-alert-agent/otel-collector.yaml — ConfigMap `otel-collector-config` with config.yaml (receivers: otlp grpc :4317 http :4318; processors: batch maxExportBatchSize=512; exporters: otlp/tempo endpoint=tempo.fraud-agent.svc.cluster.local:4317 tls.insecure=true; service.pipelines.traces: receivers[otlp] processors[batch] exporters[otlp/tempo]); Deployment `otel-collector` (otel/opentelemetry-collector-contrib:0.99.0, volumeMount ConfigMap at /etc/otelcol-contrib/config.yaml); ClusterIP Service `otel-collector` ports 4317 (gRPC OTLP from app) and 4318 (HTTP OTLP)
- [X] T086 Update apps/base/fraud-alert-agent/configmap.yaml — add OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.fraud-agent.svc.cluster.local:4317, OTEL_SERVICE_NAME=fraud-alert-agent, OTEL_TRACES_ENABLED=true
- [X] T087 Update apps/base/fraud-alert-agent/kustomization.yaml — add tempo.yaml and otel-collector.yaml to resources list
- [X] T088 [P] Add OTEL_EXPORTER_OTLP_ENDPOINT (str, default "http://otel-collector.fraud-agent.svc.cluster.local:4317"), OTEL_SERVICE_NAME (str, default "fraud-alert-agent"), OTEL_TRACES_ENABLED (bool, default True) to src/fraud-alert-agent/app/config.py Pydantic BaseSettings
- [X] T089 Create src/fraud-alert-agent/app/tracing.py — `setup_tracing(app: FastAPI) -> None`: if not settings.OTEL_TRACES_ENABLED return early; create `Resource({SERVICE_NAME: settings.OTEL_SERVICE_NAME, "deployment.environment": "minikube"})`, `OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)`, `BatchSpanProcessor(exporter)`, `TracerProvider(resource=resource, active_span_processor=processor)`; call `trace.set_tracer_provider(provider)` and `FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)`; export `get_tracer(name: str = "fraud-alert-agent") -> Tracer` returning `trace.get_tracer(name)`; export `shutdown_tracing()` calling `provider.force_flush(); provider.shutdown()`
- [X] T090 Update src/fraud-alert-agent/app/main.py — import and call `setup_tracing(app)` as the first statement in the lifespan startup block so the TracerProvider is registered before any instrumented code; call `shutdown_tracing()` in lifespan cleanup after workers stop

### FastAPI Application Foundation

- [X] T02- [X] T020 Create src/fraud-alert-agent/app/config.py — Pydantic BaseSettings: DATABASE_URL, OLLAMA_BASE_URL, OLLAMA_MODEL, ANALYSIS_TIMEOUT_SECONDS (int, default 30), FRAUD_API_KEY, SLACK_WEBHOOK_URL, FRAUD_THRESHOLD_CRITICAL/HIGH/MEDIUM, BLOCK_CONFIDENCE_THRESHOLD (float, default 0.85), ESCALATE_CONFIDENCE_THRESHOLD (float, default 0.90), ICEBERG_CATALOG_URI, ICEBERG_WAREHOUSE, ICEBERG_INVESTIGATIONS_NAMESPACE, POLARIS_CREDENTIAL, MINIO_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, MLFLOW_TRACKING_URI (default "http://mlflow.mlflow.svc.cluster.local:5000"), MLFLOW_FRAUD_MODEL_NAME (default "fraud-score-xgboost"), KAFKA_BOOTSTRAP_SERVERS (default "platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092"), KAFKA_FRAUD_ALERTS_TOPIC (default "fraud-alert-events"), KAFKA_FRAUD_NOTIFICATIONS_TOPIC (default "fraud-notifications"), KAFKA_SCORED_TRANSACTIONS_TOPIC (default "scored-transactions"), KAFKA_CONSUMER_GROUP_ID (default "fraud-alert-agent"), LANGCHAIN_TRACING_V2 (str, default "false"), LANGCHAIN_API_KEY (str, default ""), LANGCHAIN_PROJECT (str, default "fraud-alert-agent"), LANGCHAIN_ENDPOINT (str, default "https://api.smith.langchain.com")
- [X] T02- [X] T021 Create src/fraud-alert-agent/app/db/base.py — async SQLAlchemy engine using asyncpg, session factory (AsyncSessionLocal), Base declarative class
- [X] T02- [X] T022 Create src/fraud-alert-agent/app/db/models.py — SQLAlchemy ORM models for all 5 entities: FraudAlert (uq_fraud_alerts_transaction_id, composite index on status+severity, `recommended_action TEXT`, `final_action TEXT`), Investigation, InvestigationStep, DecisionEvent (no update/delete), AlertMonitorCursor (retained in schema for audit/fallback; not written by Kafka-based alert_monitor)
- [X] T02- [X] T023 Initialize Alembic in src/fraud-alert-agent/app/db/migrations/ — `alembic init`, configure DATABASE_URL, set target_metadata = Base.metadata, generate initial migration for all 5 ORM models
- [X] T02- [X] T024 Create src/fraud-alert-agent/app/api/deps.py — `verify_api_key` dependency; HTTPException 401 on mismatch
- [X] T02- [X] T025 Create src/fraud-alert-agent/app/main.py — FastAPI app with lifespan: startup creates DB engine + alembic upgrade head + starts alert_monitor and sla_worker; mounts /healthz, /metrics, /api/v1 routers

### Polaris REST Catalog (Shared Catalog Singleton)

- [X] T02- [X] T026 Create src/fraud-alert-agent/app/tools/iceberg_catalog.py — PyIceberg `RestCatalog` singleton: `uri=settings.ICEBERG_CATALOG_URI`, `credential=settings.POLARIS_CREDENTIAL`, `warehouse=settings.ICEBERG_WAREHOUSE`. `get_catalog() -> RestCatalog` with `@lru_cache(maxsize=1)`. `load_table(namespace: str, table_name: str) -> Table` with 3-attempt retry + structlog WARNING. `ensure_namespace(namespace)` helper for namespace creation. Used by all query tools and report_writer.

### General-Purpose Iceberg Query Tools (LangChain @tool — for LangGraph Agents)

- [X] T02- [X] T027 Create src/fraud-alert-agent/app/tools/iceberg_query_tool.py — Two LangChain tools backed by the Polaris `RestCatalog` that any LangGraph agent or node can use for ad-hoc Iceberg queries. (1) Define `IcebergQueryInput(BaseModel)` with fields: `namespace (str)`, `table_name (str)`, `row_filter (str | None)`, `selected_columns (list[str] | None)`, `limit (int, default 100, max 1000)`, `snapshot_id (int | None)`. Define `IcebergQueryResult(TypedDict)` with: `rows (list[dict])`, `row_count (int)`, `snapshot_id (int | None)`, `table (str)`, `columns (list[str])`, `error (str | None)`. (2) `@tool(args_schema=IcebergQueryInput) def query_iceberg_table(...)` — uses `iceberg_catalog.load_table(namespace, table_name)`, builds `table.scan(...)`, calls `scan.to_arrow()`, applies limit, converts to list[dict]; returns `IcebergQueryResult`; on exception returns result with `rows=[], error=str(exc)` and logs structlog WARNING (never logs credentials). (3) `@tool def list_iceberg_tables(namespace: str) -> list[str]` — calls `get_catalog().list_tables(namespace)` and returns table identifiers; on error returns `[]`. Both tools registered on compiled LangGraph graph. Domain helpers (T034–T036) delegate to `query_iceberg_table` internally.

### MLFlow Client Tools (LangChain @tool — for LangGraph Agents)

- [X] T02- [X] T028 Create src/fraud-alert-agent/app/tools/mlflow_tool.py — Two LangChain @tool functions backed by `MlflowClient`. (1) `MLFlowModelInput(BaseModel)`: `model_name (str)`. `@tool get_latest_model_version(model_name) -> dict` — calls `.get_latest_versions(model_name, stages=["Production","Staging","None"])`, selects highest version; returns `{model_name, version, stage, run_id, source, creation_timestamp, description}`; on error returns `{"error": str(exc), "model_name": model_name}` with structlog WARNING. (2) `MLFlowRunInput(BaseModel)`: `run_id (str)`. `@tool get_run_details(run_id) -> dict` — calls `.get_run(run_id)`; returns `{run_id, status, metrics, params, tags, start_time, end_time, artifact_uri}`; on error returns `{"error": str(exc), "run_id": run_id}`. Both registered on compiled LangGraph graph. `analysis_node` calls both to include model provenance in the LLaMA prompt.

### Kafka Producer/Consumer Tools (LangChain @tool + Consumer Factory — for LangGraph Agents and alert_monitor)

- [X] T02- [X] T029 Create src/fraud-alert-agent/app/tools/kafka_producer_tool.py — Three functions in one file serving both LangGraph tools and the alert_monitor consumer. (1) `@tool(args_schema=KafkaEventInput) def publish_kafka_event(topic, event_type, payload, key=None) -> dict` — `confluent_kafka.Producer` singleton; serializes `{"event_type": event_type, "timestamp": utcnow().isoformat(), "source": "fraud-alert-agent", "payload": payload}` as UTF-8 JSON; calls `producer.produce(...)` then `producer.flush(timeout=5.0)`; returns `{"topic": topic, "event_type": event_type, "delivered": True, "error": None}` on success; on failure returns `{"delivered": False, "error": str(exc)}` with structlog WARNING (non-fatal; never logs payload contents). (2) `@tool def list_kafka_topics() -> list[str]` — short-lived `AdminClient`; returns sorted topic names excluding `__` internals; on error returns `[]`. (3) `def create_scored_transactions_consumer() -> AIOKafkaConsumer` — returns a configured but NOT yet started `aiokafka.AIOKafkaConsumer(settings.KAFKA_SCORED_TRANSACTIONS_TOPIC, bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS, group_id=settings.KAFKA_CONSUMER_GROUP_ID, enable_auto_commit=False, value_deserializer=lambda m: json.loads(m.decode("utf-8")), auto_offset_reset="latest")` — exported utility (NOT a LangChain tool), called only by `alert_monitor`. (4) `@tool def read_recent_kafka_messages(topic: str, max_messages: int = 10, timeout_seconds: float = 5.0) -> list[dict]` — creates a short-lived `confluent_kafka.Consumer` (group_id="agent-inspector-{uuid4()}", auto_offset_reset="earliest"), polls up to `max_messages` messages with total timeout, returns list of deserialized value dicts; on exception returns `[{"error": str(exc)}]`. `publish_kafka_event`, `list_kafka_topics`, and `read_recent_kafka_messages` registered on compiled LangGraph graph.

### Flink Iceberg-to-Kafka Publisher (scored-transactions topic)

- [X] T030 Create `apps/base/flink-jobs/kafka-topic-scored-transactions.yaml` — Strimzi `KafkaTopic` resource (apiVersion: kafka.strimzi.io/v1beta2): `metadata.name=scored-transactions`, `metadata.namespace=kafka`, `metadata.labels["strimzi.io/cluster"]=platform-cluster`; `spec.partitions=3`, `spec.replicas=1`, `spec.config: {"retention.ms": "86400000", "cleanup.policy": "delete"}`. Then add `- kafka-topic-scored-transactions.yaml` to the `resources` list in `apps/base/flink-jobs/kustomization.yaml`.
- [X] T031 Create `apps/base/flink-jobs/flink_scored_kafka_publisher.sql` — New Flink SQL job that reads `transactions_scored` Iceberg (incremental streaming) and fans out to `scored-transactions` Kafka. Set `execution.runtime-mode = 'STREAMING'`. Re-use Polaris catalog definition (same `credential` / `warehouse` as `flink_streaming_job.sql`). Define Kafka sink: `CREATE TABLE scored_transactions_kafka (transaction_id STRING, user_id INT, amount DOUBLE, merchant STRING, fraud_probability DOUBLE, amount_velocity_5min DOUBLE, distance_from_home_km DOUBLE, ts TIMESTAMP(3), processing_time TIMESTAMP(3)) WITH ('connector'='kafka', 'topic'='scored-transactions', 'properties.bootstrap.servers'='platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092', 'format'='json', 'json.timestamp-format.standard'='ISO-8601')`. Then `INSERT INTO scored_transactions_kafka SELECT ... FROM polaris_catalog.default.transactions_scored`. Then add the new `FlinkDeployment fraud-score-kafka-publisher` to `apps/base/flink-jobs/resources.yaml` and the ConfigMap generator entry to `apps/base/flink-jobs/kustomization.yaml`.

### Shared LLM Factory (Analysis Agent Foundation)

- [X] T032 Create src/fraud-alert-agent/app/agents/llm.py — `get_llm() -> ChatOllama` with `@lru_cache(maxsize=1)`: `ChatOllama(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL, temperature=0.1, format="json")`. `get_llm_plain() -> ChatOllama` without `format="json"`. Imported only by `analysis_node.py`.

**Checkpoint**: Ollama deployed with llama3.1:8b; Postgres running; FastAPI starts; Polaris catalog ready; `query_iceberg_table` callable; MLflow returns model version; Flink `fraud-score-kafka-publisher` deployment running and publishing to `scored-transactions` topic; `create_scored_transactions_consumer()` connects to `scored-transactions` and receives messages; `publish_kafka_event("fraud-alert-events", "test", {...})` delivers without error. OTel Collector and Tempo running: `kubectl logs -n fraud-agent deploy/otel-collector | grep "Everything is ready"` shows no errors; `curl http://localhost:3200/ready` returns HTTP 200 via port-forward.

---

## Phase 3: User Story 1 — Automated Alert Triage and Investigation (Priority: P1) 🎯 MVP

**Goal**: Every transaction above the fraud threshold flows through a unified **7-node LangGraph multi-agent graph**. `alert_monitor` consumes from `scored-transactions` Kafka topic (event-driven, sub-5s latency) instead of polling Iceberg. Domain helpers (T034–T036) delegate to `query_iceberg_table` for Iceberg reads. `escalation_node` and `report_node` publish events to Kafka alongside Slack.

**Graph topology**:
```
START → supervisor_node
  CRITICAL/STANDARD → triage_node → data_query_node → analysis_node
                                   → recommendation_node → escalation_node → report_node → END
  MONITOR_ONLY      → triage_node → escalation_node → report_node → END
  FALSE_POSITIVE    → escalation_node → report_node → END
```

**Independent Test**: `fraud-score-enricher` writes a row to `transactions_scored` → Flink publisher emits to Kafka `scored-transactions` within ~2s → `alert_monitor` receives the Kafka message within 5s → within 60s: alert has explanation, evidence ≥ 3, final_action ∈ {block, notify, escalate}, `fraud.investigations` has a matching row, and `fraud-alert-events` has a matching event.

- [X] T033 [P] [US1] Create src/fraud-alert-agent/app/agents/state.py — `FraudInvestigationState(TypedDict)` — single shared state for all 7 nodes. Fields: `alert_id (str)`, `transaction_id (str)`, `user_id (int)`, `amount (float)`, `fraud_probability (float)`, `merchant (str | None)`, `route (str)`, `transaction_history (Annotated[list[dict], operator.add])`, `feature_values (dict | None)`, `pattern_stats (dict | None)`, `snapshot_ids (Annotated[dict, lambda a,b: {**a,**b}])`, `severity (str)`, `sla_deadline (str | None)`, `explanation (str)`, `evidence (list[dict])`, `recommended_action (str)`, `confidence (float | None)`, `final_action (str)`, `rule_matched (str)`, `iceberg_snapshot_id (int | None)`, `kafka_delivered (bool)`, `tool_errors (Annotated[list[str], operator.add])`, `error (str | None)`.
- [X] T034 [P] [US1] Create src/fraud-alert-agent/app/tools/transaction_history_tool.py — `fetch_transaction_history(user_id: int, snapshot_id: int | None = None) -> tuple[list[dict], int | None]`. Calls `query_iceberg_table(namespace="fraud", table_name="transactions", row_filter=f"user_id = {user_id}", selected_columns=["transaction_id","amount","merchant","event_time","fraud_probability"], limit=50, snapshot_id=snapshot_id)`. Sorts returned rows by `event_time` DESC. Returns `(result["rows"], result["snapshot_id"])`. On error returns `([], None)`.
- [X] T035 [P] [US1] Create src/fraud-alert-agent/app/tools/feature_context_tool.py — `fetch_feature_context(transaction_id: str, snapshot_id: int | None = None) -> tuple[dict | None, int | None]`. Calls `query_iceberg_table(namespace="fraud", table_name="transactions_scored", row_filter=f"transaction_id = '{transaction_id}'", limit=1, snapshot_id=snapshot_id)`. Returns `(result["rows"][0], result["snapshot_id"])` if non-empty, else `(None, None)`.
- [X] T036 [P] [US1] Create src/fraud-alert-agent/app/tools/pattern_lookup_tool.py — `fetch_pattern_stats(user_id: int) -> dict`. Calls `query_iceberg_table(namespace="fraud", table_name="transactions", row_filter=f"user_id = {user_id} AND event_time >= '{thirty_days_ago}'", limit=1000)`. Computes avg_amount, stddev_amount, transaction_count, avg_transactions_per_hour, max_single_amount, z_score via PyArrow. On error returns `{"error": "pattern_lookup_unavailable"}`.
- [X] T037 [US1] Create src/fraud-alert-agent/app/agents/data_query_node.py — LangGraph node using `asyncio.gather` to call `fetch_transaction_history`, `fetch_feature_context`, and `fetch_pattern_stats` concurrently (15s total timeout). Returns state patch with `transaction_history`, `feature_values`, `pattern_stats`, `snapshot_ids`, `tool_errors`.
- [X] T038 [US1] Create src/fraud-alert-agent/app/agents/supervisor_node.py — LangGraph node. Deterministic routing — no LLM. Maps `fraud_probability` to route using FRAUD_THRESHOLD_* settings. Returns `{"route": route_value}`. Logs (transaction_id, fraud_probability, route) at INFO.
- [X] T039 [US1] Create src/fraud-alert-agent/app/agents/triage_node.py — LangGraph node. Maps route to severity + computes sla_deadline. Returns `{"severity": ..., "sla_deadline": ...}`.
- [X] T040 [US1] Create src/fraud-alert-agent/app/agents/analysis_node.py — LangGraph node and **LLaMA reasoning agent**. Calls `get_llm()`. Before invoking LLaMA: calls `get_latest_model_version(settings.MLFLOW_FRAUD_MODEL_NAME)`, then `get_run_details(model_version["run_id"])` to surface training metrics (auc, precision, recall) for the reasoning prompt. System prompt: return JSON with `explanation` (2–3 sentences), `evidence` (≥3 ranked objects), `recommended_action` (block|review|monitor), `confidence` (0.0–1.0). `asyncio.wait_for(timeout=settings.ANALYSIS_TIMEOUT_SECONDS)`. Safe fallback on timeout/parse failure; model version errors non-fatal.
- [X] T041 [US1] Create src/fraud-alert-agent/app/agents/recommendation_node.py — LangGraph node. Rules: `recommended_action == "block"` AND `confidence >= BLOCK_CONFIDENCE_THRESHOLD` AND severity in (critical, high) → `final_action="block"`, `rule_matched="block_threshold"`; `severity == "critical"` OR `confidence >= ESCALATE_CONFIDENCE_THRESHOLD` OR `error` set → `final_action="escalate"`, `rule_matched="escalate_critical"`; default → `final_action="notify"`, `rule_matched="notify_default"`.
- [X] T042 [US1] Create src/fraud-alert-agent/app/agents/escalation_node.py — LangGraph node. Reads `state["final_action"]`: `block` → urgent Slack; `escalate` → supervisor Slack; `notify` → analyst Slack. MONITOR_ONLY → `final_action="notify"`. FALSE_POSITIVE → `final_action="notify"`. After Slack: calls `publish_kafka_event(settings.KAFKA_FRAUD_ALERTS_TOPIC, "escalation_triggered", {"alert_id": alert_id, "final_action": final_action, "severity": severity, "fraud_probability": fraud_probability}, key=alert_id)` — non-fatal. Returns state patch with `kafka_delivered`.
- [X] T043 [US1] Create src/fraud-alert-agent/app/services/report_writer.py — PyIceberg writer for `fraud.investigations` analytics table. Schema (20 fields): investigation_id, alert_id, transaction_id, user_id, amount, merchant, fraud_probability, route, severity, recommended_action, final_action, rule_matched, confidence, explanation, evidence_json, snapshot_ids_json, tool_errors_json, investigation_started_at, investigation_completed_at, report_written_at. Partition: `MonthTransform` on `investigation_completed_at`. `get_or_create_investigations_table()` with NoSuchTableError fallback to `create_table`. `write_investigation_report(state, investigation_id, started_at, completed_at) -> int | None`; non-fatal on error.
- [X] T044 [US1] Create src/fraud-alert-agent/app/agents/report_node.py — Terminal LangGraph node. Reads `investigation_id` and `started_at` from `config["configurable"]`. Calls `report_writer.write_investigation_report(...)`. Calls `publish_kafka_event(settings.KAFKA_FRAUD_NOTIFICATIONS_TOPIC, "investigation_completed", {"alert_id": ..., "final_action": ..., "iceberg_snapshot_id": snapshot_id, "investigation_id": investigation_id}, key=alert_id)` — non-fatal. Returns `{"iceberg_snapshot_id": snapshot_id, "kafka_delivered": kafka_result["delivered"]}`.
- [X] T045 [US1] Create src/fraud-alert-agent/app/agents/graph.py — LangGraph `StateGraph(FraudInvestigationState)` with `PostgresSaver` checkpoint. Wire all 7 nodes. Register `query_iceberg_table`, `list_iceberg_tables`, `get_latest_model_version`, `get_run_details`, `publish_kafka_event`, `list_kafka_topics`, and `read_recent_kafka_messages` tools on the graph (7 tools total). `PostgresSaver.setup()` on startup. Export `compiled_graph`.
- [X] T046 [US1] Create src/fraud-alert-agent/app/services/alert_service.py — async: create_alert (ON CONFLICT DO NOTHING), get_alert, update_alert_status, update_alert_actions (recommended_action + final_action), list_alerts (severity/status/time filters + pagination)
- [X] T047 [US1] Create src/fraud-alert-agent/app/services/investigation_service.py — `start_investigation(alert, initial_state)`: creates Investigation, passes investigation_id + started_at via `config["configurable"]`, calls `compiled_graph.ainvoke`; records InvestigationSteps: supervisor(0), data_query(1, snapshot_ids), analysis(2, LLaMA prompt+response + model_version), recommendation(3, final_action+rule_matched), escalation(4, kafka_delivered), report(5, iceberg_snapshot_id + kafka_delivered). Saves explanation → alert.summary, recommended_action, final_action.
- [X] T048 [US1] Create src/fraud-alert-agent/app/workers/alert_monitor.py — **Event-driven Kafka consumer** (replaces Iceberg polling). `async def run_alert_monitor()`: calls `create_scored_transactions_consumer()` from `kafka_producer_tool`, `await consumer.start()`, then `async for msg in consumer`: deserialize value dict; if `record["fraud_probability"] >= settings.FRAUD_THRESHOLD_MEDIUM`: call `alert_service.create_alert(...)`, build `FraudInvestigationState` from record fields, call `investigation_service.start_investigation(...)`; `await consumer.commit()` only after successful alert creation + investigation launch; on exception: log error, do NOT commit (message redelivered on pod restart); on `ConsumerStoppedError` (shutdown): break gracefully. `AlertMonitorCursor` table is NOT read/written — Kafka consumer group offset is the cursor.
- [X] T049 [US1] Create src/fraud-alert-agent/app/api/alerts.py — GET /api/v1/alerts (paginated, filterable) and GET /api/v1/alerts/{alert_id} (explanation, recommended_action, final_action); require verify_api_key
- [X] T050 [US1] Add /healthz route to src/fraud-alert-agent/app/main.py — checks Postgres, Ollama, Polaris via `list_iceberg_tables("fraud")`, MLflow via `get_latest_model_version(settings.MLFLOW_FRAUD_MODEL_NAME)`, Kafka producer via `list_kafka_topics()` (non-empty → ok), Kafka consumer via short-lived `AdminClient` call; returns `{status, postgres, ollama, polaris, mlflow, kafka_producer, kafka_consumer}` 200/503
- [X] T051 [US1] Validate security: unauthenticated → 401; `query_iceberg_table` tool never queries outside `fraud` namespace; POLARIS_CREDENTIAL not in error messages; MLflow credentials not logged; Kafka payload contents not logged; LANGCHAIN_API_KEY sourced from secret with `optional: true`; report_writer failure non-fatal; Kafka delivery failure non-fatal
- [X] T052 [US1] Create src/fraud-alert-agent/README.md — 7-node graph diagram, tool registry table (7 tools including read_recent_kafka_messages), node responsibility table, recommendation_node decision rules, Kafka topics table (scored-transactions → alert_monitor, fraud-alert-events ← escalation_node, fraud-notifications ← report_node), env vars, deploy steps

**Checkpoint**: `fraud-score-enricher` scores transaction → Flink publisher emits to `scored-transactions` → `alert_monitor` Kafka consumer receives within ~5s → 7 nodes execute → `fraud.investigations` row written → step 4 kafka_delivered=true; step 5 iceberg_snapshot_id and kafka_delivered both set.

---

## Phase 4: User Story 2 — Multi-Step Investigation Reasoning (Priority: P2)

**Goal**: 6-step audit trail (steps 0–5) persisted as InvestigationStep records. **LangGraph trace logging** (user input) instruments every node, tool, and LLM call with a dedicated callback handler, emitting structured log events and Prometheus per-node histograms. Optional LangSmith remote tracing added via config flag. Idempotency via Kafka consumer group offset. Timeout enforced.

**Independent Test**: 6 steps returned; step 2 output.model_version non-null; step 4 output.kafka_delivered=true; step 5 output.iceberg_snapshot_id non-null; duplicate Kafka message with same transaction_id blocked by ON CONFLICT DO NOTHING; timeout → timed_out. Trace log events appear in structured JSON for every node.

- [X] T053 [US2] Extend src/fraud-alert-agent/app/services/investigation_service.py — write all 6 node steps: supervisor(0), data_query(1, snapshot_ids), analysis(2, LLaMA prompt+response JSONB + model_version + model_stage + run_id), recommendation(3, final_action+rule_matched), escalation(4, final_action + kafka_delivered + kafka_topic), report(5, iceberg_snapshot_id + table + report_written_at + kafka_delivered + kafka_topic)
- [X] T054 [US2] Add idempotency guard to src/fraud-alert-agent/app/workers/alert_monitor.py — after Kafka commit: if `create_alert` returns None (ON CONFLICT), skip investigation launch (alert already exists — Kafka message is a duplicate); still commit offset
- [X] T055 [US2] Add 5-minute timeout in src/fraud-alert-agent/app/services/investigation_service.py — `asyncio.wait_for(timeout=300)`; on TimeoutError: investigation.status=timed_out, final_action="escalate", iceberg write skipped, Kafka skipped, DecisionEvent(actor="agent", action="escalate", reason="timeout")
- [X] T056 [US2] Create src/fraud-alert-agent/app/agents/trace_callbacks.py — **LangGraph trace logging for observability** (user input). `FraudGraphTraceCallback(BaseCallbackHandler)` from `langchain_core.callbacks.base`. Constructor: `__init__(self, alert_id: str)` — stores `self.alert_id`, `self._node_times: dict[UUID, float]`, `self._tool_times: dict[UUID, float]`, `self._llm_times: dict[UUID, float]`. Implement: `on_chain_start(serialized, inputs, *, run_id, ...)` — records `self._node_times[run_id] = time.monotonic()`, logs `{event: "node_start", node_name: serialized.get("name","unknown"), run_id: str(run_id), alert_id: self.alert_id}` at DEBUG; `on_chain_end(outputs, *, run_id, ...)` — computes `duration_ms`, logs `{event: "node_end", node_name, run_id, alert_id, duration_ms}` at INFO; `on_chain_error(error, *, run_id, ...)` — logs at ERROR with `error_type` and `error_message`; `on_tool_start(serialized, input_str, *, run_id, ...)` — records time, logs `{event: "tool_start", tool_name, run_id, alert_id}` at DEBUG — NEVER logs `input_str` (may contain query parameters or credentials); `on_tool_end(output, *, run_id, ...)` — logs `{event: "tool_end", tool_name, run_id, alert_id, duration_ms, output_length: len(str(output))}` at INFO — NEVER logs raw output; `on_tool_error` — logs at ERROR; `on_llm_start(serialized, prompts, *, run_id, ...)` — records time, logs `{event: "llm_start", model: serialized.get("id",[])[-1], run_id, alert_id}` at DEBUG — NEVER logs prompt text; `on_llm_end(response, *, run_id, ...)` — logs `{event: "llm_end", model, run_id, alert_id, duration_ms, prompt_tokens: response.llm_output.get("token_usage",{}).get("prompt_tokens"), completion_tokens: ...}` at INFO; `on_llm_error` — logs at ERROR with `error_type`.
- [X] T057 [US2] Wire `FraudGraphTraceCallback` into src/fraud-alert-agent/app/services/investigation_service.py: in `start_investigation` pass `config={"configurable": {"investigation_id": ..., "started_at": ...}, "callbacks": [FraudGraphTraceCallback(alert_id=str(alert.id))]}` — the local callback fires regardless of LangSmith setting. In `app/main.py` lifespan startup: if `settings.LANGCHAIN_TRACING_V2 == "true"` and `settings.LANGCHAIN_API_KEY` is non-empty, set `os.environ["LANGCHAIN_TRACING_V2"]`, `os.environ["LANGCHAIN_API_KEY"]`, `os.environ["LANGCHAIN_PROJECT"]`, `os.environ["LANGCHAIN_ENDPOINT"]` — LangChain then adds its own internal LangSmith callback automatically. LANGCHAIN_API_KEY pulled from secret `fraud-agent-secrets` key `langchain-api-key` with `optional: true` so absent secret leaves LangSmith disabled with no error.
- [X] T091 [US2] Extend src/fraud-alert-agent/app/agents/trace_callbacks.py — add OTEL span emission to `FraudGraphTraceCallback` (depends on T089 tracing.py). Import `get_tracer`, `trace`, `StatusCode`, `SpanKind` from opentelemetry. In `__init__`: `self._tracer = get_tracer("fraud-alert-agent.langgraph")`; start root span `self._root_span = self._tracer.start_span("investigation", kind=SpanKind.INTERNAL, attributes={"investigation.alert_id": self.alert_id})`; activate it `self._root_token = context.attach(trace.set_span_in_context(self._root_span))`; `self._span_stack: dict[UUID, Any] = {}`. In `on_chain_start`: `self._span_stack[run_id] = self._tracer.start_span(f"node.{serialized.get('name','unknown')}", attributes={"alert_id": self.alert_id})`. In `on_chain_end`: pop span, set `duration_ms` attribute, `StatusCode.OK`, call `span.end()`. In `on_chain_error`: pop span, `StatusCode.ERROR` with error message, `span.end()`. Same pattern in `on_tool_start`/`on_tool_end` (span name `tool.<name>`, attribute `output_length`) and `on_llm_start`/`on_llm_end` (span name `llm.ollama`, attributes `gen_ai.request.model`, `gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens`). Add `end_root_span(error: Exception | None = None)` method: if error set `StatusCode.ERROR` else `StatusCode.OK`; call `self._root_span.end()`; `context.detach(self._root_token)`. Call `callback.end_root_span()` in `investigation_service.start_investigation` after `compiled_graph.ainvoke` completes (in both success and exception paths).
- [X] T058 [US2] Create src/fraud-alert-agent/app/api/investigations.py — GET /api/v1/alerts/{alert_id}/investigation: 6 ordered steps; step 2 includes model_version and run_id; step 3 includes rule_matched; step 4 includes kafka_delivered and kafka_topic; step 5 includes iceberg_snapshot_id and kafka_delivered; require verify_api_key
- [X] T059 [US2] Wire GET /api/v1/alerts/{alert_id}/investigation router into src/fraud-alert-agent/app/main.py

**Checkpoint**: 6-step audit trail; step 2 shows model_version from MLflow; step 4 shows kafka_delivered for escalation; step 5 confirms Iceberg write and Kafka notification; duplicate transaction_id blocked. Structured `node_start`/`node_end`/`tool_start`/`tool_end`/`llm_start`/`llm_end` log events visible in JSON logs for every LangGraph trace event. OTEL spans visible in Grafana Tempo: port-forward Tempo (`kubectl port-forward -n fraud-agent svc/tempo 3200:3200`) and run `curl "http://localhost:3200/api/search?service.name=fraud-alert-agent"` — each completed investigation appears as a root trace with node/tool/LLM child spans.

---

## Phase 5: User Story 3 — Human-in-the-Loop Escalation and Feedback (Priority: P3)

**Goal**: final_action routes Slack notifications and Kafka events. Analysts approve/override. SLA worker publishes sla_breached Kafka events.

**Independent Test**: final_action=block → Slack #fraud-urgent + Kafka fraud-alert-events event; approve/override → resolved; sla_breach → sla_breached + Kafka event.

- [X] T060 [US3] Create src/fraud-alert-agent/app/services/notification_service.py — `send_slack_notification(alert, final_action, investigation)` via httpx: block → #fraud-urgent; escalate → #fraud-escalations; notify → #fraud-alerts; includes LLaMA explanation; no-op if SLACK_WEBHOOK_URL empty
- [X] T061 [US3] Extend src/fraud-alert-agent/app/agents/escalation_node.py — call notification_service async; update alert.summary with explanation
- [X] T062 [US3] Create src/fraud-alert-agent/app/api/decisions.py — POST /api/v1/alerts/{alert_id}/decisions (approve requires outcome; override requires reason); GET decisions list (append-only); both require verify_api_key
- [X] T063 [US3] Create src/fraud-alert-agent/app/services/sla_service.py — compute_sla_deadline (critical: +30min, high: +2h, medium: +8h); get_breached_alerts()
- [X] T064 [US3] Create src/fraud-alert-agent/app/workers/sla_worker.py — every 60s: get_breached_alerts → status=sla_breached, final_action="escalate", DecisionEvent(actor="sla_bot"), Slack escalation, `publish_kafka_event(settings.KAFKA_FRAUD_ALERTS_TOPIC, "sla_breached", {"alert_id": ..., "severity": ..., "sla_deadline": ...}, key=alert_id)` (non-fatal)
- [X] T065 [US3] Wire decisions router and sla_worker into src/fraud-alert-agent/app/main.py
- [X] T066 [US3] Validate security: unauthenticated POST /decisions → 401; override without reason → 400; DecisionEvent no DELETE/UPDATE; SLACK_WEBHOOK_URL not logged; Kafka payload contents not logged

**Checkpoint**: final_action routing to correct Slack channels and Kafka topics; approve/override recorded; sla_worker escalates via Slack + Kafka.

---

## Phase 6: User Story 4 — Alert Dashboard and Case Management (Priority: P4)

**Goal**: Filtering by final_action. Metrics include final_action_distribution, iceberg_write_success_rate, kafka_delivery_rate, kafka_consumer_lag, and mlflow_model_version_in_use.

**Independent Test**: Filter by final_action=block returns only block alerts; metrics include all five new fields.

- [X] T067 [US4] Extend src/fraud-alert-agent/app/api/alerts.py — add severity, status, final_action, from_time, to_time, page, page_size filters; return AlertListResponse
- [X] T068 [US4] Extend GET /api/v1/alerts/{alert_id} — include explanation, recommended_action, final_action, rule_matched, iceberg_snapshot_id (from step 5), snapshot_ids (from step 1), model_version (from step 2), kafka_delivered (from step 4)
- [X] T069 [US4] Create src/fraud-alert-agent/app/api/metrics_api.py — GET /api/v1/metrics?window_hours=24: alert_count, auto_resolution_rate, avg_time_to_decision_minutes, false_positive_rate, sla_breach_rate, route_distribution (%), final_action_distribution (block/notify/escalate %), iceberg_write_success_rate (% where iceberg_snapshot_id non-null), kafka_delivery_rate (% where kafka_delivered=true across escalation + report steps), kafka_consumer_lag (current consumer group lag on `scored-transactions` topic via AdminClient), mlflow_model_version_in_use (current Production version string from get_latest_model_version)
- [X] T070 [US4] Wire metrics router into src/fraud-alert-agent/app/main.py

**Checkpoint**: final_action filter; full alert detail with iceberg_snapshot_id, model_version, kafka_delivered; metrics include consumer lag and all delivery rates.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T071 [P] Add structlog JSON logging throughout app/ — supervisor_node (transaction_id, route), data_query_node (snapshot_ids, tool_errors), analysis_node (model, duration_ms, recommended_action, mlflow_model_version, mlflow_model_stage — no raw prompt at INFO), recommendation_node (final_action, rule_matched), escalation_node (final_action, kafka_delivered, kafka_topic), report_node (investigation_id, iceberg_snapshot_id, kafka_delivered, duration_ms), alert_monitor (topic, partition, offset, transaction_id, fraud_probability — no payload contents), iceberg_query_tool (namespace, table_name, row_count, snapshot_id, duration_ms — never log row contents or credentials), mlflow_tool (model_name, version, stage, duration_ms — never log auth), kafka_producer_tool (topic, event_type, delivered, duration_ms — never log payload or credentials)
- [X] T072 [P] Add Prometheus metrics — Counter `fraud_alerts_total` (severity, route), Histogram `analysis_node_duration_seconds` (model), Counter `final_actions_total` (final_action, rule_matched), Counter `iceberg_query_tool_calls_total` (namespace, table_name, status=success|error), Histogram `iceberg_query_tool_duration_seconds`, Counter `iceberg_writes_total` (table, status), Counter `sla_breaches_total`, Counter `mlflow_tool_calls_total` (tool, status), Histogram `mlflow_tool_duration_seconds`, Counter `kafka_producer_events_total` (topic, event_type, status=delivered|error), Histogram `kafka_producer_duration_seconds`, Counter `kafka_consumer_messages_total` (topic, status=processed|skipped|error), Gauge `kafka_consumer_lag` (topic, group_id), Histogram `investigation_node_duration_seconds` (node label — pairs with FraudGraphTraceCallback T056 events); expose GET /metrics
- [X] T073 Finalize src/fraud-alert-agent/Dockerfile — multi-stage: deps install; non-root uid=1000; EXPOSE 8000; CMD uvicorn
- [X] T074 Update src/fraud-alert-agent/README.md — 7-node graph diagram, 7-tool registry table, recommendation_node decision table, Kafka topics table (scored-transactions ← Flink publisher → alert_monitor; fraud-alert-events ← escalation_node; fraud-notifications ← report_node), Iceberg investigations schema, env vars, deploy steps, LangGraph trace logging section (FraudGraphTraceCallback fields, LangSmith opt-in via LANGCHAIN_TRACING_V2)
- [X] T075 Create docs/runbooks/fraud-alert-agent.md — (1) tune thresholds; (2) tune analysis_node prompt; (3) swap Ollama model; (4) replay investigation (delete Investigation + LangGraph checkpoint by thread_id=alert_id); (5) query fraud.investigations Iceberg; (6) compact fraud.investigations; (7) list Polaris tables; (8) rotate Polaris credential; (9) look up MLflow model version; (10) promote MLflow model to Production; (11) inspect Kafka topics (`list_kafka_topics()`); (12) check Kafka consumer lag on `scored-transactions`; (13) reset Kafka consumer group offset to re-process transactions; (14) debug failed Kafka delivery (check kafka_delivered in step 4/5); (15) restart Flink `fraud-score-kafka-publisher` if `scored-transactions` topic goes silent; (16) enable LangSmith tracing (set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY secret); (17) add Slack channel; (18) Postgres recovery
- [X] T076 Update docs/FRAUD_SCORE_ENRICHER.md — add downstream section: `fraud-score-enricher` writes to Iceberg `transactions_scored` → Flink `fraud-score-kafka-publisher` reads Iceberg (streaming) and publishes to `scored-transactions` Kafka topic → `alert_monitor` consumes from `scored-transactions` (event-driven, sub-5s latency) → 7-node LangGraph graph investigates → report_node writes `fraud.investigations`
- [X] T077 Update README.md — add Ollama (llama3.1:8b), fraud-alert-agent (7-node LangGraph, 7 registered tools, Kafka-driven alert_monitor, fraud.investigations table), Flink fraud-score-kafka-publisher job to Stack and Repository Layout
- [X] T078 Update `apps/base/synthetic-transaction-producer/main.py` and `apps/base/synthetic-transaction-producer/deployment.yaml` — add `POST /inject` (publishes to `transactions` topic with configurable fields) and `POST /inject/scored` (publishes directly to `scored-transactions` topic, bypassing ML pipeline — primary tool for triggering a fraud investigation in dev/testing). Move AIOKafkaProducer to `app["producer"]` so handlers can reach it; both inject handlers return HTTP 503 if producer not ready. Requires `_auth_ok`. Add `KAFKA_SCORED_TOPIC=scored-transactions` env entry in deployment.yaml.
- [X] T079 Run quickstart.md integration scenarios 1–6; additionally verify: Flink `fraud-score-kafka-publisher` running; `scored-transactions` topic has messages; `alert_monitor` consumer group lag is ≥ 0 and decreasing; step 2 output has model_version; step 4 output has kafka_delivered=true; step 5 output has iceberg_snapshot_id and kafka_delivered; `node_start`/`node_end` trace events visible in pod logs. **Inject test**: `curl -X POST http://localhost:8080/inject/scored -d '{"user_id": 99999, "amount": 8500.00, "fraud_probability": 0.95, "merchant": "Test Fraud Merchant", "distance_from_home_km": 450.0}'` → within ~60s alert appears at `GET /api/v1/alerts?status=open&severity=critical`, investigation completes with final_action=escalate, trace events logged per node.
- [X] T080 [P] Create docs/architecture.md — full end-to-end system architecture document with two Mermaid diagrams. **Diagram 1 — End-to-End System Flow** (`flowchart TD`): show all components in pipeline order: `synth-producer[Synthetic Transaction Producer\nPOST /inject & /inject/scored]` → `kafka-txns[(Kafka: transactions)]` → `flink-enricher[Flink: fraud-score-enricher\nXGBoost ModelScorerJob]` → `iceberg-scored[(Iceberg: transactions_scored\nPolaris catalog)]` → `flink-publisher[Flink: fraud-score-kafka-publisher\nstreaming SQL]` → `kafka-scored[(Kafka: scored-transactions\npartitions=3)]` → `alert-monitor[alert_monitor\nAIOKafkaConsumer\ngroup=fraud-alert-agent]` → `langgraph[LangGraph 7-Node Graph\nPostgresSaver checkpoint]`; from langgraph branch to: `postgres[(Postgres 15\nFraudAlert + Investigation\n+ InvestigationStep + DecisionEvent)]`, `iceberg-inv[(Iceberg: fraud.investigations\nMonthTransform partition)]`, `kafka-alerts[(Kafka: fraud-alert-events)]`, `kafka-notifs[(Kafka: fraud-notifications)]`, `slack[Slack\nWebhook]`; also show `mlflow[MLflow\nModel Registry]` and `ollama[Ollama\nllama3.1:8b]` feeding into `langgraph`; show `fastapi[FastAPI Service\n/api/v1 + /healthz + /metrics]` reading from `postgres` and served by `grafana[Grafana\nFraud Alert Dashboard]`. **Diagram 2 — LangGraph 7-Node Graph** (`flowchart TD`): show `START` → `supervisor_node{supervisor_node\nDeterministic routing}` with three conditional edges: `CRITICAL/STANDARD` → `triage_node[triage_node\nSeverity + SLA deadline]` → `data_query_node[data_query_node\nasyncio.gather:\ntransaction_history\nfeature_context\npattern_lookup]` → `analysis_node[analysis_node\nLLaMA 3.1:8b\nMLflow provenance\nevidence + recommendation]` → `recommendation_node[recommendation_node\nRule-based:\nblock/notify/escalate]` → `escalation_node`; `MONITOR_ONLY` → `triage_node` → `escalation_node`; `FALSE_POSITIVE` → `escalation_node[escalation_node\nSlack notification\nKafka: fraud-alert-events]` → `report_node[report_node\nIceberg: fraud.investigations\nKafka: fraud-notifications]` → `END`. Include a component table below each diagram (node name, responsibility, LLM/Iceberg/MLflow/Kafka usage). Add a Data Flow section describing each Kafka topic and Iceberg table. Reference quickstart.md for local dev commands.
- [X] T081 [P] Update root README.md — replace or extend the fraud-alert-agent section (T077 general entry) with three new sections: **(1) Usage Instructions**: local dev quickstart (`cd src/fraud-alert-agent`, `docker compose up -d postgres`, `pip install -e ".[dev]"`, `alembic upgrade head`, `uvicorn app.main:app --reload --port 8000`); Minikube deploy commands; curl examples for `GET /api/v1/alerts?severity=critical&status=open` and `POST /api/v1/alerts/{id}/decisions`; link to `quickstart.md` for full scenario list. **(2) Benefits**: bullet list — "80%+ of fraud alerts fully investigated before an analyst opens them", "P95 investigation time < 60 seconds end-to-end including Ollama inference", "Complete LangGraph trace log per investigation (node, tool, LLM events) for auditability and debugging", "Event-driven Kafka consumer (sub-5s alert lag) replaces polling", "LangSmith remote tracing opt-in via single env var for production debugging", "Iceberg fraud.investigations table enables SQL analytics over historical investigation data". **(3) End-to-End Demo**: numbered walkthrough — step 1: ensure Minikube running and port-forwards active (`kubectl port-forward svc/fraud-alert-agent -n fraud-agent 8000:8000 &`; `kubectl port-forward svc/synthetic-transaction-producer -n fraud-agent 8080:8080 &`); step 2: inject a high-probability scored transaction (`curl -X POST http://localhost:8080/inject/scored -H "Authorization: Bearer dev-key" -d '{"user_id": 99999, "amount": 8500.00, "fraud_probability": 0.95, "merchant": "Test Fraud Merchant", "distance_from_home_km": 450.0}'`); step 3: poll for the alert (`curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/alerts?severity=critical&status=open`); step 4: watch the investigation complete within ~60s (`curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/alerts/{ALERT_ID}/investigation`); step 5: approve or override (`curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/alerts/{ALERT_ID}/decisions -d '{"actor": "demo@example.com", "action": "approve", "outcome": "block"}'`); step 6: view trace logs (`kubectl logs -n fraud-agent deploy/fraud-alert-agent | grep node_end`). Add link to `docs/architecture.md` for diagrams.
- [X] T082 [P] Update src/fraud-alert-agent/README.md — add **Architecture** section with link to `docs/architecture.md` and inline summary of the 7-node graph topology; add **End-to-End Demo** section mirroring the root README demo steps but scoped to the service (port 8000 only, assumes alert_monitor is consuming from `scored-transactions`); add **LangGraph Trace Logging** section explaining `FraudGraphTraceCallback` events (`node_start`, `node_end`, `tool_start`, `tool_end`, `llm_start`, `llm_end`) and how to enable LangSmith (`LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` secret); add **Distributed Tracing (OTEL + Tempo)** section explaining the OTLP export path and how to explore traces in Grafana.
- [X] T092 [P] Create apps/base/monitoring/fraud-agent-tempo-datasource.yaml — Grafana datasource provisioning ConfigMap (namespace: monitoring, labels: grafana_datasource=1): datasources.yaml with name=Fraud-Agent-Tempo, type=tempo, url=http://tempo.fraud-agent.svc.cluster.local:3200, access=proxy, editable=false, jsonData: {tracesToLogsV2: {datasourceUid: loki, filterByTraceID: true}, nodeGraph: {enabled: true}, serviceMap: {datasourceUid: prometheus}, spanBar: {type: duration}}. Add fraud-agent-tempo-datasource.yaml to apps/base/monitoring/kustomization.yaml resources (create kustomization.yaml with apiVersion/kind/resources if it does not exist).
- [X] T093 [P] Create apps/base/monitoring/fraud-agent-trace-dashboard.yaml — Grafana dashboard provisioning ConfigMap (namespace: monitoring, labels: grafana_dashboard=1): JSON dashboard with title "Fraud Alert Agent — LangGraph Traces" containing six panels: (1) Tempo trace list "Recent Investigations" — search datasource=Fraud-Agent-Tempo service.name=fraud-alert-agent, show columns [traceID, duration, investigation.alert_id, rootName, status]; (2) Histogram "Node Execution Duration (p95)" — TraceQL `{span.name =~ "node\\..*"}` grouped by span.name; (3) Histogram "Tool Call Duration (p95)" — TraceQL `{span.name =~ "tool\\..*"}` grouped by span.name; (4) Stat "LLM Inference p95 Latency" — TraceQL `{span.name =~ "llm\\..*"}`; (5) Timeseries "Node Error Rate" — TraceQL `{status=error && span.name =~ "node\\..*"}` grouped by span.name; (6) Stat "Total Investigations (24h)" — count of root spans `{span.name="investigation"}`. Add fraud-agent-trace-dashboard.yaml to apps/base/monitoring/kustomization.yaml.
- [X] T094 Update specs/004-fraud-alert-agent/quickstart.md — add section "Grafana Trace Exploration" after the "Grafana Dashboard" section: (1) ensure Tempo is running (`kubectl get pod -n fraud-agent -l app=tempo`); (2) port-forward Grafana (`kubectl port-forward -n monitoring svc/grafana 3000:3000`); (3) navigate to Explore → select "Fraud-Agent-Tempo" datasource → enter TraceQL `{.investigation.alert_id="<alert-id>"}` to view full investigation trace with node/tool/LLM child spans and timings; (4) open the "Fraud Alert Agent — LangGraph Traces" dashboard for aggregated node latency histograms and error rates; (5) troubleshoot: `kubectl logs -n fraud-agent deploy/otel-collector | grep -E "(Everything is ready|error)"` and `kubectl logs -n fraud-agent statefulset/tempo | grep -E "(started|error)"`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (Foundational)**: Depends on Phase 1; Ollama (T006–T011), K8s manifests (T012–T019), OTEL infra (T083–T090 — T089 tracing.py must precede T090 main.py update; T083–T088 are [P] and can run alongside K8s manifest tasks), App (T020–T025), Catalog (T026) → Iceberg query tools (T027) → MLFlow tools (T028) → Kafka tools (T029) → KafkaTopic + Flink publisher (T030–T031) → LLM factory (T032)
- **Phase 3 (US1)**: Depends on Phase 2 — T027 blocks T034–T036; T028 blocks T040; T029 blocks T042, T044, T048; T031 (Flink publisher) blocks T048 (Kafka consumer needs messages in topic)
- **Phase 4 (US2)**: Depends on Phase 3 — T056 (trace_callback) requires compiled_graph (T045); T057 requires investigation_service (T047); T091 (OTEL spans in trace_callbacks.py) requires T089 (tracing.py) from Phase 2 and T056 from Phase 4 — run after T057
- **Phases 5–6**: Depend on Phase 3; independent of Phase 4
- **Phase 7**: Depends on desired stories complete; T072 Prometheus histograms pair with T056 trace callback; T080–T081 (docs/architecture.md) should come after T045 (graph.py); T082 and T094 should come last; T092–T093 (Grafana datasource + dashboard) require Phase 2 OTEL infra deployed and T091 spans active

### Parallel Opportunities Within Phase 2

```
Parallel group A (Ollama Flux):   T006–T009 → T010 → T011
Parallel group B (K8s Manifests): T012–T014 → T015, T016, T017, T018, T019
Parallel group C (App + Tools):   T020, T021 → T022 → T023, T024 → T025 → T026 → T027 → T028 → T029
Parallel group D (Flink Kafka):   T030, T031 (independent files — KafkaTopic manifest + Flink SQL/deployment)
Parallel group E (OTEL infra):    T083 (pyproject.toml), T084 (tempo.yaml), T085 (otel-collector.yaml), T086 (configmap), T087 (kustomization), T088 (config.py) → T089 (tracing.py) → T090 (main.py update)
                                  Groups A–E can start in parallel; T089 depends on T083 and T088
```

### Parallel Opportunities Within Phase 3 (US1)

```
Parallel group:  T033, T034, T035, T036 (state.py + 3 domain tools; T034–T036 depend on T027)
Parallel group:  T037, T038, T039 (data_query_node, supervisor_node, triage_node — independent)
Sequential:      T040 (analysis_node — depends on llm.py T032, state.py T033, mlflow_tool T028)
Sequential:      T041 (recommendation_node — depends on state fields from T040)
Sequential:      T042 (escalation_node — depends on final_action T041, kafka_producer_tool T029)
Sequential:      T043 (report_writer — depends on iceberg_catalog T026)
Sequential:      T044 (report_node — depends on report_writer T043, state.py T033, kafka_producer_tool T029)
Sequential:      T045 (graph.py — wires all 7 nodes + registers 7 tools; depends on T037–T044)
Parallel:        T046, T047 (alert_service, investigation_service — independent)
Sequential:      T048 (alert_monitor — depends on kafka_producer_tool T029 + compiled_graph T045 + Flink publisher T031)
Parallel:        T049, T050 (API + healthz — independent)
```

---

## Implementation Strategy

### MVP (US1 Only)

1. Phase 2: Ollama + Postgres + Polaris catalog + 3 tool types + Flink `fraud-score-kafka-publisher` running
2. Phase 3: All 7 LangGraph nodes wired; `alert_monitor` consuming from `scored-transactions`
3. **VALIDATE**: Flink publisher emits to `scored-transactions` → `alert_monitor` receives → all 7 nodes execute → `fraud.investigations` written → step 4 kafka_delivered=true; step 5 iceberg_snapshot_id non-null

### Incremental Delivery

1. Phase 1 + 2 → Infrastructure + all tool types + Flink Kafka publisher ready + OTel Collector + Tempo deployed
2. Phase 3 → MVP: event-driven alerts, all 7 nodes, Kafka fan-out, Iceberg report
3. Phase 4 → 6-step audit trail + **LangGraph trace logging** (structlog node/tool/llm events) + **OTEL span emission** (T091 — every investigation is a root trace with child spans shipped to Tempo) + LangSmith opt-in
4. Phase 5 → Slack + decisions + SLA (SLA worker Kafka events)
5. Phase 6 → Dashboard + metrics (consumer lag in /metrics)
6. Phase 7 → Production-ready: full observability stack (structlog + Prometheus histograms + **Grafana Tempo datasource and LangGraph trace dashboard** T092–T093), architecture diagrams, updated READMEs, quickstart Grafana trace exploration section (T094)

---

## Notes

### Data Flow: scored-transactions Pipeline

```
fraud-score-enricher (Flink ModelScorerJob)
  └─► Iceberg polaris_catalog.default.transactions_scored
         └─► Flink fraud-score-kafka-publisher (NEW — flink_scored_kafka_publisher.sql)
                └─► Kafka scored-transactions (partitions=3)
                       └─► alert_monitor (AIOKafkaConsumer, group=fraud-alert-agent)
                              └─► LangGraph 7-node investigation graph
                                     └─► FraudGraphTraceCallback (T056) — LangGraph trace logging
```

### LangGraph Trace Logging Architecture (T056–T057, T091)

The `FraudGraphTraceCallback` is the primary observability instrument for the LangGraph graph. It fires for every LangGraph node, tool call, and LLM invocation:

| LangChain callback | LangGraph trigger | Structured log event | OTEL span (T091) | Safe? |
|--------------------|-------------------|---------------------|------------------|-------|
| `on_chain_start` | Node starts | `node_start` (DEBUG) | `node.<name>` child span | ✓ Never logs inputs |
| `on_chain_end` | Node completes | `node_end` (INFO, duration_ms) | span end, StatusCode.OK | ✓ Never logs outputs |
| `on_chain_error` | Node errors | `node_error` (ERROR) | span end, StatusCode.ERROR | ✓ |
| `on_tool_start` | LangChain tool called | `tool_start` (DEBUG) | `tool.<name>` child span | ✓ Never logs input_str |
| `on_tool_end` | Tool returns | `tool_end` (INFO, output_length) | span end, output_length attr | ✓ Never logs raw output |
| `on_llm_start` | Ollama called | `llm_start` (DEBUG) | `llm.ollama` child span | ✓ Never logs prompt |
| `on_llm_end` | Ollama responds | `llm_end` (INFO, token counts) | span end, gen_ai token attrs | ✓ |

LangSmith remote tracing is opt-in: set `LANGCHAIN_TRACING_V2=true` and provide `LANGCHAIN_API_KEY` secret. Local `FraudGraphTraceCallback` logging (structlog) is always active. OTEL span emission (T091) is active when `OTEL_TRACES_ENABLED=true` (default).

### OpenTelemetry + Grafana Tempo Architecture (T083–T091, T092–T093)

```
fraud-alert-agent (FastAPI + LangGraph)
  │  FraudGraphTraceCallback.on_chain_start/end → OTEL span(node.<name>)
  │  FraudGraphTraceCallback.on_tool_start/end  → OTEL span(tool.<name>)
  │  FraudGraphTraceCallback.on_llm_start/end   → OTEL span(llm.ollama)
  │  Root span: investigation (alert_id attr)
  │
  ▼ OTLP gRPC (opentelemetry-exporter-otlp-proto-grpc)
otel-collector.fraud-agent.svc.cluster.local:4317 (OTel Collector)
  │  receivers: otlp / processors: batch / exporters: otlp/tempo
  ▼ OTLP gRPC (insecure)
tempo.fraud-agent.svc.cluster.local:4317 (Grafana Tempo — monolithic mode)
  │  storage: local /var/tempo / retention: 72h
  ▼ HTTP Tempo API :3200
Grafana (monitoring namespace)
  └─► Fraud-Agent-Tempo datasource → "Fraud Alert Agent — LangGraph Traces" dashboard
      • Recent investigations trace list
      • Node execution duration p95 histogram
      • Tool call duration p95 histogram
      • LLM inference latency stat
      • Node error rate timeseries
      • Total investigations count (24h)
```

| Component | Image | Port | Purpose |
|-----------|-------|------|---------|
| `otel-collector` | otel/opentelemetry-collector-contrib:0.99.0 | 4317 gRPC, 4318 HTTP | Receive OTLP from app, forward to Tempo |
| `tempo` | grafana/tempo:2.4.1 | 4317 (ingest), 3200 (API) | Trace storage and query backend |
| Grafana Tempo datasource | — | — | `Fraud-Agent-Tempo` provisioned in monitoring namespace |

### Tool Architecture

| Layer | File | Used By | Purpose |
|-------|------|---------|---------|
| Catalog singleton | `iceberg_catalog.py` (T026) | All tools + report_writer | Polaris `RestCatalog` connection |
| **Iceberg query tools** | `iceberg_query_tool.py` (T027) | Domain helpers, analysis_node | LangChain @tool for ad-hoc Iceberg queries |
| **MLFlow client tools** | `mlflow_tool.py` (T028) | analysis_node, healthz, metrics | LangChain @tool for model version + run details |
| **Kafka tools** | `kafka_producer_tool.py` (T029) | escalation_node, report_node, sla_worker, alert_monitor | LangChain @tool producer/inspector + `create_scored_transactions_consumer()` factory |
| Domain helpers | `*_tool.py` (T034–T036) | `data_query_node` | Specific queries wrapping `query_iceberg_table` |
| Report writer | `report_writer.py` (T043) | `report_node` | Write-only path to `fraud.investigations` |
| **Trace callback** | `trace_callbacks.py` (T056) | `investigation_service` | LangGraph trace logging — all node/tool/LLM events |

**7 LangGraph registered tools**: `query_iceberg_table`, `list_iceberg_tables`, `get_latest_model_version`, `get_run_details`, `publish_kafka_event`, `list_kafka_topics`, `read_recent_kafka_messages`

### 7-Node LangGraph Graph

| Node | LLM? | Iceberg? | MLflow? | Kafka? | Responsibility |
|------|------|----------|---------|--------|----------------|
| `supervisor_node` | No | No | No | No | Deterministic routing on fraud_probability |
| `triage_node` | No | No | No | No | Severity + SLA deadline |
| `data_query_node` | No | Read (via T034–T036) | No | No | Parallel evidence fetch |
| `analysis_node` | **Yes** (LLaMA 3.1:8b) | Read (if needed) | **Yes** | No | LLM reasoning with model provenance |
| `recommendation_node` | No | No | No | No | Rule-based: block/notify/escalate |
| `escalation_node` | No | No | No | **Yes** (fraud-alert-events) | Execute final_action + Slack + Kafka |
| `report_node` | No | **Write** | No | **Yes** (fraud-notifications) | Compile + persist report + Kafka event |

### Kafka Consumer Design (alert_monitor)

- **Library**: `aiokafka.AIOKafkaConsumer` (async, native asyncio)
- **Group ID**: `fraud-alert-agent` (single consumer group; single replica v1)
- **auto_offset_reset**: `latest` — on first deployment, process only new transactions
- **Commit strategy**: manual, after successful alert creation + investigation launch
- **Error handling**: exception → no commit → message redelivered after pod restart
- **Idempotency**: `ON CONFLICT DO NOTHING` on `fraud_alerts.transaction_id` deduplicates redelivered messages

### Recommendation Node Decision Rules

| Rule | Condition | final_action | rule_matched |
|------|-----------|-------------|--------------|
| Block threshold | recommended_action=block AND confidence ≥ 0.85 AND severity in (critical, high) | block | block_threshold |
| Escalate critical | severity=critical OR confidence ≥ 0.90 OR error set | escalate | escalate_critical |
| Default | All other cases | notify | notify_default |
