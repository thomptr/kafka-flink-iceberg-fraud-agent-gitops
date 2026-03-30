# Bootstrap Runbook

## Minikube Profile

Use a dedicated profile with at least 8 CPUs, 16 GiB memory, and 80 GiB disk for
the full stack.

```bash
minikube start --profile fraud-gitops --cpus 8 --memory 16384 --disk-size 80g
```

## Validate Before Bootstrap

```bash
make validate
```

## Bootstrap Flux

```bash
flux bootstrap github \
  --owner <github-user-or-org> \
  --repository <repo-name> \
  --branch main \
  --path clusters/minikube
```

## Create Local Cluster Secrets

Create the required secrets directly in Minikube before reconciling workloads that
depend on them:

```bash
kubectl -n minio create secret generic minio-root-credentials \
  --from-literal=root-user='<choose-a-local-user>' \
  --from-literal=root-password='<choose-a-local-password>'

kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user='admin' \
  --from-literal=admin-password='<choose-a-local-password>'

kubectl -n mlflow create secret generic mlflow-artifact-credentials \
  --from-literal=accessKey='<minio-access-key>' \
  --from-literal=secretKey='<minio-secret-key>'
```

## Reconciliation Order

1. `infra-controllers`
2. `infra-configs`
3. `apps`

## Success Targets

- Core platform ready within 15 minutes
- Full stack ready within 45 minutes on the recommended profile
- Routine reconciliations ready within 5 minutes after approved changes
