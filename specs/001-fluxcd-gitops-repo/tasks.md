---

description: "Task list for FluxCD GitOps monorepo foundation"
---

# Tasks: FluxCD GitOps Monorepo Foundation

**Input**: Design documents from `/specs/001-fluxcd-gitops-repo/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Include the validation needed to satisfy the constitution. Automated tests
are not the primary artifact for this repository; instead, each phase includes
render, schema, security, and smoke-validation tasks for Flux-managed manifests.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **GitOps monorepo**: `clusters/`, `infrastructure/`, `apps/`, `docs/`, `scripts/`
- **Cluster entrypoint**: `clusters/minikube/`
- **Shared platform**: `infrastructure/controllers/`, `infrastructure/configs/`
- **Workloads**: `apps/base/`, `apps/minikube/`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and repository skeleton

- [x] T001 Create repository skeleton files in `README.md`, `docs/runbooks/README.md`, `clusters/minikube/kustomization.yaml`, `infrastructure/controllers/base/kustomization.yaml`, `infrastructure/configs/base/kustomization.yaml`, and `apps/base/kustomization.yaml`
- [x] T002 Create cluster bootstrap placeholders in `clusters/minikube/apps.yaml`, `clusters/minikube/infrastructure.yaml`, and `clusters/minikube/secrets/README.md`
- [x] T003 [P] Create validation automation in `scripts/validate.sh` and `Makefile`
- [x] T004 [P] Create CI workflow skeletons in `.github/workflows/validate.yaml` and `.github/workflows/secret-scan.yaml`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core GitOps infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Create SOPS and public-repo secret policy files in `.sops.yaml`, `.gitignore`, and `docs/runbooks/secret-management.md`
- [x] T006 [P] Create controller aggregation overlays in `infrastructure/controllers/base/kustomization.yaml` and `infrastructure/controllers/minikube/kustomization.yaml`
- [x] T007 [P] Create config aggregation overlays in `infrastructure/configs/base/kustomization.yaml` and `infrastructure/configs/minikube/kustomization.yaml`
- [x] T008 [P] Create app aggregation overlays in `apps/base/kustomization.yaml` and `apps/minikube/kustomization.yaml`
- [x] T009 Create shared namespaces and platform defaults in `infrastructure/configs/base/namespaces/kustomization.yaml` and `infrastructure/configs/base/namespaces/platform-namespaces.yaml`
- [x] T010 Create ordered Flux `dependsOn` wiring in `clusters/minikube/infrastructure.yaml`, `clusters/minikube/apps.yaml`, and `clusters/minikube/kustomization.yaml`
- [x] T011 Create bootstrap and sizing guidance in `docs/runbooks/bootstrap.md` and `README.md`
- [x] T012 Capture baseline validation and timing targets in `scripts/validate.sh`, `.github/workflows/validate.yaml`, and `docs/runbooks/reconciliation.md`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Bootstrap Shared Platform Delivery (Priority: P1) 🎯 MVP

**Goal**: Deliver the shared Minikube platform layers so Flux can bootstrap and reconcile infrastructure in dependency order

**Independent Test**: Follow `specs/001-fluxcd-gitops-repo/quickstart.md` to bootstrap Flux to `clusters/minikube`, reconcile `infra-controllers` then `infra-configs`, and verify MinIO, Polaris, Strimzi Kafka, Flink Operator, Kubeflow, Prometheus, and Grafana report healthy status

### Validation for User Story 1

- [x] T013 [P] [US1] Add render and schema validation targets for `clusters/minikube`, `infrastructure/controllers/minikube`, and `infrastructure/configs/minikube` in `scripts/validate.sh` and `.github/workflows/validate.yaml`
- [x] T014 [US1] Validate public-repo secret handling for bootstrap inputs in `.sops.yaml`, `clusters/minikube/secrets/README.md`, and `docs/runbooks/secret-management.md`
- [x] T015 [US1] Validate bootstrap timing and reconciliation checkpoints in `docs/runbooks/bootstrap.md` and `docs/runbooks/reconciliation.md`

### Implementation for User Story 1

- [x] T016 [P] [US1] Add MinIO controller manifests in `infrastructure/controllers/base/minio/kustomization.yaml` and `infrastructure/controllers/minikube/minio/kustomization.yaml`
- [x] T017 [P] [US1] Add monitoring stack manifests for Prometheus and Grafana in `infrastructure/controllers/base/monitoring/kustomization.yaml` and `infrastructure/controllers/minikube/monitoring/kustomization.yaml`
- [x] T018 [P] [US1] Add Polaris manifests in `infrastructure/controllers/base/polaris/kustomization.yaml` and `infrastructure/controllers/minikube/polaris/kustomization.yaml`
- [x] T019 [P] [US1] Add Strimzi operator manifests in `infrastructure/controllers/base/strimzi/kustomization.yaml` and `infrastructure/controllers/minikube/strimzi/kustomization.yaml`
- [x] T020 [P] [US1] Add Kafka cluster configuration in `infrastructure/configs/base/kafka/kustomization.yaml` and `infrastructure/configs/minikube/kafka/kustomization.yaml`
- [x] T021 [P] [US1] Add Flink Operator manifests in `infrastructure/controllers/base/flink-operator/kustomization.yaml` and `infrastructure/controllers/minikube/flink-operator/kustomization.yaml`
- [x] T022 [P] [US1] Add Kubeflow manifests and Minikube tuning in `infrastructure/controllers/base/kubeflow/kustomization.yaml` and `infrastructure/controllers/minikube/kubeflow/kustomization.yaml`
- [x] T023 [US1] Wire controller/config dependency order into `infrastructure/controllers/base/kustomization.yaml`, `infrastructure/configs/base/kustomization.yaml`, and `clusters/minikube/infrastructure.yaml`
- [x] T024 [US1] Document platform bring-up and smoke checks in `docs/runbooks/bootstrap.md` and `docs/runbooks/reconciliation.md`

**Checkpoint**: At this point, the shared platform should bootstrap and reconcile independently on Minikube

---

## Phase 4: User Story 2 - Onboard Application Workloads Consistently (Priority: P2)

**Goal**: Provide a standard workload pattern for app teams using MLflow and sample Flink jobs without restructuring the repository

**Independent Test**: An application owner can add or update workload manifests under `apps/base/` and `apps/minikube/`, reconcile `clusters/minikube/apps.yaml`, and observe MLflow and sample Flink workload resources deploy through the standard app path

### Validation for User Story 2

- [x] T025 [P] [US2] Add workload render validation for `apps/base` and `apps/minikube` in `scripts/validate.sh` and `.github/workflows/validate.yaml`
- [x] T026 [US2] Validate workload dependency and secret-reference rules in `apps/minikube/kustomization.yaml`, `clusters/minikube/apps.yaml`, and `docs/runbooks/secret-management.md`

### Implementation for User Story 2

- [x] T027 [P] [US2] Add MLflow workload base and Minikube overlay in `apps/base/mlflow/kustomization.yaml` and `apps/minikube/mlflow/kustomization.yaml`
- [x] T028 [P] [US2] Add sample Flink job base and Minikube overlay in `apps/base/flink-jobs/kustomization.yaml` and `apps/minikube/flink-jobs/kustomization.yaml`
- [x] T029 [P] [US2] Add workload secret placeholders and contributor notes in `apps/minikube/mlflow/README.md`, `apps/minikube/flink-jobs/README.md`, and `clusters/minikube/secrets/README.md`
- [x] T030 [US2] Wire workload reconciliation and `dependsOn` rules in `apps/minikube/kustomization.yaml` and `clusters/minikube/apps.yaml`
- [x] T031 [US2] Add workload onboarding guidance in `README.md` and `docs/runbooks/bootstrap.md`

**Checkpoint**: At this point, application workloads should be independently onboarded and reconciled through the standard repository path

---

## Phase 5: User Story 3 - Audit and Operate Repository-Driven Changes (Priority: P3)

**Goal**: Make ownership, review, rollback, and troubleshooting expectations explicit for operators and governance stakeholders

**Independent Test**: A reviewer who did not author the repository can identify ownership boundaries, follow the reconciliation and rollback steps, and verify required change evidence from repository documentation and workflow templates

### Validation for User Story 3

- [x] T032 [US3] Validate ownership, review, and rollback evidence paths in `.github/CODEOWNERS`, `.github/pull_request_template.md`, and `docs/runbooks/reconciliation.md`

### Implementation for User Story 3

- [x] T033 [P] [US3] Define path ownership boundaries in `.github/CODEOWNERS`
- [x] T034 [P] [US3] Create change evidence and reviewer checklist template in `.github/pull_request_template.md`
- [x] T035 [P] [US3] Document reconciliation failure handling and rollback steps in `docs/runbooks/reconciliation.md`
- [x] T036 [P] [US3] Document secret rotation and local bootstrap credential handling in `docs/runbooks/secret-management.md`
- [x] T037 [US3] Update repository overview and ownership map in `README.md` and `docs/runbooks/README.md`
- [x] T038 [US3] Create contributor workflow guidance in `CONTRIBUTING.md`

**Checkpoint**: All user stories should now be independently functional and auditable

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T039 [P] Run the end-to-end quickstart validation in `specs/001-fluxcd-gitops-repo/quickstart.md` and record final adjustments in `README.md`
- [x] T040 [P] Tune Minikube resource requests and retention settings in `infrastructure/controllers/minikube/monitoring/kustomization.yaml`, `infrastructure/controllers/minikube/kubeflow/kustomization.yaml`, and `infrastructure/configs/minikube/kafka/kustomization.yaml`
- [x] T041 Harden public-repo hygiene in `.github/workflows/secret-scan.yaml`, `.gitignore`, and `.sops.yaml`
- [x] T042 Finalize cross-linked runbook documentation in `README.md`, `docs/runbooks/bootstrap.md`, `docs/runbooks/reconciliation.md`, and `docs/runbooks/secret-management.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion
- **User Story 2 (Phase 4)**: Depends on Foundational completion and uses the platform paths created in User Story 1 for meaningful validation
- **User Story 3 (Phase 5)**: Depends on Foundational completion and should be finalized after User Stories 1 and 2 establish the actual managed areas
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2), but its independent test assumes the shared platform from User Story 1 is available
- **User Story 3 (P3)**: Can begin after Foundational (Phase 2), but ownership, rollback, and audit guidance should be finalized after User Stories 1 and 2 define the concrete paths

