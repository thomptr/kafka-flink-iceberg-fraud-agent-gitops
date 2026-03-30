# Contract: Minikube Bootstrap and Reconciliation

## Purpose

Define the inputs, sequence, and expected outcomes for bootstrapping the public
FluxCD repository into a Minikube environment.

## Inputs

- A running Minikube cluster with the documented CPU, memory, and disk profile
- A public Git repository containing the GitOps monorepo
- Flux CLI access for the bootstrap operator
- Out-of-band secret delivery for encrypted or externally managed sensitive values

## Bootstrap Sequence

1. Validate rendered manifests for `clusters/minikube`,
   `infrastructure/controllers/minikube`,
   `infrastructure/configs/minikube`, and `apps/minikube`
2. Bootstrap Flux to the `clusters/minikube` path
3. Provide the cluster with required decrypt keys or secret backend access
4. Reconcile `infra-controllers`
5. Reconcile `infra-configs`
6. Reconcile `apps`

## Reconciliation Rules

- `infra-controllers` MUST complete before any custom resources that depend on CRDs
- `infra-configs` MUST not reconcile before required controllers are ready
- `apps` MUST not reconcile before required platform services are healthy
- Failures in an earlier stage MUST block later stages rather than silently
  continuing

## Security Rules

- Plaintext credentials, private keys, passwords, and tokens MUST never be committed
  to Git
- Secret delivery MUST occur through SOPS-encrypted manifests, an external secret
  provider, or manual local secret creation outside version control
- Bootstrap credentials used by Flux CLI MUST remain outside the repository

## Expected Outcomes

- Flux reports the Git source and all planned Kustomizations as healthy
- Shared platform components reconcile in dependency order
- Operators can verify the ready state using `flux get`, `kubectl`, and documented
  dashboards
- Reverting to the previous approved Git revision restores the prior desired state

## Failure Conditions

- A required CRD or controller is missing when a dependent custom resource is applied
- A required secret reference is missing or undecryptable
- Resource limits in Minikube prevent components from reaching readiness within the
  documented time targets
