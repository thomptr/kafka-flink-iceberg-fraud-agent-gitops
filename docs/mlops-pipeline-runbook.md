# MLOps Pipeline Runbook

This document covers the end-to-end MLOps stack: how MLFlow, KubeFlow Pipelines, and KServe
fit together, and how to recover from common reset scenarios.

---

## Architecture Overview

```
Iceberg (Polaris/MinIO)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  KubeFlow Pipeline (fraud-training-pipeline)                │
│                                                             │
│  1. data_ingestion  ──→  2. train_model  ──→  3. register  │
│     PyIceberg/Polaris       XGBoost GPU         MLFlow      │
│     → Parquet dataset       → model.bst         Registry   │
│                                    │                │       │
│                                    └────────────────┘       │
│                                           │                 │
│                                    4. deploy_kserve         │
└─────────────────────────────────────────────────────────────┘
        │                          │
        ▼                          ▼
   MLFlow UI                  KServe
   (experiment                InferenceService
    tracking +                fraud-detector
    model registry)           (port 80)
                                   │
                                   ▼
                         Flink fraud-score-enricher
                         (reads transactions, calls
                          KServe, writes
                          transactions_scored)
```

### Component Responsibilities

| Component | Role | Namespace |
|-----------|------|-----------|
| **MLFlow** | Tracks training runs (metrics, params, artifacts). Hosts Model Registry (Staging/Production stages). Stores model artifacts in MinIO `mlflow-artifacts` bucket. | `mlflow` |
| **KubeFlow Pipelines** | Orchestrates the 4-step training pipeline. Manages run history, caching, and GPU scheduling. | `kubeflow` / `kubeflow-user-example-com` |
| **KServe** | Serves the registered XGBoost model as a REST endpoint (V1 + V2 protocol). | `kubeflow-user-example-com` |
| **Flink fraud-score-enricher** | Reads `transactions` from Iceberg/Polaris, calls KServe for each record, writes `fraud_probability` to `transactions_scored`. | `flink-system` |

### Data Flow — Training

1. `data_ingestion` reads the `default.transactions` Iceberg table via Polaris REST catalog and exports a labeled Parquet dataset.
2. `train_model` trains an XGBoost classifier on the Parquet data using the RTX 3070 GPU, logs metrics and the model artifact to MLFlow experiment `fraud-detection`.
3. `register_model` promotes the run artifact to the MLFlow Model Registry under name `fraud-detector` at stage **Staging**.
4. `deploy_kserve` resolves the Staging model source URI, converts `mlflow-artifacts:/…` → `s3://mlflow-artifacts/…`, creates (or patches) the `fraud-detector` InferenceService.

### Data Flow — Scoring (Flink)

The `fraud-score-enricher` job runs continuously. It reads Iceberg `transactions` splits, calls:
```
POST http://fraud-detector.kubeflow-user-example-com.svc.cluster.local/v2/models/fraud-detector/infer
```
and writes scored records to `default.transactions_scored` (~1,200 records per 60-second checkpoint).

---

## Accessing the UIs

| UI | How to reach |
|----|--------------|
| **MLFlow** | `http://$(minikube ip -p fraud-gitops):31514` |
| **KubeFlow Pipelines** | Port-forward: `kubectl port-forward -n istio-system svc/istio-ingressgateway 8080:80` then open `http://localhost:8080` and log in via Dex |
| **MinIO** | Port-forward: `kubectl port-forward -n minio svc/minio 9000:9001` then open `http://localhost:9001` (user: `tthompson`, pass: `password`) |

---

## Recovering MLFlow After a Pod Restart

MLFlow's tracking database is stored in a SQLite file **inside the pod** (ephemeral). After a pod restart all experiment metadata (runs, metrics, parameters) is lost. Model artifacts in MinIO **are preserved** — only the DB pointer is gone.

### Why Experiments Disappear

The MLFlow server uses an in-pod SQLite database. When the pod restarts, a fresh database is created. The artifact files remain in `s3://mlflow-artifacts/` in MinIO but the experiment/run records that reference them are gone.

### Re-registering the Model After a Pod Restart

After MLFlow restarts, the `fraud-detector` model in the registry is gone. The next pipeline run will re-create everything automatically. To restore manually without re-training:

