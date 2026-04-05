# Tasks: End-to-end streaming pipeline (synthetic Kafka → Flink SQL → Iceberg / Polaris)

<<<<<<< HEAD
**Input**: Design documents from `/specs/002-e2e-streaming-pipeline/` plus implementation notes: Python synthetic producer (**aiokafka**, **faker**); **Flink SQL** from `apps/base/flink-jobs/flink_streaming_job.sql` in a **Flux-managed** `FlinkDeployment`; **checkpoints to MinIO**; **Prometheus** metrics in Flink spec; **Grafana** imports (**14161** Flink Job Metrics, **Kafka Overview** community dashboard) and **custom Iceberg write latency** panels from Flink metrics.
=======
**Input**: Design documents from `/specs/002-e2e-streaming-pipeline/` plus implementation notes: Python synthetic producer (**aiokafka**, **faker**); **Flink SQL** from `apps/base/flink-jobs/flink_streaming_job.sql` in a **Flux-managed** `FlinkDeployment`; **checkpoints to MinIO**; **Prometheus** metrics in Flink spec; **Grafana** imports (**14911** Flink Job Metrics, **Kafka Overview** community dashboard) and **custom Iceberg write latency** panels from Flink metrics.
>>>>>>> 3fc06d2 (Add synthetic trnasaction data producer.  Create Flink SQL Streaming job and Grafana dashboards)

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Validation via `make validate`, cluster smoke checks in `specs/002-e2e-streaming-pipeline/quickstart.md`, and manual Grafana/Prometheus verification where automation is not yet wired.

**Organization**: Phases follow user stories **US1** (ingestion), **US2** (Flink SQL processing), **US3** (Iceberg durability), **US4** (observability). Setup and foundational work block all stories.

**Path note**: If `SPECIFY_FEATURE` points at `001`, unset it or `export SPECIFY_FEATURE=002-e2e-streaming-pipeline` so helper scripts resolve this feature directory.

---

## Phase 1: Setup (shared structure & dependencies)

**Purpose**: Repository layout, Python deps, and doc pointers before cluster manifests.

- [X] T001 Add `apps/base/synthetic-transaction-producer/requirements.txt` pinning `aiokafka` and `faker` (with compatible version ranges) for the async producer.
- [X] T002 Add `apps/base/synthetic-transaction-producer/Dockerfile` multi-stage or slim image running `python -m synthetic_transaction_producer` (or `main.py`) as non-root.
- [X] T003 Add `apps/base/synthetic-transaction-producer/README.md` documenting env vars (`KAFKA_BOOTSTRAP_SERVERS`, `TOPIC`, `RATE`, secret refs), local `docker build` / `docker run`, and that secrets are not committed.
<<<<<<< HEAD
- [X] T004 [P] Add `docs/runbooks/grafana-dashboards.md` stub listing intended Grafana.com dashboard IDs (Flink **14161**, Kafka Overview TBD after import) and ownership for updates.
=======
- [X] T004 [P] Add `docs/runbooks/grafana-dashboards.md` stub listing intended Grafana.com dashboard IDs (Flink **14911**, Kafka Overview TBD after import) and ownership for updates.
>>>>>>> 3fc06d2 (Add synthetic trnasaction data producer.  Create Flink SQL Streaming job and Grafana dashboards)
- [X] T005 [P] Update root `README.md` with one paragraph linking to `specs/002-e2e-streaming-pipeline/quickstart.md` for the streaming pipeline validation path.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: Kafka topic, SQL/catalog alignment, checkpoint storage contract, and manifest wiring before workloads run.

**⚠️ No user-story implementation should merge until this phase completes.**

