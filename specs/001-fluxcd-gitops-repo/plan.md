# Implementation Plan: FluxCD GitOps Monorepo Foundation

**Branch**: `[001-fluxcd-gitops-repo]` | **Date**: 2026-03-29 | **Spec**: [`specs/001-fluxcd-gitops-repo/spec.md`](./spec.md)
**Input**: Feature specification from `/specs/001-fluxcd-gitops-repo/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Build a public FluxCD GitOps monorepo for a Minikube-based local platform that
separates cluster wiring, shared infrastructure, and workloads using the Flux
monorepo pattern. The implementation will use `clusters/minikube` as the Flux
entrypoint, reusable `base` definitions with Minikube-specific overlays, ordered
Flux `Kustomization` dependencies for platform bring-up, and a strict no-secrets-in-git
model using encrypted or externally managed secret references.

## Technical Context

**Language/Version**: Kubernetes YAML manifests using Flux v2 APIs, Helm values,
Kustomize overlays, Markdown documentation, and Bash helper scripts  
**Primary Dependencies**: FluxCD, Kustomize, Helm, Minikube, kubectl, SOPS with age
for encrypted secrets, kubeconform, yamllint, and platform charts/operators for
MinIO, Polaris, Strimzi Kafka, Flink Kubernetes Operator, Kubeflow, MLflow,
Prometheus, and Grafana  
**Storage**: Minikube persistent volumes for local state; MinIO as the in-cluster
object store; encrypted or externally provisioned secrets only  
**Testing**: `kustomize build`, `flux build kustomization`, `helm template` where
applicable, `kubeconform`, `yamllint`, secret scanning, and Minikube smoke checks
using `flux get` and `kubectl wait`  
**Target Platform**: Single-node Minikube Kubernetes cluster on a local developer
machine, with the repository structured to expand to additional clusters later  
**Project Type**: GitOps monorepo for Kubernetes platform infrastructure and
application workloads  
**Performance Goals**: Core GitOps, monitoring, and policy layers healthy within
15 minutes of bootstrap; full requested stack ready within 45 minutes on a
Minikube profile sized for the platform; standard reconciliation completes within
5 minutes after a reviewed change under normal local load  
**Constraints**: Public GitHub repository, no committed plaintext secrets, no
private keys or passwords in version control, Flux monorepo structure aligned with
community best practices, explicit dependency ordering, and Minikube resource
limits that require lean defaults and tunable overlays  
**Scale/Scope**: One `minikube` environment in v1 with reusable bases for future
staging or production overlays; initial platform scope includes MinIO, Polaris,
Strimzi Kafka, Flink Operator, Kubeflow, MLflow, Prometheus, and Grafana

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- `Security by Default`: PASS. The plan uses a public-repo secret model based on
  SOPS-encrypted files or externally provisioned secrets, keeps all sensitive
  values out of plaintext Git, and makes cluster trust boundaries explicit through
  ownership and bootstrap contracts.
- `Production-Grade Engineering`: PASS. The design uses Flux-native structure,
  deterministic ordering with `dependsOn`, CI-friendly manifest validation, and a
  rollback path based on reverting repository state and reconciling back to the
  previous approved revision.
- `README-Driven Documentation`: PASS. The implementation will require a root
  `README.md`, per-area README coverage for platform layers, and runbooks for
  bootstrap, secret management, and reconciliation troubleshooting.
- `Performance Is a Feature`: PASS. The plan defines bootstrap and reconciliation
  time targets, sizes Minikube explicitly, and treats heavy components such as
  Kubeflow as tuned overlays rather than uncontrolled defaults.
- `Observable and Operable Systems`: PASS. The plan places Prometheus and Grafana in
  the platform path, documents Flux health checks, and requires operators to be
  diagnosable through `flux get`, `kubectl wait`, logs, and monitoring dashboards.

**Post-Design Re-check**: PASS. `research.md`, `data-model.md`, `quickstart.md`, and
`contracts/` resolve the initial structural, security, and operability questions
without leaving constitutional gaps or unresolved clarifications.

## Project Structure

### Documentation (this feature)

```text
specs/001-fluxcd-gitops-repo/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── repository-structure.md
│   └── minikube-bootstrap.md
└── tasks.md
```

### Source Code (repository root)

```text
apps/
├── base/
│   ├── flink-jobs/
│   └── mlflow/
└── minikube/
    ├── flink-jobs/
    └── mlflow/

clusters/
└── minikube/
    ├── flux-system/
    ├── kustomization.yaml
    ├── infrastructure.yaml
    ├── apps.yaml
    └── secrets/
        └── README.md

infrastructure/
├── controllers/
│   ├── base/
│   │   ├── minio/
│   │   ├── polaris/
│   │   ├── strimzi/
│   │   ├── flink-operator/
│   │   ├── kubeflow/
│   │   └── monitoring/
│   └── minikube/
└── configs/
    ├── base/
    │   ├── namespaces/
    │   ├── kafka/
    │   ├── storage/
    │   ├── monitoring/
    │   └── ml-platform/
    └── minikube/

docs/
└── runbooks/
    ├── bootstrap.md
    ├── reconciliation.md
    └── secret-management.md

scripts/
└── validate.sh
```

**Structure Decision**: Use the FluxCD monorepo pattern with `clusters/` for Flux
entrypoints and ordering, `infrastructure/` for shared platform controllers and
cluster-wide configs, and `apps/` for workload-level definitions. Keep reusable
`base` manifests plus `minikube` overlays even for a single environment so future
staging or production expansion does not require restructuring.

## Complexity Tracking

No constitutional violations or design exceptions are currently required. The only
notable complexity is the full platform footprint on Minikube, which is handled by
explicit sizing guidance and Minikube-specific overlays rather than by relaxing the
governance rules.
