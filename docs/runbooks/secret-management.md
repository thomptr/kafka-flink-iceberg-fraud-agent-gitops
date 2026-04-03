# Secret Management

This repository is public. Plaintext `Secret` manifests, kubeconfigs, passwords,
private keys, and tokens must never be committed.

## Preferred Local Pattern

For Minikube development, create Kubernetes secrets directly in the local cluster
as needed. This is the default workflow for this repository.

Example commands:

```bash
kubectl -n minio create secret generic minio-root-credentials \
  --from-literal=rootUser='<choose-a-local-user>' \
  --from-literal=rootPassword='<choose-a-local-password>'

kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user='admin' \
  --from-literal=admin-password='<choose-a-local-password>'

kubectl -n mlflow create secret generic mlflow-artifact-credentials \
  --from-literal=accessKey='<same-value-as-minio-rootUser>' \
  --from-literal=secretKey='<same-value-as-minio-rootPassword>'

kubectl create namespace polaris --dry-run=client -o yaml | kubectl apply -f -
kubectl -n polaris create secret generic polaris-bootstrap-credentials \
  --from-literal=credentials='POLARIS,root,<choose-a-local-password>'

kubectl -n polaris create secret generic polaris-storage-credentials \
  --from-literal=awsAccessKeyId='<same-value-as-minio-rootUser>' \
  --from-literal=awsSecretAccessKey='<same-value-as-minio-rootPassword>'
```

## Optional Future Patterns

- SOPS-encrypted YAML using age
- External secret managers referenced from manifests

## Expected Files

- `clusters/minikube/secrets/README.md` explains local secret inputs
- `.sops.yaml` may remain in the repository for future encrypted-secret adoption,
  but it is not required for local Minikube bootstrap

## Rotation

1. Delete or replace the affected Kubernetes secret in the local cluster.
2. Recreate it with `kubectl create secret generic ...` using the new value.
3. Re-run `make validate` and document the secret dependency in the pull request if
   the change affects setup instructions.