### Within Each User Story

- Validation tasks before implementation tasks
- Aggregation and dependency wiring before final story sign-off
- README and runbook updates before story completion
- Story complete before moving to final polish

### Parallel Opportunities

- Setup tasks `T003` and `T004` can run in parallel after the initial skeleton exists
- Foundational tasks `T006`, `T007`, and `T008` can run in parallel because they touch different directory trees
- User Story 1 component tasks `T016` through `T022` can run in parallel once the aggregation structure is in place
- User Story 2 workload tasks `T027`, `T028`, and `T029` can run in parallel
- User Story 3 governance tasks `T033` through `T036` can run in parallel

---

## Parallel Example: User Story 1

```bash
Task: "Add MinIO controller manifests in infrastructure/controllers/base/minio/kustomization.yaml and infrastructure/controllers/minikube/minio/kustomization.yaml"
Task: "Add monitoring stack manifests for Prometheus and Grafana in infrastructure/controllers/base/monitoring/kustomization.yaml and infrastructure/controllers/minikube/monitoring/kustomization.yaml"
Task: "Add Polaris manifests in infrastructure/controllers/base/polaris/kustomization.yaml and infrastructure/controllers/minikube/polaris/kustomization.yaml"
Task: "Add Strimzi operator manifests in infrastructure/controllers/base/strimzi/kustomization.yaml and infrastructure/controllers/minikube/strimzi/kustomization.yaml"
Task: "Add Flink Operator manifests in infrastructure/controllers/base/flink-operator/kustomization.yaml and infrastructure/controllers/minikube/flink-operator/kustomization.yaml"
Task: "Add Kubeflow manifests and Minikube tuning in infrastructure/controllers/base/kubeflow/kustomization.yaml and infrastructure/controllers/minikube/kubeflow/kustomization.yaml"
```

