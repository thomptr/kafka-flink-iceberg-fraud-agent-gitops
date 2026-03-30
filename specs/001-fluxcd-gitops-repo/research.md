# Research: FluxCD GitOps Monorepo Foundation

## Decision 1

Decision: Adopt the Flux monorepo layout with top-level `clusters/`,
`infrastructure/`, and `apps/` directories, using `clusters/minikube` as the sole
Flux bootstrap entrypoint for the first environment.

Rationale: This follows the standard Flux monorepo mental model, keeps cluster
wiring separate from reusable manifests, and makes future expansion to staging or
production straightforward without moving existing content.

Alternatives considered: A flat `flux/` tree was rejected because it obscures the
separation between cluster entrypoints, shared platform services, and workloads. A
single `clusters/minikube`-only layout was rejected because it does not scale well
once a second environment is added.

## Decision 2

Decision: Keep reusable `base` definitions and Minikube-specific overlays for both
infrastructure and workloads, even though v1 only targets a single `minikube`
environment.

Rationale: A dedicated `minikube` overlay captures resource sizing, storage class,
ingress exposure, and lightweight local defaults without polluting shared base
manifests. This also preserves a clean promotion path when more environments are
introduced later.

Alternatives considered: Storing all Minikube patches directly under
`clusters/minikube` was rejected because it would centralize too much environment
logic in the cluster entrypoint and make reuse difficult. Delaying overlays until a
second environment exists was rejected because it would force a repository
restructure later.

## Decision 3

Decision: Reconcile the platform in ordered Flux stages:
`infra-controllers` -> `infra-configs` -> `apps`, with component-specific
dependencies inside those layers.

Rationale: Controllers and CRDs must exist before their custom resources can be
applied, and workload definitions must not reconcile before shared platform services
are ready. This explicit ordering reduces bootstrap failures and makes recovery
easier to diagnose.

Alternatives considered: A single monolithic `infrastructure` reconciliation was
rejected because it hides ordering errors and makes troubleshooting harder. Relying
only on folder naming or Helm subchart dependencies was rejected because cross-chart
and cross-directory dependencies still need Flux-native ordering.

## Decision 4

Decision: Group platform components by operational role. Put MinIO, Polaris,
Strimzi, Flink Operator, Kubeflow, and the Prometheus/Grafana stack in
`infrastructure/controllers`, keep non-secret cluster tuning and component CRs in
`infrastructure/configs`, and place fast-changing workload definitions such as Flink
jobs and MLflow workload overlays in `apps`.

Rationale: This aligns ownership with change frequency. Shared operators and
platform-wide services are maintained by the platform team, while workload-level
definitions remain isolated for application contributors.

Alternatives considered: Putting all component YAML under `apps/` was rejected
because it blurs the line between cluster platform responsibilities and application
responsibilities. Putting all component manifests in a single `infrastructure/`
directory was rejected because it mixes operators, configs, and workload semantics.

## Decision 5

Decision: Treat secret material as out-of-band or encrypted-only content. Use
SOPS-encrypted manifests with age for any committed secret-bearing files, and allow
externally provisioned secret backends or manual local secret creation for Minikube
bootstrap.

Rationale: The repository is public, so plaintext `Secret` manifests, kubeconfigs,
private keys, passwords, and token files are prohibited. Flux works well with
SOPS-encrypted content, while local Minikube users still need a documented path to
create decrypt keys and cluster secrets safely.

Alternatives considered: Plain Kubernetes `Secret` YAML was rejected because base64
is not protection. A policy-only "do not commit secrets" approach was rejected
because it is too easy to violate accidentally. Fully external secrets with no
encrypted manifests were rejected for v1 because they complicate local bootstrap.

## Decision 6

Decision: Ship the full requested component set in scope, but size and tune the
Minikube environment explicitly and allow a slimmed local profile for heavy
components, especially Kubeflow.

Rationale: The user explicitly requested MinIO, Polaris, Strimzi, Flink Operator,
Kubeflow, MLflow, Prometheus, and Grafana. Minikube can host the stack only if CPU,
memory, and storage are called out up front and each overlay uses conservative
defaults for a local cluster.

Alternatives considered: Dropping Kubeflow or MLflow from scope was rejected because
it conflicts with the requested platform. Treating the full stack as if it has no
local performance cost was rejected because it would create unrealistic expectations
for bootstrap and reconciliation time.

## Decision 7

Decision: Validate every repository path that Flux reconciles with local and CI
checks using `kustomize build`, `flux build kustomization`, `helm template`,
`kubeconform`, YAML linting, and secret scanning before merge.

Rationale: A GitOps repo fails late and noisily if invalid manifests reach the
cluster. Schema validation, render checks, and secret scanning make the public repo
safer and more predictable before Flux ever sees the change.

Alternatives considered: Manual review alone was rejected as insufficient for a
public infrastructure repository. Full end-to-end cluster tests for every change
were deferred because they are heavier than necessary for initial planning, though
they remain a strong future enhancement.

## Decision 8

Decision: Document one "golden path" bootstrap for Minikube that covers local
cluster creation, Flux bootstrap to `clusters/minikube`, secret preparation, health
verification, and rollback to the previous approved Git revision.

Rationale: Operational clarity is a first-class requirement in the constitution.
Contributors and reviewers need a short, repeatable workflow that avoids manual
cluster drift and makes troubleshooting consistent.

Alternatives considered: Putting all operational detail only in ad hoc notes or
issue comments was rejected because it creates tribal knowledge. Overloading the
root README with all troubleshooting detail was rejected because a focused runbook
structure scales better.
