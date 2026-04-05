# Quickstart: FluxCD GitOps Monorepo Foundation

## Goal

Bring up the Minikube-targeted GitOps repository structure locally, bootstrap Flux
to the `clusters/minikube` path, and verify that the shared platform and workload
layers reconcile without committing secrets to Git.

## Prerequisites

- A local workstation with Docker or another Minikube-supported driver
- `minikube`, `kubectl`, and `flux` installed
- `kustomize`, `helm`, `kubeconform`, and `yamllint` installed for local validation
- `python3` available locally for the optional `PyIceberg` smoke test
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
Kubeflow is enabled as a smaller pinned core install in the
`infra-controllers` Minikube bundle. Pipelines, KServe, Katib, and Spark
Operator stay out of the active local path so the Flink-based platform remains
practical on Minikube.

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

kubectl create namespace polaris --dry-run=client -o yaml | kubectl apply -f -

# Apache Polaris bootstraps a local root client from this value. The format is:
# REALM,CLIENT_ID,CLIENT_SECRET
kubectl -n polaris create secret generic polaris-bootstrap-credentials \
  --from-literal=credentials='POLARIS,root,<choose-a-local-password>'

# Reuse the MinIO root username/password so Apache Polaris can access the same
# local MinIO instance for S3-backed catalogs.
kubectl -n polaris create secret generic polaris-storage-credentials \
  --from-literal=awsAccessKeyId='<same-value-as-minio-rootUser>' \
  --from-literal=awsSecretAccessKey='<same-value-as-minio-rootPassword>'
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
- `polaris-bootstrap-credentials` in the `polaris` namespace
- `polaris-storage-credentials` in the `polaris` namespace

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
- Apache Polaris catalog works with a simple PyIceberg script.
- MLflow endpoints reconcile according to the Minikube overlay
- Kubeflow dashboard and notebook components reconcile from the pinned core set

Optional Apache Polaris smoke test:

```bash
kubectl -n polaris port-forward svc/polaris 8181:8181
kubectl -n minio port-forward svc/minio 9000:9000

uv pip install pyiceberg pyarrow boto3

POLARIS_CLIENT_ID=root \
POLARIS_CLIENT_SECRET='<same-value-as-polaris-bootstrap-client-secret>' \
POLARIS_S3_ACCESS_KEY_ID='<same-as-polaris-storage-awsAccessKeyId>' \
POLARIS_S3_SECRET_ACCESS_KEY='<same-as-polaris-storage-awsSecretAccessKey>' \
python3 scripts/verify_polaris_pyiceberg.py
```

The script ensures the catalog and namespace, then creates an Iceberg table (`POLARIS_TABLE_NAME`, default `smoke_test`), appends rows, and scans them back. Set `POLARIS_TABLE_REPLACE=0` to fail if the table already exists instead of dropping it.

PyIceberg defaults to requesting vended S3 credentials from Polaris (`X-Iceberg-Access-Delegation: vended-credentials`), which requires extra Polaris grants that the bootstrap `root` user does not have. This script therefore defaults to **static MinIO credentials** via `POLARIS_S3_*` (and clears that header). To use vended credentials instead, set `POLARIS_USE_VENDED_CREDENTIALS=1` and configure Polaris RBAC accordingly.

If table creation returns **500** with a Polaris error mentioning `SdkClientException` and “Unable to load credentials”, the Polaris server process needs MinIO keys on the **default AWS SDK credential chain** as well as the chart’s `polaris.storage.aws.*` mapping. The `infra-controllers` HelmRelease sets `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` from `polaris-storage-credentials`; reconcile Flux and restart the Polaris pod (`kubectl rollout restart deployment/polaris -n polaris`) so the pod picks up the env vars.

The default warehouse is `s3://iceberg-warehouse/...`; that bucket must exist in MinIO. The script uses **boto3** to create it automatically when using static `POLARIS_S3_*` credentials (`POLARIS_ENSURE_S3_BUCKET=1` by default). To create the bucket yourself instead, use e.g. `mc mb minio/iceberg-warehouse` and set `POLARIS_ENSURE_S3_BUCKET=0`.

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
