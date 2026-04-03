# Minikube Secrets

This directory is documentation-only for the local workflow. Create secrets
directly in the Minikube cluster with `kubectl create secret generic ...` instead of
committing them to Git.

Required local secrets currently include:

- `minio-root-credentials` in the `minio` namespace
- `grafana-admin-credentials` in the `monitoring` namespace
- `mlflow-artifact-credentials` in the `mlflow` namespace
- `polaris-bootstrap-credentials` in the `polaris` namespace
- `polaris-storage-credentials` in the `polaris` namespace

Do not commit plaintext secrets here.