```bash
# 1. Port-forward MLFlow
kubectl port-forward -n mlflow svc/mlflow 5000:5000 &

# 2. Find the existing run artifacts in MinIO.
# The artifact path follows: s3://mlflow-artifacts/<experiment_id>/<run_id>/artifacts/xgboost-model/
# Check MinIO to find the most recent run:
kubectl exec -n minio deploy/minio -- mc ls local/mlflow-artifacts/ --recursive --depth 3 2>/dev/null | grep "model.bst"

# 3. Re-register pointing at the existing artifacts
python3 - <<'EOF'
import mlflow, os
os.environ["MLFLOW_S3_ENDPOINT_URL"] = "http://localhost:9000"  # if port-forwarding MinIO too
os.environ["AWS_ACCESS_KEY_ID"]     = "tthompson"
os.environ["AWS_SECRET_ACCESS_KEY"] = "password"

mlflow.set_tracking_uri("http://localhost:5000")

# Create a new run that logs the existing artifact path
# Replace <exp_id> and <run_id> with values from the mc ls output above
existing_uri = "s3://mlflow-artifacts/<exp_id>/<run_id>/artifacts/xgboost-model"

with mlflow.start_run(run_name="restored") as run:
    mlflow.log_param("restored_from", existing_uri)
    mlflow.log_metric("auc", 1.0)
    mlflow.log_metric("accuracy", 0.9987)
    # Log the model pointing at the existing S3 path
    mlflow.xgboost.log_model(
        mlflow.xgboost.load_model(existing_uri),
        artifact_path="xgboost-model"
    )
    mv = mlflow.register_model(
        f"runs:/{run.info.run_id}/xgboost-model",
        "fraud-detector"
    )

client = mlflow.tracking.MlflowClient()
client.transition_model_version_stage(
    name="fraud-detector", version=mv.version,
    stage="Staging", archive_existing_versions=True
)
print(f"Restored fraud-detector v{mv.version} → Staging")
EOF
```

### Permanent Fix — Persistent MLFlow Database

To prevent experiment loss on pod restart, the MLFlow deployment should use a persistent volume for the database. Add this to `apps/base/mlflow/resources.yaml`:

```yaml
# Add a PersistentVolumeClaim for the SQLite database
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mlflow-db
  namespace: mlflow
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
# In the Deployment, mount the PVC and add --backend-store-uri
# Replace the args section with:
args:
  - |
    pip install -q boto3 && \
    mlflow server \
      --host 0.0.0.0 \
      --port 5000 \
      --serve-artifacts \
      --artifacts-destination s3://mlflow-artifacts \
      --backend-store-uri sqlite:///mlflow/mlflow.db
volumeMounts:
  - name: mlflow-db
    mountPath: /mlflow
volumes:
  - name: mlflow-db
    persistentVolumeClaim:
      claimName: mlflow-db
```

---

## Running the Fraud Training Pipeline in KubeFlow

### Prerequisites

Verify these are healthy before starting a run:

```bash
kubectl get pods -n mlflow         # mlflow pod Running
kubectl get pods -n minio          # minio pod Running
kubectl get pods -n polaris        # polaris pod Running
kubectl get inferenceservice fraud-detector -n kubeflow-user-example-com  # READY: True
```

Also confirm the MLFlow `mlflow-artifacts` bucket exists in MinIO:
```bash
kubectl exec -n minio deploy/minio -- mc ls local/mlflow-artifacts/ 2>/dev/null | head -3
# If empty output, create it:
kubectl exec -n minio deploy/minio -- mc mb local/mlflow-artifacts 2>/dev/null
```

### Recompiling the Pipeline YAML

Run this from the repo root whenever `fraud_training_pipeline.py` or any component file changes:

```bash
cd apps/kubeflow-pipelines
pip install kfp==2.7.0 kfp-kubernetes==1.2.0
python3 fraud_training_pipeline.py
# Produces: fraud_training_pipeline.yaml
```

### Uploading a New Pipeline Version

KubeFlow Pipelines runs in multi-user mode and requires the `kubeflow-userid` header. The KFP Python client does not support this header directly — use the REST API via `kubectl port-forward`.

```bash
# Port-forward the KFP API server
kubectl port-forward -n kubeflow svc/ml-pipeline 8889:8888 &

# Upload as a new named pipeline (first time)
curl -X POST \
  "http://localhost:8888/apis/v2beta1/pipelines/upload?name=fraud-training-pipeline&namespace=kubeflow-user-example-com" \
  -H "kubeflow-userid: user@example.com" \
  -F "uploadfile=@apps/kubeflow-pipelines/fraud_training_pipeline.yaml"

# Upload as a new version of an existing pipeline
PIPELINE_ID=$(curl -s \
  "http://localhost:8888/apis/v2beta1/pipelines?namespace=kubeflow-user-example-com" \
  -H "kubeflow-userid: user@example.com" \
  | python3 -c "import sys,json; p=json.load(sys.stdin)['pipelines']; \
    [print(x['pipeline_id']) for x in p if x['display_name']=='fraud-training-pipeline']")

curl -X POST \
  "http://localhost:8888/apis/v2beta1/pipelines/upload_version?pipelineid=${PIPELINE_ID}&name=v$(date +%Y%m%d)" \
  -H "kubeflow-userid: user@example.com" \
  -F "uploadfile=@fraud_training_pipeline.yaml"
```

