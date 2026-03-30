# MLflow Workload

This overlay exposes the MLflow service for Minikube testing.

Expected dependencies:

- MinIO is reconciled and healthy
- `mlflow-artifact-credentials` exists in the cluster
- Monitoring is available
- Kubeflow is optional; the active Minikube bundle only enables its lighter core controllers