- [X] T006 Add Strimzi `KafkaTopic` (or documented `kafka-topic` creation) for topic `transactions` in `infrastructure/configs/base/kafka/` and include it from `infrastructure/configs/base/kafka/kustomization.yaml` (topic name MUST match `apps/base/flink-jobs/flink_streaming_job.sql`).
- [X] T007 Align `apps/base/flink-jobs/flink_streaming_job.sql` bootstrap server placeholder with cluster DNS (`platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092` or patch-driven value) and **remove committed plaintext Polaris credentials** — replace `credential = 'root:secret'` with pattern compatible with Kubernetes-injected env or documented `SET` via init wrapper (see T014–T016).
- [X] T008 Align `flink_streaming_job.sql` **Polaris** `warehouse` and **Iceberg** catalog identifiers with `specs/002-e2e-streaming-pipeline/contracts/flink-polaris-iceberg.md` and existing Polaris bootstrap (`quickstart_catalog` vs `polariscatalog` — pick one and update SQL + docs consistently).
- [X] T009 Define Flink **checkpoint** and **savepoint** base directory on **MinIO** via `s3://` URIs in `flinkConfiguration` (e.g. `state.checkpoints.dir`, `state.savepoints.dir`) and list required Hadoop/S3A or `fs.s3a` keys — document secret keys expected in `docs/runbooks/` (no secrets in Git).
- [X] T010 Add `apps/base/flink-jobs/flink-streaming-sql-configmap.yaml` (or equivalent) mounting `flink_streaming_job.sql` into the JobManager/TaskManager pods at a fixed path (e.g. `/opt/flink/sql/flink_streaming_job.sql`).
- [X] T011 Extend `apps/base/flink-jobs/kustomization.yaml` to include the ConfigMap and any new resources (producer, ServiceMonitor patches) without breaking existing `resources.yaml` order.
- [X] T012 Add `apps/minikube/synthetic-transaction-producer/kustomization.yaml` (or fold under `apps/minikube/`) referencing base manifests and Kafka bootstrap patch for Minikube.
- [X] T013 Update `apps/minikube/kustomization.yaml` to include the synthetic producer resource set alongside `flink-jobs`.

**Checkpoint**: Topic exists in manifests; SQL file is consistent with contracts; checkpoint dir strategy documented; ConfigMap path known.

---

## Phase 3: User Story 1 — Continuous event capture (Priority: P1) 🎯 MVP

**Goal**: Synthetic credit-card–like JSON events stream into Kafka topic `transactions` continuously.

**Independent Test**: Consumer lag increases with producer running; `kafka-console-consumer` shows JSON matching `specs/002-e2e-streaming-pipeline/contracts/kafka-transaction-event.md` (columns compatible with `flink_streaming_job.sql`).

### Implementation for User Story 1

- [X] T014 [US1] Implement async producer in `apps/base/synthetic-transaction-producer/main.py` using **aiokafka** + **faker** to emit JSON records with fields required by `flink_streaming_job.sql` (`transaction_id`, `user_id`, `amount`, `merchant`, `lat`, `lon`, `ts`).
- [X] T015 [US1] Add `apps/base/synthetic-transaction-producer/deployment.yaml` (Deployment + ServiceAccount if needed) in namespace `kafka` or `default` per trust model, with env from ConfigMap/Secret for bootstrap and topic.
- [X] T016 [US1] Add `NetworkPolicy` or namespace choice documentation if producer must reach Kafka brokers only (minimum: README note).
- [X] T017 [US1] Run `make validate` (or `scripts/validate.sh`) and fix kustomize/render errors for new manifests under `apps/`.

**Checkpoint**: Producer deploys; Kafka shows steady traffic; no Flink required for this story’s acceptance.

---

## Phase 4: User Story 2 — Flink SQL streaming job (Priority: P2)

**Goal**: **Flink SQL** job defined in `apps/base/flink-jobs/flink_streaming_job.sql` runs under **Flux-managed** `FlinkDeployment`, consuming Kafka and writing Iceberg via Polaris.

**Independent Test**: Flink UI / `kubectl logs` shows SQL job running; Iceberg table receives rows (verified in US3).

### Implementation for User Story 2