> **Important:** Always include `?namespace=kubeflow-user-example-com` on upload. Without the namespace the pipeline will be stored globally and the KubeFlow UI will not display it under the user's Pipelines menu.

### Starting a Pipeline Run

```bash
# Get the pipeline version ID
VERSION_ID=$(curl -s \
  "http://localhost:8888/apis/v2beta1/pipelines/${PIPELINE_ID}/versions" \
  -H "kubeflow-userid: user@example.com" \
  | python3 -c "import sys,json; v=json.load(sys.stdin)['pipeline_versions']; print(v[-1]['pipeline_version_id'])")

# Get or create the experiment
curl -s -X POST "http://localhost:8888/apis/v2beta1/experiments" \
  -H "kubeflow-userid: user@example.com" \
  -H "Content-Type: application/json" \
  -d '{"display_name":"fraud-detection","namespace":"kubeflow-user-example-com"}'

EXPERIMENT_ID=$(curl -s \
  "http://localhost:8888/apis/v2beta1/experiments?namespace=kubeflow-user-example-com" \
  -H "kubeflow-userid: user@example.com" \
  | python3 -c "import sys,json; e=json.load(sys.stdin)['experiments']; \
    [print(x['experiment_id']) for x in e if x['display_name']=='fraud-detection']")

# Submit the run
curl -X POST "http://localhost:8888/apis/v2beta1/runs" \
  -H "kubeflow-userid: user@example.com" \
  -H "Content-Type: application/json" \
  -d "{
    \"display_name\": \"fraud-training-$(date +%Y%m%d-%H%M)\",
    \"experiment_id\": \"${EXPERIMENT_ID}\",
    \"pipeline_version_reference\": {
      \"pipeline_id\": \"${PIPELINE_ID}\",
      \"pipeline_version_id\": \"${VERSION_ID}\"
    }
  }"
```

### Monitoring a Run

```bash
# Watch pod status (each step runs as a separate pod)
kubectl get pods -n kubeflow-user-example-com -w

# View logs for the currently running step
kubectl logs -n kubeflow-user-example-com \
  $(kubectl get pods -n kubeflow-user-example-com --no-headers \
    | grep -v Completed | awk '{print $1}' | head -1) --follow

# Check run status via API
curl -s "http://localhost:8888/apis/v2beta1/runs?experiment_id=${EXPERIMENT_ID}" \
  -H "kubeflow-userid: user@example.com" \
  | python3 -c "import sys,json; [print(r['display_name'], r['state']) \
    for r in json.load(sys.stdin).get('runs',[])]"
```

---

## How KubeFlow Pipelines and MLFlow Relate

### During a Pipeline Run

```
KubeFlow step: train_model
│
│  calls mlflow.set_tracking_uri("http://mlflow.mlflow.svc.cluster.local:5000")
│  calls mlflow.set_experiment("fraud-detection")
│  calls mlflow.xgboost.autolog()
│  calls mlflow.start_run()
│
│  → MLFlow creates Experiment "fraud-detection" (if not exists)
│  → MLFlow creates a Run with auto-generated run_id
│  → MLFlow logs: params, metrics (AUC, accuracy), model artifact
│  → Artifact stored at: s3://mlflow-artifacts/<exp_id>/<run_id>/artifacts/xgboost-model/
│
│  KFP stores run_id in the output artifact metadata
│
KubeFlow step: register_model
│
│  reads run_id from previous step's output metadata
│  calls mlflow.register_model(model_uri=f"runs:/{run_id}/xgboost-model", name="fraud-detector")
│
│  → MLFlow Model Registry creates "fraud-detector" v1 (or increments version)
│  → Version transitioned to stage: Staging
│
KubeFlow step: deploy_kserve
│
│  reads Staging version from MLFlow Registry
│  converts source URI: mlflow-artifacts:/… → s3://mlflow-artifacts/…
│  creates/patches KServe InferenceService
```

### Key Relationship Points

- **KubeFlow is the orchestrator** — it schedules and sequences the steps, handles retries, and stores input/output artifacts between steps.
- **MLFlow is the experiment store** — it persists run metrics, parameters, and model artifacts independently of KubeFlow. MLFlow data survives pipeline re-runs and is queryable across runs.
- **MLFlow is the model source of truth** — KServe does not pull from KubeFlow. It pulls the model from the S3 path recorded in the MLFlow Model Registry. This decouples serving from the training orchestration.
- **The experiment name (`fraud-detection`) is shared** — the pipeline hardcodes `EXPERIMENT_NAME = "fraud-detection"`. If MLFlow loses this experiment (pod restart), the next pipeline run will auto-recreate it with a new `experiment_id`.

