# Contract: Repository Structure

## Purpose

Define the required repository layout and ownership rules for the FluxCD GitOps
monorepo.

## Required Top-Level Paths

- `clusters/`: Flux bootstrap entrypoints and environment wiring
- `infrastructure/`: Shared platform controllers and cluster-wide configuration
- `apps/`: Workload-level definitions layered on top of the platform
- `docs/`: Operational guidance and runbooks
- `scripts/`: Repeatable validation or helper automation

## Cluster Contract

- Each managed environment MUST have exactly one directory at `clusters/<environment>`
- `clusters/<environment>` MUST contain the Flux entrypoint manifests and the ordered
  `Kustomization` objects for infrastructure and apps
- `clusters/<environment>` MUST not be the primary home for reusable component logic

## Infrastructure Contract

- Shared operators and platform services MUST live under
  `infrastructure/controllers`
- Cluster-wide configuration, tuning, and custom resources MUST live under
  `infrastructure/configs`
- Both `controllers` and `configs` MUST provide reusable `base/` content and an
  environment-specific `minikube/` overlay for local tuning

## Application Contract

- Workload definitions that depend on the shared platform MUST live under `apps/`
- Shared workload defaults MUST live in `apps/base/`
- Environment-specific workload overlays MUST live in `apps/minikube/`

## Ownership Contract

- Shared platform paths require platform-team ownership and stronger review
- Workload paths may be app-team owned, but must declare their dependency on shared
  platform services
- Every managed area MUST document its owner in a README or runbook

## Verification Contract

The repository structure is considered valid only if:

- `kustomize build` succeeds for every Flux-managed path
- Flux cluster entrypoints declare an explicit infrastructure-before-app ordering
- No plaintext secret data exists anywhere in the tracked repository content
