# Local Setup Instructions

Step-by-step guide to get Minikube running with FluxCD deploying all required apps and infrastructure.

## 1. Start Minikube

```sh
minikube start --profile fraud-gitops \
  --cpus 8 \
  --memory 16384 \
  --disk-size 80g \
  --driver docker \
  --container-runtime docker \
  --gpus all
```

> If Minikube fails with a GPU-related error (common on WSL2), omit `--gpus all` and start without it. See `docs/runbooks/bootstrap.md` for GPU troubleshooting.

## 2. Set Credential Environment Variables

Export these variables in your shell before running the secret creation commands. Choose your own values — do not commit these to the repository.

```sh
export MINIO_ROOT_USER=<your-minio-username>
export MINIO_ROOT_PASSWORD=<your-minio-password>
export GRAFANA_ADMIN_PASSWORD=<your-grafana-password>
export POLARIS_ROOT_PASSWORD=<your-polaris-password>
```

Copy the .env_example to .env 



> All four variables are required. The MinIO credentials are reused across MLflow, Polaris storage, and Flink S3 access. The Polaris password is used for both the bootstrap credentials and the Flink OAuth secret.

## 3. Create Cluster Secrets

Run these commands after Minikube is up. They create the secrets that FluxCD-managed workloads expect before they can start.

```sh
kubectl -n minio create secret generic minio-root-credentials \
  --from-literal=rootUser="$MINIO_ROOT_USER" \
  --from-literal=rootPassword="$MINIO_ROOT_PASSWORD"

kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user='admin' \
  --from-literal=admin-password="$GRAFANA_ADMIN_PASSWORD"

kubectl -n mlflow create secret generic mlflow-artifact-credentials \
  --from-literal=accessKey="$MINIO_ROOT_USER" \
  --from-literal=secretKey="$MINIO_ROOT_PASSWORD"

kubectl create namespace polaris --dry-run=client -o yaml | kubectl apply -f -

kubectl -n polaris create secret generic polaris-bootstrap-credentials \
  --from-literal=credentials="POLARIS,root,$POLARIS_ROOT_PASSWORD"

kubectl -n polaris create secret generic polaris-storage-credentials \
  --from-literal=awsAccessKeyId="$MINIO_ROOT_USER" \
  --from-literal=awsSecretAccessKey="$MINIO_ROOT_PASSWORD"

kubectl -n flink-system create secret generic minio-flink-s3-credentials \
  --from-literal=rootUser="$MINIO_ROOT_USER" \
  --from-literal=rootPassword="$MINIO_ROOT_PASSWORD"

kubectl -n flink-system create secret generic polaris-flink-oauth \
  --from-literal=credential="root:$POLARIS_ROOT_PASSWORD"
```

## 4. Build and Load Application Images

Each application with a local Dockerfile must be built and loaded into the Minikube image cache before FluxCD reconciles the workloads that reference them. Run from the repo root:

```sh
# Flink SQL runner
docker build -t flink-sql-runner:1.20.5 apps/base/flink-jobs/
minikube image load flink-sql-runner:1.20.5 --profile fraud-gitops

# Fraud alert agent
docker build -t fraud-alert-agent:0.1.8 src/fraud-alert-agent/
minikube image load fraud-alert-agent:0.1.8 --profile fraud-gitops

# Fraud investigation UI
docker build -t fraud-investigation-ui:0.1.0 src/streamlit-ui/
minikube image load fraud-investigation-ui:0.1.0 --profile fraud-gitops

# Synthetic transaction producer
docker build -t synthetic-transaction-producer:latest apps/base/synthetic-transaction-producer/
minikube image load synthetic-transaction-producer:latest --profile fraud-gitops
```

> `minikube image load` copies the image from your local Docker daemon into the Minikube node. Pods will use `imagePullPolicy: Never` or `IfNotPresent` so Kubernetes does not try to pull from a registry.

## 5. Bootstrap FluxCD

```sh
flux bootstrap github \
  --owner <github-user-or-org> \
  --repository kafka-flink-iceberg-fraud-agent-gitops \
  --branch main \
  --path clusters/minikube \
  --personal
```

FluxCD will reconcile infrastructure and apps in order: `infra-controllers` → `infra-configs` → `apps`. The full stack takes approximately 45 minutes on the recommended profile.

## User interfaces

Flink
```sh
kubectl --context=fraud-gitops -n flink-system port-forward svc/sample-fraud-stream-rest 8081:8081
```

MinIO
```sh
kubectl --context=fraud-gitops -n minio port-forward svc/minio-console 9001:9001
```

KubeFlow
```sh
kubectl --context=fraud-gitops -n istio-system port-forward svc/istio-ingressgateway 8085:80