- [X] T018 [US2] Add `apps/base/flink-jobs/Dockerfile` (or `jobs/flink-sql-image/Dockerfile`) extending `flink:1.20.x-java17` with **Iceberg** + **Kafka** SQL connector JARs on the classpath and copy `flink_streaming_job.sql` into the image at a fixed path.
- [X] T019 [US2] Replace `apps/base/flink-jobs/resources.yaml` `FlinkDeployment.spec.job.jarURI` / entry strategy with a **SQL execution** strategy compatible with **Flink Kubernetes Operator** 1.14.x in-repo: e.g. `job` spec invoking `sql-client.sh embedded -f /opt/flink/sql/flink_streaming_job.sql`, or **FlinkSessionJob** / operator-supported SQL fields — document chosen pattern in `apps/base/flink-jobs/README.md`.
- [X] T020 [US2] Patch `apps/minikube/flink-jobs/kustomization.yaml` to set `KAFKA_BOOTSTRAP_SERVERS` and any Polaris/MinIO-related env vars for Minikube overlays.
- [X] T021 [US2] Register **Flink custom metrics** hook for **Iceberg sink latency** (e.g. `Histogram` around commit / `TwoPhaseCommitSink` callback) in the SQL execution path or via a thin Java wrapper if SQL-only cannot register metrics — if wrapper required, add minimal `jobs/` module and document.
- [X] T022 [US2] Expose custom Iceberg latency metric name(s) matching Prometheus scrape (e.g. `flink_taskmanager_job_task_operator_iceberg_commit_latency_ms` — final name documented in `docs/runbooks/grafana-dashboards.md`).

**Checkpoint**: Flink job runs SQL pipeline; metrics artifact exists for Iceberg latency (even if US4 wires scraping).

---

## Phase 5: User Story 3 — Durable Iceberg results & checkpoints (Priority: P2)

**Goal**: Checkpoints and Iceberg commits land on **MinIO**; data survives restarts.

**Independent Test**: After `kubectl delete pod` on TaskManager, job recovers from checkpoint; Iceberg files present in MinIO bucket; `scripts/verify_polaris_pyiceberg.py` or SQL query shows new rows.

### Implementation for User Story 3

- [X] T023 [US3] Apply **checkpoint** and **state backend** settings in `FlinkDeployment.spec.flinkConfiguration` for S3/MinIO (`fs.s3a.endpoint`, `fs.s3a.path.style.access`, credentials via `env` from Kubernetes secrets mounted into JM/TM).
- [X] T024 [US3] Verify Iceberg catalog in SQL uses REST URI reachable from `flink-system` pods (`http://polaris.polaris:8181/api/catalog` or service DNS from `contracts/flink-polaris-iceberg.md`).
- [X] T025 [US3] Update `specs/002-e2e-streaming-pipeline/quickstart.md` with step-by-step validation (producer on, Flink running, query Iceberg / MinIO object list).

**Checkpoint**: End-to-end data path durable and documented.

---

## Phase 6: User Story 4 — Prometheus metrics & Grafana (Priority: P3)

<<<<<<< HEAD
**Goal**: **Prometheus** scrapes Flink; **Grafana** shows Flink **14161**, Kafka overview, and **Iceberg write latency** panels.
=======
**Goal**: **Prometheus** scrapes Flink; **Grafana** shows Flink **14911**, Kafka overview, and **Iceberg write latency** panels.
>>>>>>> 3fc06d2 (Add synthetic trnasaction data producer.  Create Flink SQL Streaming job and Grafana dashboards)

**Independent Test**: Prometheus targets `UP` for Flink metrics port; Grafana dashboards render; custom panel queries Iceberg latency metric from T021–T022.

### Implementation for User Story 4

- [X] T026 [US4] Add `FlinkDeployment.spec.flinkConfiguration` entries enabling **PrometheusReporter** (e.g. `metrics.reporter.prom.class`, `metrics.reporter.prom.port`) and matching **container port** on JM/TM via `podTemplate` in `apps/base/flink-jobs/resources.yaml`.
- [X] T027 [US4] Add `Service` or `PodMonitor`/`ServiceMonitor` CR in `infrastructure/controllers/base/monitoring/` (or `apps/base/flink-jobs/`) so **kube-prometheus-stack** scrapes Flink metrics (namespace `monitoring` selector alignment with existing Prometheus Helm values).
<<<<<<< HEAD
- [X] T028 [US4] Import Grafana dashboard **14161** (“Flink Job Metrics”) via Grafana provisioning ConfigMap or Helm values under `infrastructure/controllers/base/monitoring/` (as supported by kube-prometheus-stack sidecar pattern).
=======
- [X] T028 [US4] Import Grafana dashboard **14911** (“Flink Job Metrics”) via Grafana provisioning ConfigMap or Helm values under `infrastructure/controllers/base/monitoring/` (as supported by kube-prometheus-stack sidecar pattern).
>>>>>>> 3fc06d2 (Add synthetic trnasaction data producer.  Create Flink SQL Streaming job and Grafana dashboards)
- [X] T029 [US4] Import a **Kafka Overview** dashboard from Grafana.com (search “Kafka Overview” / Strimzi exporter; record final dashboard UID/ID in `docs/runbooks/grafana-dashboards.md`).
- [X] T030 [US4] Add Grafana dashboard JSON patch or new panel row for **Iceberg write latency** using Prometheus queries against metrics from T021–T022 (save JSON under `docs/runbooks/` or `infrastructure/.../grafana-dashboards/` if repo pattern allows).
- [X] T031 [US4] Document alert rules (optional) for high Iceberg commit latency or failed checkpoints in `docs/runbooks/` — link to PrometheusRule if added.