### What Survives a Pod Restart

| Data | Survives restart? | Location |
|------|------------------|----------|
| Model artifact files (`.bst`, `MLmodel`, etc.) | **Yes** | MinIO `s3://mlflow-artifacts/` |
| Experiment/run records and metrics | **No** (SQLite in pod) | MLFlow pod filesystem |
| Model Registry entries | **No** | MLFlow pod filesystem |
| KubeFlow run history | **Yes** | MySQL DB (`mlpipeline` service) |
| KServe InferenceService | **Yes** | Kubernetes resource |
| `transactions_scored` Iceberg data | **Yes** | MinIO `s3://iceberg-warehouse/` |

---

## Recovering the KServe InferenceService

If the `fraud-detector` InferenceService is missing or broken after cluster changes:

```bash
# Check status
kubectl get inferenceservice fraud-detector -n kubeflow-user-example-com

# If CrashLoopBackOff, check the storage-initializer pod logs
kubectl logs -n kubeflow-user-example-com \
  $(kubectl get pods -n kubeflow-user-example-com \
    -l serving.kserve.io/inferenceservice=fraud-detector \
    --no-headers | awk '{print $1}') \
  -c storage-initializer

# The model S3 path is in the InferenceService spec:
kubectl get inferenceservice fraud-detector -n kubeflow-user-example-com \
  -o jsonpath='{.spec.predictor.model.storageUri}'

# If the InferenceService is missing entirely, re-run the pipeline's deploy step
# or apply it manually (replace <S3_PATH> with the path from MLFlow):
kubectl apply -f - <<EOF
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: fraud-detector
  namespace: kubeflow-user-example-com
  annotations:
    sidecar.istio.io/inject: "false"
spec:
  predictor:
    serviceAccountName: kserve-sa
    model:
      modelFormat:
        name: xgboost
      storageUri: s3://mlflow-artifacts/<exp_id>/<run_id>/artifacts/xgboost-model
      resources:
        requests: {cpu: 100m, memory: 256Mi}
        limits:   {cpu: "1",  memory: 1Gi}
EOF
```

### Testing the KServe Endpoint

```bash
kubectl port-forward -n kubeflow-user-example-com svc/fraud-detector-predictor 8765:80 &

# V1 REST protocol
curl -X POST http://localhost:8765/v1/models/fraud-detector:predict \
  -H "Content-Type: application/json" \
  -d '{"instances": [[50.0, 100.0, 5.0]]}'
# → {"predictions":[8.2e-06]}  (normal transaction, near-zero fraud prob)

# V2 REST protocol (used by Flink)
curl -X POST http://localhost:8765/v2/models/fraud-detector/infer \
  -H "Content-Type: application/json" \
  -d '{"inputs":[{"name":"input-0","shape":[1,3],"datatype":"FP32","data":[[500.0,495.0,5.0]]}]}'
# → {"outputs":[{"data":[0.9999]}]}  (high-velocity, high-fraud)
```

The three input features, in order: `[amount, amount_velocity_5min, distance_from_home_km]`.

---

## Troubleshooting Quick Reference

| Symptom | Check | Fix |
|---------|-------|-----|
| Pipeline steps fail with `mlflow-artifacts` bucket error | `kubectl exec -n minio deploy/minio -- mc ls local/mlflow-artifacts/` | Create bucket: `mc mb local/mlflow-artifacts` |
| KServe storage-initializer crashes: `Cannot recognize storage type` | `kubectl logs … -c storage-initializer` | URI must be `s3://…`, not `mlflow-artifacts:/…`. Re-run pipeline with latest `deploy_kserve.py`. |
| KServe predictor crashes: `ModelMissingError` | Check S3 for `model.bst` file | `kubectl exec -n minio deploy/minio -- mc ls local/mlflow-artifacts/…/xgboost-model/` — must contain `model.bst` |
| KFP UI shows no pipelines | Pipeline uploaded without namespace | Re-upload with `?namespace=kubeflow-user-example-com` |
| MLFlow experiment missing after restart | Pod restarted, SQLite DB lost | Re-run the pipeline — it recreates the experiment. Or restore manually (see above). |
| Flink writes `-1.0` for `fraud_probability` | KServe DNS not reachable from `flink-system` | Check `fraud-detector` Service exists in `kubeflow-user-example-com`: `kubectl get svc fraud-detector -n kubeflow-user-example-com` |
| `401 Unauthorized` from KFP API | Missing `kubeflow-userid` header | Always include `-H "kubeflow-userid: user@example.com"` in API calls |
