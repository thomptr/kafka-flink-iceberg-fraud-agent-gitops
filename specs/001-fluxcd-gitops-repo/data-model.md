# Data Model: FluxCD GitOps Monorepo Foundation

## ManagedEnvironment

**Purpose**: Represents a Flux-managed target environment, starting with the
`minikube` local cluster.

**Fields**

- `name`: Stable environment identifier such as `minikube`
- `clusterType`: Environment category, initially `local`
- `path`: Repository path under `clusters/<environment>`
- `bootstrapPath`: Flux bootstrap target path
- `resourceProfile`: Declared CPU, memory, and storage expectations
- `statusChecks`: Required health and reconciliation checks
- `owners`: Platform maintainers responsible for the environment

**Validation Rules**

- `name` MUST match a single directory under `clusters/`
- `bootstrapPath` MUST point to the same environment directory that Flux bootstraps
- `resourceProfile` MUST document minimum local sizing for the requested stack
- `statusChecks` MUST include Flux reconciliation verification

**Relationships**

- Owns many `PlatformComponentGroup` records
- Owns many `ApplicationWorkload` overlays
- References many `SecretReference` records

## PlatformComponentGroup

**Purpose**: Groups shared infrastructure that must reconcile together and has a
clear operational owner.

**Fields**

- `name`: Component group identifier such as `strimzi`, `monitoring`, or `kubeflow`
- `layer`: `controllers` or `configs`
- `basePath`: Shared repository path under `infrastructure/.../base`
- `overlayPath`: Environment-specific repository path under `infrastructure/.../minikube`
- `namespace`: Primary Kubernetes namespace
- `sourceType`: Helm, Kustomize, OCI, or raw manifests
- `dependsOn`: Upstream component groups required before reconcile
- `healthSignals`: Expected readiness indicators, logs, or dashboards
- `ownerBoundary`: Responsible team or maintainer group

**Validation Rules**

- `layer` MUST be either `controllers` or `configs`
- `dependsOn` MUST not create cycles
- `overlayPath` MUST exist for Minikube-tuned components
- `healthSignals` MUST be documented for operability

**Relationships**

- Belongs to one `ManagedEnvironment`
- Can depend on other `PlatformComponentGroup` records
- Can expose services consumed by `ApplicationWorkload`

## ApplicationWorkload

**Purpose**: Represents a workload that runs on top of the shared platform, such as
Flink jobs or MLflow-specific overlays.

**Fields**

- `name`: Workload identifier
- `basePath`: Shared repository path under `apps/base`
- `overlayPath`: Environment-specific path under `apps/minikube`
- `runtimeDependencies`: Required platform services such as Kafka, MinIO, or Flux
- `ownerBoundary`: Team responsible for day-2 changes
- `syncStage`: Flux reconciliation stage in which the workload is applied
- `verificationSteps`: Commands or checks used to confirm readiness

**Validation Rules**

- Every workload MUST declare at least one verification step
- `runtimeDependencies` MUST reference existing platform groups where applicable
- Workloads MUST not reconcile before their declared dependencies

**Relationships**

- Belongs to one `ManagedEnvironment`
- Depends on one or more `PlatformComponentGroup` records
- Can be referenced by a `PromotionChange`

## PromotionChange

**Purpose**: Captures a reviewed repository update that changes the desired state of
the managed environment.

**Fields**

- `changeId`: Pull request, commit, or release identifier
- `affectedPaths`: Repository paths touched by the change
- `changeType`: Infrastructure, app, documentation, or mixed
- `approvalBoundary`: Required reviewers based on affected paths
- `rollbackTarget`: Previous approved revision or release marker
- `validationEvidence`: Build, lint, conformance, or smoke-check evidence

**Validation Rules**

- `affectedPaths` MUST map to one or more ownership boundaries
- `approvalBoundary` MUST tighten for shared infrastructure or production-like areas
- `validationEvidence` MUST exist before the change is considered ready

**State Transitions**

- `draft` -> `reviewed` -> `approved` -> `reconciled`
- `reconciled` -> `rolled_back` when reverting to a prior approved revision

**Relationships**

- Touches many `PlatformComponentGroup` or `ApplicationWorkload` records
- References one or more `OwnershipBoundary` records

## OwnershipBoundary

**Purpose**: Defines who can propose, approve, and operate a repository area.

**Fields**

- `name`: Boundary name such as `platform-core` or `app-team`
- `paths`: Repository paths governed by the boundary
- `maintainers`: People or groups with operational responsibility
- `reviewRequirements`: Minimum approval expectations
- `runbooks`: Required documentation and troubleshooting references

**Validation Rules**

- Every managed path MUST belong to exactly one primary ownership boundary
- Shared infrastructure paths MUST require stronger review than app-only paths
- Boundaries MUST reference documentation that explains operational ownership

**Relationships**

- Governs many `PlatformComponentGroup` or `ApplicationWorkload` records
- Applies to `PromotionChange` approval rules

## SecretReference

**Purpose**: Represents a sensitive value dependency that must never be committed in
plaintext.

**Fields**

- `name`: Secret or credential identifier
- `consumer`: Platform component or workload that needs the value
- `deliveryMode`: `sops`, external secret backend, or manual cluster bootstrap
- `repositoryRepresentation`: Encrypted file, placeholder manifest, or documentation-only reference
- `rotationOwner`: Maintainer responsible for lifecycle management

**Validation Rules**

- `repositoryRepresentation` MUST NOT contain plaintext secret values
- `deliveryMode` MUST be documented in bootstrap or secret-management runbooks
- Every secret reference MUST identify a consumer and a rotation owner

**Relationships**

- Belongs to one `ManagedEnvironment`
- Is consumed by `PlatformComponentGroup` or `ApplicationWorkload`
