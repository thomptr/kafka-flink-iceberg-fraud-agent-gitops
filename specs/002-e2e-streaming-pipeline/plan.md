# Implementation Plan: End-to-end streaming pipeline (Kafka → Flink → Iceberg via Polaris)

**Branch**: `002-e2e-streaming-pipeline` | **Date**: 2026-04-04 | **Spec**: [`spec.md`](./spec.md)  
**Input**: Synthetic credit-card transactions continuously produced into Kafka. A Flink streaming job consumes them, performs basic feature engineering, and writes enriched records to an Iceberg table through the Polaris REST catalog. The Flink job runs as a Kubernetes-native `FlinkDeployment` managed by the Flink Kubernetes Operator.

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Deliver a **continuous fraud-analytics pipeline** on the existing GitOps platform: **Strimzi Kafka** ingests **synthetic credit-card transaction** events; a **Flink** streaming application (packaged as a job artifact and run via **`FlinkDeployment`**) applies **basic feature engineering** (rolling aggregates, derived fields, normalization) and **commits enriched rows** to **Apache Iceberg** using the **Apache Polaris REST catalog** and **MinIO** as object storage. The workload is **declarative in Git** (`apps/` + overlays), reconciled by **Flux**, and operated with **metrics/logs** aligned to the repository constitution.

## Technical Context

**Language/Version**: Java 17 (aligned with Flink 1.18 image baseline) for the streaming job; Kubernetes YAML (FlinkDeployment, KafkaTopic, secrets, Kustomize patches); optional Bash/Python for synthetic producers and smoke tests  
**Primary Dependencies**: Apache Flink 1.18, Flink Kubernetes Operator (existing HelmRelease), Strimzi Kafka operator and `Kafka` CR, `flink-connector-kafka`, Iceberg Flink runtime + `flink-connector-files` / Iceberg sink for Polaris REST catalog, Apache Polaris (in-cluster), MinIO S3 API  
**Storage**: Iceberg tables on MinIO (`s3://…` warehouse paths); Kafka topics for input (and optionally DLQ); Flink checkpoints to compatible filesystem (config TBD in implementation—often S3/MinIO or cluster FS)  
**Testing**: `make validate` / kubeconform for manifests; local Minikube integration test: produce sample events → observe Flink checkpoints → query Iceberg via engine of record (e.g. Spark SQL, Trino, or existing PyIceberg smoke patterns)  
**Target Platform**: Kubernetes (Minikube overlay first), Linux containers  
**Project Type**: GitOps monorepo — platform controllers in `infrastructure/`, workloads in `apps/`  
**Performance Goals**: Steady-state end-to-end latency (Kafka event time → Iceberg commit) **P95 &lt; 5 minutes** under lab load (tunable); Flink **checkpoint interval** default 60s–300s; Kafka consumer lag **&lt; 10k messages** sustained under nominal synthetic rate (e.g. **100–1000 events/sec** lab envelope)  
**Constraints**: No plaintext secrets in Git; Polaris/MinIO credentials via Kubernetes secrets; Flink job must tolerate single-replica Kafka/ZK and ephemeral storage in local profile  
**Scale/Scope**: Single Minikube path for v1; one primary input topic and one Iceberg table (or clearly versioned namespace); synthetic producer as a **Deployment** or **CronJob** in `apps/` (not a full payment gateway)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Security by Default**: PASS. Kafka and Flink use cluster-internal listeners and service accounts; Polaris and MinIO credentials are mounted from **existing secret patterns** (`polaris-storage-credentials`, `polaris-bootstrap-credentials`, MinIO root material); no anonymous admin. Catalog REST uses OAuth client credentials as already documented for Polaris.
- **Production-Grade Engineering**: PASS. Changes are **Flux-managed** with `kustomize build` validation; Flink **upgradeMode** and savepoint policy documented; rollback = **git revert + reconcile**. Job image build/version pinned in Git.
- **README-Driven Documentation**: PASS. Update **root `README.md`** pointer, **`specs/001-fluxcd-gitops-repo/quickstart.md`** or add **`specs/002-e2e-streaming-pipeline/quickstart.md`**, and **`docs/runbooks/`** for Flink savepoints, lag triage, and Iceberg/Polaris failure modes.
- **Performance Is a Feature**: PASS. Targets above + validation via metrics (Flink **numRecordsOut**, Kafka **consumer lag**, Iceberg **commit rate**) and documented soak procedure.
- **Observable and Operable Systems**: PASS. Flink Operator **REST/metrics**, Kafka **Strimzi metrics**, Polaris/MinIO health; alerts on **consumer lag**, **checkpoint failures**, **job FAILED** state.

**Post-Design Re-check**: PASS. `research.md`, `data-model.md`, `quickstart.md`, and `contracts/` define schemas, catalog settings, and operational validation without unresolved NEEDS CLARIFICATION.

## Project Structure

### Documentation (this feature)

```text
specs/002-e2e-streaming-pipeline/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── kafka-transaction-event.md
│   └── flink-polaris-iceberg.md
└── tasks.md   # produced by /speckit.tasks (not this command)
```

### Source Code (repository root)

```text
apps/
├── base/
│   └── flink-jobs/              # FlinkDeployment, SA/RBAC — extend/replace sample job
└── minikube/
    └── flink-jobs/              # Kafka bootstrap env, resource patches, image overrides

infrastructure/
├── configs/
│   └── base/kafka/              # Optional: KafkaTopic for synthetic tx topic (or Strimzi TO)
│   └── ...
└── controllers/base/            # Existing Strimzi, Flink Operator, Polaris, MinIO

jobs/                            # (recommended) Java/Gradle or Maven project for Flink job JAR
└── fraud-stream-to-iceberg/
    ├── pom.xml
    └── src/main/java/...

scripts/                         # Optional: kafka-console-producer wrapper, smoke tests
```

**Structure Decision**: Keep **GitOps layout** from `001`: Flux entry under `clusters/minikube`, shared **bases** under `apps/base`, environment patches under `apps/minikube`. Add a **`jobs/`** (or `src/flink/`) tree for the **Flink application source** and CI build that produces the **image or fat JAR URI** referenced by `FlinkDeployment.spec.job.jarURI` (or `job` stanza pointing to an image that embeds the artifact). Prefer **immutable image** + `jarURI` from container path over fetching unsigned HTTP artifacts.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | — | — |

## Delivery Phases (implementation outline)

1. **Topic & contracts**: Declare Kafka topic for synthetic transactions; publish **`contracts/`** as source of truth for JSON/Avro payload.
2. **Synthetic load**: Add lightweight producer workload (same schema) to exercise the pipe continuously in lab.
3. **Flink job**: Implement Flink DataStream job: Kafka source → feature engineering → Iceberg sink (Polaris catalog); configure **checkpointing** and **exactly-once** semantics where supported by connectors.
4. **GitOps**: Replace placeholder `TopSpeedWindowing.jar` **FlinkDeployment** with fraud pipeline job; wire env (bootstrap servers, catalog URI, warehouse, credentials via secret refs).
5. **Verify**: Run **`quickstart.md`** validation; document dashboards and alerts.