## Parallel Example: User Story 2

```bash
Task: "Add MLflow workload base and Minikube overlay in apps/base/mlflow/kustomization.yaml and apps/minikube/mlflow/kustomization.yaml"
Task: "Add sample Flink job base and Minikube overlay in apps/base/flink-jobs/kustomization.yaml and apps/minikube/flink-jobs/kustomization.yaml"
Task: "Add workload secret placeholders and contributor notes in apps/minikube/mlflow/README.md, apps/minikube/flink-jobs/README.md, and clusters/minikube/secrets/README.md"
```

## Parallel Example: User Story 3

```bash
Task: "Define path ownership boundaries in .github/CODEOWNERS"
Task: "Create change evidence and reviewer checklist template in .github/pull_request_template.md"
Task: "Document reconciliation failure handling and rollback steps in docs/runbooks/reconciliation.md"
Task: "Document secret rotation and local bootstrap credential handling in docs/runbooks/secret-management.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Bootstrap Minikube and verify `infra-controllers` and `infra-configs`
5. Demo the shared platform before adding workloads

### Incremental Delivery

1. Complete Setup + Foundational -> repository skeleton and validation baseline ready
2. Add User Story 1 -> bootstrap shared platform -> validate Flux reconciliation
3. Add User Story 2 -> onboard MLflow and sample Flink workloads -> validate app path
4. Add User Story 3 -> finalize ownership, rollback, and audit guidance
5. Finish with Polish -> run full quickstart and tune Minikube defaults

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. One engineer takes shared platform components for User Story 1 while another prepares validation automation and runbooks
3. After User Story 1 is stable, workload onboarding tasks for User Story 2 and governance tasks for User Story 3 can proceed in parallel

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] labels map tasks directly to user stories for traceability
- Each user story is structured to be independently testable at the repository level
- Validation, secret handling, and documentation are first-class tasks, not optional follow-up work
- The suggested MVP scope is Phase 1 + Phase 2 + User Story 1
