# Feature Specification: MLOps Layer on Iceberg/MinIO Lakehouse

**Feature Branch**: `003-mlops-lakehouse`  
**Created**: 2026-04-21  
**Status**: Draft  
**Input**: User description: "I want to build a working MLOps layer on top of the Iceberg/MinIO lakehouse using KubeFlow and MlFlow."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Train and Track a Fraud Detection Model (Priority: P1)

A data scientist registers a new model training run, trains a fraud detection model using data stored in the lakehouse, and tracks the experiment — including parameters, metrics, and the resulting model artifact — so that results are reproducible and comparable.

**Why this priority**: This is the core value of the MLOps layer. Without the ability to train models on lakehouse data and track experiments, no downstream workflow (registration, deployment, monitoring) is possible.

**Independent Test**: A data scientist can launch a training run, observe it in the experiment tracking UI, and retrieve run artifacts. This alone validates the foundational pipeline.

**Acceptance Scenarios**:

1. **Given** a data scientist has access to the ML platform, **When** they submit a training job pointing at a lakehouse dataset, **Then** the job runs to completion and a new experiment run record is created with parameters, metrics, and artifacts.
2. **Given** two training runs with different hyperparameters, **When** the data scientist views the experiment tracker, **Then** both runs are listed with their respective metrics and artifacts for side-by-side comparison.
3. **Given** a training job that encounters an error, **When** the job fails, **Then** the failure is recorded in the experiment tracker with an error message and the data scientist is notified.

---

### User Story 2 - Register and Version a Trained Model (Priority: P2)

A data scientist promotes a completed training run to the model registry, assigns a version, and documents the model's intended use, so that the team has a single source of truth for production-ready models.

**Why this priority**: Model versioning is the handoff point between experimentation and deployment. Without a registry, teams cannot reliably promote or roll back models.

**Independent Test**: A trained model artifact can be registered with a version number and stage label (e.g., Staging, Production) and retrieved by version via the registry UI or API.

**Acceptance Scenarios**:

1. **Given** a completed training run, **When** the data scientist registers the model artifact, **Then** a new versioned entry appears in the model registry with metadata (run ID, creation date, author).
2. **Given** a registered model version, **When** a reviewer transitions it to the Production stage, **Then** the registry reflects the updated stage and an audit log entry is created.
3. **Given** a model in the Production stage, **When** a newer version is promoted, **Then** the previous version is automatically transitioned to Archived.

---

### User Story 3 - Deploy a Registered Model for Inference (Priority: P3)

An ML engineer deploys a registered model version to a serving endpoint, so that downstream applications (e.g., the fraud detection agent) can call it for real-time or batch inference.

**Why this priority**: Deployment closes the loop from training to production value. It depends on Stories 1 and 2 but is the step that delivers business impact.

**Independent Test**: A registered model can be deployed to an endpoint, and a test inference request returns a valid prediction within an acceptable latency threshold.

**Acceptance Scenarios**:

1. **Given** a model version in the Production stage, **When** an ML engineer triggers a deployment, **Then** a serving endpoint becomes available and returns predictions for valid input payloads.
2. **Given** a deployed model endpoint, **When** the fraud detection agent sends a transaction payload, **Then** the endpoint returns a fraud probability score within 500 milliseconds.
3. **Given** a deployed model, **When** a new Production version is promoted, **Then** the serving endpoint can be updated to the new version with zero downtime.

---

### User Story 4 - Monitor Model Performance in Production (Priority: P4)

An ML engineer or data scientist monitors the deployed model's prediction quality and data drift over time, so that model degradation is detected before it causes business harm.

**Why this priority**: Without monitoring, model quality silently degrades. This story ensures the MLOps layer provides operational visibility post-deployment.

**Independent Test**: A dashboard shows prediction distribution and data drift metrics for a deployed model over a configurable time window.

**Acceptance Scenarios**:

1. **Given** a deployed model receiving inference requests, **When** the data scientist views the monitoring dashboard, **Then** they see prediction volume, score distributions, and drift indicators updated at least hourly.
2. **Given** input feature distributions drifting beyond a configured threshold, **When** drift is detected, **Then** an alert is raised and the responsible team is notified.
3. **Given** a period with no inference traffic, **When** the data scientist views the dashboard, **Then** the absence of traffic is clearly indicated rather than showing stale data.

---

### Edge Cases

