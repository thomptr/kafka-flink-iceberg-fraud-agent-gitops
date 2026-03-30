# Quickstart: FluxCD GitOps Monorepo Foundation

## Goal

Bring up the Minikube-targeted GitOps repository structure locally, bootstrap Flux
to the `clusters/minikube` path, and verify that the shared platform and workload
layers reconcile without committing secrets to Git.

## Prerequisites

- A local workstation with Docker or another Minikube-supported driver
- `minikube`, `kubectl`, and `flux` installed
- `kustomize`, `helm`, `kubeconform`, and `yamllint` installed for local validation
- A public Git hosting repository already created

## Recommended Minikube Profile

Use a dedicated Minikube profile sized for the requested platform:

```bash
minikube start \
  --profile fraud-gitops \
  --cpus 8 \
  --memory 16384 \
  --disk-size 80g
```

If the full stack is too heavy for the local machine, keep the same repository
structure but use Minikube overlays with reduced replicas and lighter defaults.
Kubeflow is currently deferred from the active `infra-controllers` Minikube bundle
so the rest of the platform can reconcile first.

## 1. Validate the Repository Before Bootstrap

Run local render and schema checks for every Flux-managed path:

```bash
kustomize build clusters/minikube
kustomize build infrastructure/controllers/minikube
kustomize build infrastructure/configs/minikube
kustomize build apps/minikube
```

Add schema and lint validation:

```bash
kubeconform -summary <(kustomize build clusters/minikube)
yamllint .
```

## 2. Prepare Secret Handling Out of Band

For local Minikube use, create the required Kubernetes secrets directly in the
cluster with `kubectl`. This keeps secrets out of Git while avoiding the overhead
of SOPS or an external secret backend.

Example local bootstrap secrets:

```bash
kubectl create namespace minio --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace mlflow --dry-run=client -o yaml | kubectl apply -f -

kubectl -n minio create secret generic minio-root-credentials \
  --from-literal=rootUser='<choose-a-local-user>' \
  --from-literal=rootPassword='<choose-a-local-password>'

kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user='admin' \
  --from-literal=admin-password='<choose-a-local-password>'

# For local development, reuse the MinIO root username/password below so MLflow
# can authenticate to the same MinIO instance.
kubectl -n mlflow create secret generic mlflow-artifact-credentials \
  --from-literal=accessKey='<same-value-as-minio-rootUser>' \
  --from-literal=secretKey='<same-value-as-minio-rootPassword>'
```

For example, if `minio-root-credentials` uses `rootUser='minioadmin'` and
`rootPassword='choose-a-strong-local-password'`, use those same values for
`mlflow-artifact-credentials`.

If you later want encrypted manifests, SOPS can still be added as an optional
enhancement, but it is not required for local development.

Do not commit plaintext `Secret` data, kubeconfigs, passwords, private keys, or
token values.

## 3. Bootstrap Flux

Point Flux at the `clusters/minikube` path:

```bash
flux bootstrap github \
  --owner <github-user-or-org> \
  --repository <repo-name> \
  --branch main \
  --path clusters/minikube
```

If GitHub is not the target host, use the equivalent Flux bootstrap command for the
chosen provider while keeping the same repository path.

## 4. Apply or Unlock Secret Inputs

Before or immediately after bootstrap, ensure the Minikube cluster contains the
secret material required by the platform:

- `minio-root-credentials` in the `minio` namespace
- `grafana-admin-credentials` in the `monitoring` namespace
- `mlflow-artifact-credentials` in the `mlflow` namespace

You can create these locally with `kubectl create secret generic ...` and recreate
or rotate them whenever needed. They should exist only in the cluster, not in Git.

## 5. Verify Reconciliation Order

Confirm that Flux reconciles the environment in the planned order:

```bash
flux get sources git -A
flux get kustomizations -A

```

Expected progression:

1. `infra-controllers` becomes ready
2. `infra-configs` becomes ready
3. `apps` becomes ready

## 6. Run Smoke Checks

Validate the platform at a minimum with:

- Flux reports all Kustomizations as `Ready=True`
- Prometheus and Grafana pods are running
- MinIO is reachable inside the cluster
- Strimzi and the Kafka cluster resources are healthy
- Flink Operator is running and ready for a sample job
- Polaris dashboard or audit output is available
- MLflow endpoints reconcile according to the Minikube overlay

Kubeflow manifests remain in the repository for later activation, but they are not
part of the active Minikube controller reconciliation path right now.

## 7. Roll Back a Bad Change

To restore the previous approved state:

1. Revert the offending Git commit or pull request
2. Push the revert through the normal review path
3. Trigger or wait for Flux reconciliation
4. Re-run the verification commands above until all layers return to healthy status

## Success Targets

- Core platform layers are healthy within 15 minutes after bootstrap
- The full requested stack is healthy within 45 minutes on the recommended Minikube
  profile
- Routine reviewed changes reconcile within 5 minutes under normal local load
