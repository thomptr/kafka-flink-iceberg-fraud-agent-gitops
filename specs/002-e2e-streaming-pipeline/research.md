# Research: E2E streaming pipeline (Kafka → Flink → Iceberg / Polaris)

**Feature**: `002-e2e-streaming-pipeline`  
**Date**: 2026-04-04

## 1. Flink → Iceberg via Polaris (REST catalog)

**Decision**: Use the **Apache Iceberg Flink connector** with **REST catalog** implementation pointing at **Apache Polaris** (`/api/catalog`), with **warehouse** and **OAuth client credentials** aligned to existing Polaris bootstrap secrets.

**Rationale**: Polaris is already deployed and validated with PyIceberg in-repo; Flink Iceberg supports REST catalog in current Iceberg releases. Keeps a single catalog authority for table metadata.

**Alternatives considered**:

- **Hive Metastore**: Extra operational burden; not needed when Polaris is present.
- **Hadoop catalog**: Does not match REST-first Polaris deployment.

## 2. Kafka consumer semantics

**Decision**: Flink Kafka consumer with **checkpointing** enabled; **Flink EXACTLY_ONCE** or **AT_LEAST_ONCE** depending on Iceberg sink transaction support and Kafka transactional producer settings—default lab path **AT_LEAST_ONCE** with idempotent writes to Iceberg where possible, document tradeoff.

**Rationale**: Single-broker Minikube Kafka is not a production HA setup; prioritizes working E2E over strongest guarantee in v1.

**Alternatives considered**:

- **EXACTLY_ONCE** end-to-end: desirable for production; may require additional Kafka txn + two-phase commit tuning—defer to hardening phase.

## 3. Synthetic transaction producer

**Decision**: A **small Java or Python producer** deployed as Kubernetes **Deployment** (or **Job** with restart policy) publishing JSON (or Avro with schema) to a dedicated topic, rate-limited for Minikube.

**Rationale**: Continuous load is required to validate streaming; keeping the producer in-cluster avoids laptop dependency.

**Alternatives considered**:

- **External load tool only** (e.g. from laptop): weaker for CI/GitOps reproducibility.

## 4. Feature engineering scope (v1)

**Decision**: **Basic** features: per-card **rolling window counts** (e.g. 10-minute), **amount z-score or bounds flag**, **merchant category rollup**, **time-of-day bucket**—all derivable in-state or with minimal keyed state.

**Rationale**: Matches fraud-adjacent analytics without requiring ML model serving in-path.

**Alternatives considered**:

- **Full ML inference in Flink**: out of scope for initial vertical slice.

## 5. Flink job packaging

**Decision**: Build a **custom Docker image** based on `flink:1.20.x-java17` (or official Flink image) that **adds** the application fat JAR under `/opt/flink/usrlib` or a known path; `FlinkDeployment` references **`local:///...`** `jarURI` and main class.

**Rationale**: Matches existing `FlinkDeployment` pattern in `apps/base/flink-jobs/resources.yaml`; GitOps-friendly if image tag is versioned.

**Alternatives considered**:

- **Remote HTTP jarURI**: simpler for spikes but weaker supply-chain posture for a GitOps repo.

## 6. Object storage credentials for Flink → Iceberg

**Decision**: Use **Kubernetes secrets** for **static MinIO credentials** (same pattern as Polaris storage credentials) for the Flink pods’ Hadoop/S3 FileSystem config **or** rely on **Iceberg + Polaris vended credentials** if operator supports token injection—**default to static keys from `polaris-storage-credentials`-compatible secret** mounted into Flink for simpler local parity with existing PyIceberg smoke test.

**Rationale**: Prior work documented Polaris + MinIO static path for clients; Flink S3A config is well-trodden.

**Alternatives considered**:

- **STS / IRSA**: not assumed on Minikube.