**Checkpoint**: Operators can triage pipeline health from Grafana; Flink and Kafka visible.

---

## Phase 7: Polish & cross-cutting

- [X] T032 [P] Update `specs/001-fluxcd-gitops-repo/quickstart.md` with a cross-link to `specs/002-e2e-streaming-pipeline/quickstart.md` for the streaming validation path (per DI-002).
- [X] T033 [P] Update `docs/runbooks/bootstrap.md` if new secrets or namespaces are required for producer/Flink MinIO checkpoints.
- [ ] T034 Run full `specs/002-e2e-streaming-pipeline/quickstart.md` on a clean Minikube profile and fix gaps.
- [X] T035 [P] Security review: no plaintext credentials in `flink_streaming_job.sql` or producer env examples in Git; sample values clearly fake.

---

## Dependencies & execution order

### Phase dependencies

- **Phase 1** → **Phase 2** → **Phases 3–6** (US1–US4) → **Phase 7**.
- **US2** depends on **US1** Kafka topic traffic (can use console producer for early Flink testing, but acceptance needs synthetic producer).
- **US3** depends on **US2** running.
- **US4** depends on **US2** metrics (T021–T022) for Iceberg panels.

### User story dependencies

| Story | Depends on |
|-------|------------|
| US1 | Phase 2 (topic) |
| US2 | Phase 2 + US1 (realistic load optional for dev) |
| US3 | US2 |
| US4 | US2 (metrics) |

### Parallel opportunities

- **T004** and **T005** parallel with **T001–T003** (different files).
- **T014** (producer code) can start after **T006–T007** while **T018–T019** (Flink image) proceed in parallel if staffed separately.
- **T028** and **T029** (Grafana imports) parallel after Prometheus scrape works (**T026–T027**).

---

## Parallel example: after Phase 2

```bash
# Track A: producer
# Implement T014–T016 (US1)

# Track B: Flink SQL image + FlinkDeployment
# Implement T018–T022 (US2)

# Track C: docs
# T004, T005, T032
```

---

## Implementation strategy

### MVP (minimum shippable)

1. Complete **Phase 1–2**.
2. **US1** (T014–T017): producer + topic + traffic.
3. **US2** (T018–T022): Flink SQL job running (Iceberg sink working).
4. Stop and demo; add US3–US4 for durability proof and ops dashboards.

### Suggested MVP scope

- **US1** + **US2** + **US3** checkpoint validation = full “e2e” demo.
- **US4** can follow in a second PR if time-boxed.

---

## Task summary

| Phase | Task IDs | Count |
|-------|----------|-------|
| Setup | T001–T005 | 5 |
| Foundational | T006–T013 | 8 |
| US1 | T014–T017 | 4 |
| US2 | T018–T022 | 5 |
| US3 | T023–T025 | 3 |
| US4 | T026–T031 | 6 |
| Polish | T032–T035 | 4 |
| **Total** | **T001–T035** | **35** |

---

## Notes

- **Flink SQL in FlinkDeployment**: Operator version in `infrastructure/controllers/base/flink-operator/resources.yaml` may require **FlinkSessionJob** or a **custom image entrypoint**; T019 must match the supported CRD fields for this chart version.
- **Kafka Overview** dashboard: Grafana.com has several; pick one compatible with **JMX exporter** / **kafka-exporter** metrics your cluster exposes; document the import URL/ID in `docs/runbooks/grafana-dashboards.md`.
- **Iceberg write latency**: May require a small **Java** shim if pure SQL cannot register custom Flink `MetricGroup` — T021 allows that escape hatch.