- What happens when a training job is submitted but the lakehouse dataset does not exist or is inaccessible?
- How does the system handle a training job that exceeds the configured resource limits (CPU, memory, GPU)?
- What happens when model registry storage is at capacity or unavailable during artifact upload?
- How does the system behave when a serving endpoint is overloaded beyond its concurrency limits?
- What happens if a model is deployed but the underlying lakehouse data schema has changed since training?
- How does the system handle authentication failure when a pipeline component attempts to access lakehouse data?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Data scientists MUST be able to submit model training jobs that read training data directly from the lakehouse without manual data export.
- **FR-002**: The system MUST capture and persist experiment metadata for every training run, including input parameters, evaluation metrics, and output artifact locations.
- **FR-003**: Data scientists MUST be able to compare metrics across multiple runs within the same experiment via a visual interface.
- **FR-004**: The system MUST provide a model registry where trained model artifacts can be registered, versioned, and assigned lifecycle stages (e.g., Staging, Production, Archived).
- **FR-005**: Users MUST be able to transition a model version between lifecycle stages and the system MUST record the actor, timestamp, and prior stage for each transition.
- **FR-006**: ML engineers MUST be able to deploy a registered model version to a serving endpoint without writing custom deployment scripts.
- **FR-007**: Deployed model endpoints MUST return predictions for valid input payloads within 500 milliseconds under normal load.
- **FR-008**: The system MUST expose model performance metrics and data drift indicators for deployed models via a monitoring interface updated at least hourly.
- **FR-009**: The system MUST alert the responsible team when monitored drift metrics exceed configured thresholds.
- **FR-010**: Pipeline and serving components MUST authenticate to lakehouse storage using short-lived credentials — no long-lived static secrets embedded in job definitions.
- **FR-011**: The system MUST support re-training workflows that automatically trigger when new lakehouse data meets a configured volume or time threshold.

### Security & Access Considerations *(mandatory)*

- **SA-001**: Access to experiment tracking, model registry, and serving endpoints MUST be controlled by role-based access — at minimum distinguishing between read-only viewers, data scientists (run/register), and ML engineers (deploy/promote).
- **SA-002**: All components that access the lakehouse MUST use short-lived, scoped credentials; no static access keys may be embedded in pipeline definitions or container images.
- **SA-003**: Model artifacts stored in the lakehouse MUST be accessible only to authenticated users with the appropriate registry permissions; artifacts MUST NOT be publicly readable.
- **SA-004**: All model lifecycle stage transitions (Staging → Production → Archived) MUST be logged with actor identity and timestamp to support audit requirements.

### Documentation Impact *(mandatory)*

- **DI-001**: `README.md` (project root) MUST be updated to document the MLOps layer components, access URLs, and quickstart instructions for data scientists and ML engineers.
- **DI-002**: A new `docs/mlops-runbook.md` MUST be created covering: how to submit a training job, register a model, deploy to an endpoint, and interpret monitoring dashboards.
- **DI-003**: `docs/architecture.md` (or equivalent) MUST be updated to reflect the MLOps layer's position in the overall lakehouse architecture.

### Key Entities *(include if feature involves data)*

- **Experiment**: A named grouping of related training runs sharing a common objective (e.g., "fraud-detection-v2"). Contains one or more runs.
- **Run**: A single training execution within an experiment. Records parameters, metrics, tags, start/end time, status, and artifact locations.
- **Model Artifact**: The serialized, versioned output of a training run stored in the lakehouse. Referenced by registry entries.
- **Model Version**: A registered entry in the model registry pointing to a specific artifact. Has a stage (Staging, Production, Archived) and lineage back to its originating run.
- **Serving Endpoint**: A deployed runtime that loads a model version and exposes an inference API. Has a status (active, updating, failed) and routes traffic to a specific model version.
- **Drift Report**: A time-windowed summary of input feature distributions and prediction distributions for a deployed endpoint, used to detect model degradation.
- **Pipeline**: A directed acyclic graph of steps (data prep → train → evaluate → register) that automates the model development workflow end-to-end.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A data scientist can go from raw lakehouse data to a registered, versioned model artifact in under 30 minutes without manual data preparation steps.
- **SC-002**: All training run metadata (parameters, metrics, artifacts) is captured automatically — zero manual logging required for standard metrics.
- **SC-003**: A registered model can be deployed to a serving endpoint in under 10 minutes from the model registry UI.
- **SC-004**: Deployed endpoints serve inference requests with p95 latency under 500 milliseconds under a load of at least 50 concurrent requests.
- **SC-005**: Model performance dashboards reflect inference activity within 1 hour of requests being processed.
- **SC-006**: When data drift exceeds configured thresholds, an alert is raised and delivered to the responsible team within 15 minutes.
- **SC-007**: 100% of model lifecycle stage transitions are recorded in the audit log with actor identity and timestamp.
- **SC-008**: The end-to-end re-training pipeline (data ingestion through model registration) can complete without human intervention when triggered automatically.

## Assumptions

- The existing Iceberg/MinIO lakehouse is operational and contains labelled fraud transaction data suitable for training.
- Users (data scientists, ML engineers) are internal team members — external user authentication is out of scope.
- The Kubernetes cluster backing the system has sufficient compute resources (CPU, memory) to run training jobs; GPU support is a future enhancement.
- Initial deployment targets batch inference and lightweight real-time inference; high-throughput streaming inference (>1,000 RPS) is out of scope for v1.
- The fraud detection agent that consumes model predictions is a separate system; this spec covers only the MLOps layer that produces and serves the model.
- Model monitoring covers statistical drift detection on input features and prediction distributions; business-level outcome monitoring (e.g., actual fraud labels) requires a separate feedback loop and is out of scope for v1.
- A single shared model registry serves all experiments and teams in this proof-of-concept; multi-tenant isolation is a future concern.
- Network connectivity between the ML platform and the MinIO/Iceberg endpoints is available within the Kubernetes cluster.
