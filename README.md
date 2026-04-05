# FluxCD GitOps Monorepo for Minikube

This repository is a public GitOps monorepo for a Minikube-based local platform.
It uses FluxCD to reconcile shared infrastructure and workloads from a single
source of truth while keeping plaintext secrets, private keys, and passwords out
of Git.

## Stack

- FluxCD
- MinIO
- Apache Polaris catalog
- Strimzi Kafka
- Flink Kubernetes Operator
- Kubeflow core controllers for the dashboard and notebooks
- MLflow
- Prometheus
- Grafana

## Repository Layout

```text
clusters/
infrastructure/
apps/
docs/runbooks/
scripts/
```

- `clusters/minikube/` contains the Flux entrypoint and reconciliation order.
- `infrastructure/` contains shared platform controllers and cluster-wide config.
- `apps/` contains workload-level definitions such as MLflow and sample Flink jobs.

## Public Repo Rules

- Do not commit plaintext `Secret` manifests.
- Do not commit kubeconfigs, tokens, passwords, TLS private keys, or `.env` files.
- For local Minikube work, create Kubernetes secrets directly in the cluster with
  `kubectl create secret` and keep them out of Git.
- SOPS or external secret managers are optional future enhancements, not required
  for the local workflow.

## Quick Start

1. Start Minikube with the documented sizing profile.
2. Run `make validate` to render and lint all Flux-managed paths.
3. Bootstrap Flux to `clusters/minikube`.
4. Create the required Kubernetes secrets locally in Minikube.
5. Verify `infra-controllers`, `infra-configs`, and `apps` reconcile in order.
6. Port-forward Apache Polaris and MinIO, then run `scripts/verify_polaris_pyiceberg.py` (install `pyiceberg`, `pyarrow`, and `boto3`; set `POLARIS_S3_ACCESS_KEY_ID` / `POLARIS_S3_SECRET_ACCESS_KEY` to MinIO keys unless you enable vended credentials with `POLARIS_USE_VENDED_CREDENTIALS=1`). The script creates the `iceberg-warehouse` bucket if missing.

For the local Minikube workflow, Kubeflow is enabled as a pinned core install.
Heavier add-ons such as Pipelines, KServe, Katib, and Spark Operator remain out
of the active controller path so the Flink-first platform can stay lighter.

See `docs/runbooks/bootstrap.md` for the operator workflow and
`docs/runbooks/secret-management.md` for secret handling.
