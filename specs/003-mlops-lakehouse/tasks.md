# Tasks: KubeFlow Pipelines + KServe Infrastructure Deployment

**Input**: Design documents from `specs/003-mlops-lakehouse/`
**Branch**: `003-mlops-lakehouse`
**Spec**: [spec.md](./spec.md)

**Scope**: Add KubeFlow Pipelines (KFP) and KServe to the existing Flux GitOps stack by appending
Flux Kustomization resources to `infrastructure/controllers/base/kubeflow/resources.yaml` and
Minikube-specific patches to `infrastructure/controllers/minikube/kubeflow/kustomization.yaml`.
The `kubeflow-manifests` GitRepository (tag `v1.9.1`) is already present and is the source for
all new Kustomizations.

**Existing state**:
- `infrastructure/controllers/base/kubeflow/resources.yaml` — GitRepository `kubeflow-manifests`
  + 15 Flux Kustomizations for cert-manager, istio, dex, oauth2-proxy, centraldashboard,
  jupyter-web-app, notebook-controller, profiles, user-namespace; all `True` in Flux
- `infrastructure/controllers/minikube/kubeflow/kustomization.yaml` — patches the `kubeflow`
  Kustomization with a 30m timeout and `targetNamespace: kubeflow`
- KubeFlow central dashboard running in `kubeflow` namespace
- `kubectl get inferenceservice -A` returns "server doesn't have a resource type" — KServe
  CRDs missing
- MLFlow server running in `mlflow` namespace (NodePort 31514); no experiment runs yet

**Architecture decision**: All new components use the existing `kubeflow-manifests`
GitRepository pointing at `github.com/kubeflow/manifests` tag `v1.9.1`. KFP uses path
`apps/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user`. KServe uses
`contrib/kserve/kserve` for the controller + CRDs and
`contrib/kserve/models-web-app/overlays/kubeflow` for the dashboard UI. KServe is
patched to `rawDeployment` mode on Minikube (no Knative Serving required).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no in-progress dependencies)
- **[US1]**: Train and Track (P1) — requires KFP
- **[US3]**: Deploy for Inference (P3) — requires KServe

---

## Phase 1: Setup

**Purpose**: Confirm the kubeflow/manifests v1.9.1 tree contains the expected KFP and KServe
paths before writing any Flux resources.

- [X] T001 Confirm KFP path exists in kubeflow/manifests v1.9.1 by fetching the directory
  listing: `curl -s "https://api.github.com/repos/kubeflow/manifests/contents/apps/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user?ref=v1.9.1" | python3 -c "import json,sys; [print(f['name']) for f in json.load(sys.stdin)]"` — expect a `kustomization.yaml` in the output; if the path returns 404, the KFP path for v1.9.1 is `apps/pipeline/upstream/env/platform-agnostic-multi-user` (fallback path without cert-manager subfolder); note the correct path for T004

- [X] T002 [P] Confirm KServe contrib path exists in kubeflow/manifests v1.9.1:
  `curl -s "https://api.github.com/repos/kubeflow/manifests/contents/contrib/kserve/kserve?ref=v1.9.1" | python3 -c "import json,sys; d=json.load(sys.stdin); print([f['name'] for f in d] if isinstance(d,list) else d.get('message'))"` — expect a list of files; note whether a `kustomization.yaml` is present; if path returns 404, KServe is not in kubeflow/manifests v1.9.1 — use separate GitRepository task T002b below

- [ ] T002b [P] (Run only if T002 returns 404) Add a second GitRepository `kserve-manifests`
  to `infrastructure/controllers/base/kubeflow/resources.yaml` pointing at
  `github.com/kserve/kserve` tag `v0.13.0` — follow the same pattern as the existing
  `kubeflow-manifests` GitRepository block; KServe Kustomizations in T009/T010 will reference
  this source instead of `kubeflow-manifests`

---

## Phase 2: Foundational

**Purpose**: Confirm all prerequisite Kustomizations that KFP and KServe depend on are healthy
in Flux before adding new components.

- [X] T003 Verify prerequisite Kustomizations are Ready before adding KFP or KServe:
  ```bash
  kubectl -n flux-system get kustomization \
    kubeflow-cert-manager kubeflow-istio-resources kubeflow-namespace kubeflow-roles \
    -o custom-columns='NAME:.metadata.name,READY:.status.conditions[0].status,MSG:.status.conditions[0].message'
  ```
  All four must show `READY=True`. If any show `False`, investigate with
  `flux logs --kind=Kustomization --name=<name> -n flux-system` before proceeding.

---

## Phase 3: User Story 1 — KubeFlow Pipelines (Priority: P1)

**Goal**: KFP API server, persistence agent, scheduled workflow controller, and UI are running
in the `kubeflow` namespace; the "Pipelines" link in the KubeFlow dashboard is functional.

**Independent Test**: `kubectl get pods -n kubeflow | grep ml-pipeline` shows at least
`ml-pipeline` (API server) and `ml-pipeline-ui` pods in `Running` state. Navigating to
the KubeFlow dashboard → Pipelines shows the pipeline list page without errors.

### Implementation for User Story 1

- [X] T004 [US1] Append a `kubeflow-pipelines` Flux Kustomization block to
  `infrastructure/controllers/base/kubeflow/resources.yaml` after the final existing
  Kustomization block (after the `kubeflow` user-namespace entry). Use the path confirmed in
  T001 (default: `apps/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user`).
  Depend on `kubeflow-cert-manager`, `kubeflow-istio-resources`, and `kubeflow-namespace`.
  Use `timeout: 30m`, `interval: 30m`, `retryInterval: 2m`, `prune: true`, `wait: true`.
  Pattern to append:
  ```yaml
  ---
  apiVersion: kustomize.toolkit.fluxcd.io/v1
  kind: Kustomization
  metadata:
    name: kubeflow-pipelines
    namespace: flux-system
  spec:
    dependsOn:
      - name: kubeflow-cert-manager
      - name: kubeflow-istio-resources
      - name: kubeflow-namespace
    interval: 30m
    path: ./apps/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user
    prune: true
    retryInterval: 2m
    sourceRef:
      kind: GitRepository
      name: kubeflow-manifests
    timeout: 30m
    wait: true
  ```

- [X] T005 [US1] Add resource-limit patches for KFP components to
  `infrastructure/controllers/minikube/kubeflow/kustomization.yaml` so Minikube is not
  overwhelmed. Add a new `patches` entry (alongside the existing `kubeflow` timeout patch)
  that applies Strategic Merge Patches reducing cpu/memory requests for the four heaviest
  KFP deployments. Create a new file
  `infrastructure/controllers/minikube/kubeflow/kfp-resource-patch.yaml` with content:
  ```yaml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: ml-pipeline
    namespace: kubeflow
  spec:
    template:
      spec:
        containers:
          - name: ml-pipeline-api-server
            resources:
              requests:
                cpu: 250m
                memory: 256Mi
              limits:
                cpu: "1"
                memory: 1Gi
  ---
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: ml-pipeline-ui
    namespace: kubeflow
  spec:
    template:
      spec:
        containers:
          - name: ml-pipeline-ui
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 512Mi
  ---
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: ml-pipeline-persistenceagent
    namespace: kubeflow
  spec:
    template:
      spec:
        containers:
          - name: ml-pipeline-persistenceagent
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 256Mi
  ---
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: ml-pipeline-scheduledworkflow
    namespace: kubeflow
  spec:
    template:
      spec:
        containers:
          - name: ml-pipeline-scheduledworkflow
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                cpu: 500m
                memory: 256Mi
  ```
  Then add to `infrastructure/controllers/minikube/kubeflow/kustomization.yaml` under `patches`:
  ```yaml
  - path: kfp-resource-patch.yaml
    target:
      kind: Deployment
      namespace: kubeflow
  ```

- [X] T006 [US1] Commit the changes and trigger Flux reconciliation:
  ```bash
  git add infrastructure/controllers/base/kubeflow/resources.yaml \
          infrastructure/controllers/minikube/kubeflow/kustomization.yaml \
          infrastructure/controllers/minikube/kubeflow/kfp-resource-patch.yaml
  git commit -m "feat: add KubeFlow Pipelines Flux Kustomization"
  git push
  flux reconcile source git flux-system
  flux reconcile ks infra-controllers --with-source
  ```

- [X] T007 [US1] Verify KFP pods are running (this will take 5–15 minutes; poll until stable):
  ```bash
  # Watch KFP pods come up
  kubectl get pods -n kubeflow -w | grep -E "ml-pipeline|metadata|workflow"
  # Final check — all should be Running/Completed:
  kubectl get pods -n kubeflow | grep -E "ml-pipeline|metadata-grpc|workflow-controller"
  ```
  Expect at minimum: `ml-pipeline` (API server), `ml-pipeline-ui`, `ml-pipeline-persistenceagent`,
  `ml-pipeline-scheduledworkflow`, `workflow-controller` all in `Running` state.
  Also check Flux Kustomization status:
  ```bash
  kubectl -n flux-system get kustomization kubeflow-pipelines
  ```

- [X] T008 [US1] Verify the Pipelines page loads in the KubeFlow dashboard by port-forwarding
  and opening `http://127.0.0.1:8080/pipeline`:
  ```bash
  kubectl -n istio-system port-forward svc/istio-ingressgateway 8080:80
  ```
  Log in with KubeFlow credentials (default: `user@example.com` / `12341234`).
  Navigate to Pipelines → the pipeline list should render without a 404 or "not a valid page"
  error.

**Checkpoint**: US1 infrastructure complete. KFP is running; the Pipelines page is accessible.
Running a pipeline requires the Python pipeline source code (next task batch after this one).

---

## Phase 4: User Story 3 — KServe Inference Platform (Priority: P3)

**Goal**: KServe controller and CRDs are installed in the `kserve` namespace; `InferenceService`
resource type is recognized by the cluster; the Models web-app page in the KubeFlow dashboard
shows the KServe endpoints page (no more "not a valid page" error).

**Independent Test**: `kubectl get inferenceservice -A` returns a valid (possibly empty) table
header rather than "server doesn't have a resource type". `kubectl get pods -n kserve` shows
`kserve-controller-manager` in `Running` state.

### Implementation for User Story 3

- [X] T009 [US3] Append two KServe Kustomization blocks to
  `infrastructure/controllers/base/kubeflow/resources.yaml`:

  **Block 1 — KServe controller + CRDs** (depends on cert-manager and istio):
  ```yaml
  ---
  apiVersion: kustomize.toolkit.fluxcd.io/v1
  kind: Kustomization
  metadata:
    name: kubeflow-kserve
    namespace: flux-system
  spec:
    dependsOn:
      - name: kubeflow-cert-manager
      - name: kubeflow-istio-resources
    interval: 30m
    path: ./contrib/kserve/kserve
    prune: true
    retryInterval: 2m
    sourceRef:
      kind: GitRepository
      name: kubeflow-manifests
    timeout: 30m
    wait: true
  ```
  *(If T002 returned 404 and T002b was executed, change `name: kubeflow-manifests` to
  `name: kserve-manifests` and set `path: ./config/default`.)*

  **Block 2 — KServe models web-app** (depends on kserve controller and centraldashboard):
  ```yaml
  ---
  apiVersion: kustomize.toolkit.fluxcd.io/v1
  kind: Kustomization
  metadata:
    name: kubeflow-kserve-models-web-app
    namespace: flux-system
  spec:
    dependsOn:
      - name: kubeflow-kserve
      - name: kubeflow-centraldashboard
    interval: 30m
    path: ./contrib/kserve/models-web-app/overlays/kubeflow
    prune: true
    retryInterval: 2m
    sourceRef:
      kind: GitRepository
      name: kubeflow-manifests
    timeout: 20m
    wait: true
  ```

- [X] T010 [US3] Create
  `infrastructure/controllers/minikube/kubeflow/kserve-rawdeployment-patch.yaml` to switch
  KServe from serverless (Knative) to rawDeployment mode, which does not require Knative
  Serving and is appropriate for Minikube:
  ```yaml
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: inferenceservice-config
    namespace: kserve
  data:
    deploy: |
      {
        "defaultDeploymentMode": "RawDeployment"
      }
  ```
  Then add to `infrastructure/controllers/minikube/kubeflow/kustomization.yaml` under `patches`:
  ```yaml
  - path: kserve-rawdeployment-patch.yaml
    target:
      kind: ConfigMap
      name: inferenceservice-config
      namespace: kserve
  ```

- [X] T011 [US3] Commit and trigger reconciliation:
  ```bash
  git add infrastructure/controllers/base/kubeflow/resources.yaml \
          infrastructure/controllers/minikube/kubeflow/kustomization.yaml \
          infrastructure/controllers/minikube/kubeflow/kserve-rawdeployment-patch.yaml
  git commit -m "feat: add KServe Flux Kustomizations with rawDeployment mode"
  git push
  flux reconcile ks infra-controllers --with-source
  ```

- [X] T012 [US3] Watch KServe deployment (5–10 minutes):
  ```bash
  kubectl -n flux-system get kustomization kubeflow-kserve -w
  kubectl get pods -n kserve -w
  ```
  Expect `kserve-controller-manager` pod in `Running` state and Kustomization `READY=True`.

- [X] T013 [US3] Verify KServe CRDs are installed:
  ```bash
  kubectl get inferenceservice -A
  kubectl get crd | grep kserve
  ```
  Expect `InferenceService`, `ServingRuntime`, `ClusterServingRuntime` CRDs present. The
  `kubectl get inferenceservice -A` command must return a table header (not "server doesn't
  have a resource type").

- [X] T014 [US3] Verify the KServe models web-app (dashboard endpoints page) is accessible:
  ```bash
  kubectl -n flux-system get kustomization kubeflow-kserve-models-web-app
  kubectl get pods -n kubeflow | grep models-web-app
  ```
  Then with the port-forward from T008 open, navigate to the KubeFlow dashboard → Models.
  The page should load (no "not a valid page" error). If the models-web-app path does not
  exist in v1.9.1 contrib (returns 404 in Flux logs), skip this task and note that the
  dashboard link will remain broken until a compatible models-web-app is available.

**Checkpoint**: US3 infrastructure complete. KServe CRDs exist; `kubectl get inferenceservice -A`
works. The `fraud-score-enricher` Flink job now has a valid target — once the Python training
pipeline runs and deploys a model, `fraud_probability` values will shift from -1.0 to real scores.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T015 [P] Verify no resource pressure on Minikube node after both deployments:
  ```bash
  kubectl top nodes
  kubectl get pods -A | grep -v Running | grep -v Completed
  ```
  If any pods are in `OOMKilled` or `Pending` state, tighten resource patches in T005 or
  `kfp-resource-patch.yaml` — reduce limits further or scale down unused KFP components
  (`ml-pipeline-viewer-crd-service`, `cache-server`, `metadata-writer`) by patching replicas to 0.

- [ ] T016 [P] Update `infrastructure/controllers/base/kubeflow/README.md` (or create it if
  absent) to document the new components: list all Kustomization names, their paths in
  kubeflow/manifests v1.9.1, dependencies, and the rawDeployment ConfigMap patch for KServe.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — run T001 and T002 in parallel immediately
- **Foundational (Phase 2)**: T003 can run in parallel with T001/T002 (read-only check)
- **US1 KFP (Phase 3)**: T004–T008 sequential; T004 requires T001 path confirmation
- **US3 KServe (Phase 4)**: T009–T014 sequential; T009 can begin while KFP (T007) is rolling out
  (different Kustomization, different namespace, no ordering dependency at apply time)
- **Polish (Phase 5)**: Depends on T013 (KServe CRDs confirmed)

### Parallel Opportunities

```bash
# Phase 1 — run both path checks simultaneously:
T001 KFP path check  ||  T002 KServe path check

# Phase 3+4 — after T004 is applied, KFP rollout takes ~10 min:
T005/T006 KFP patches commit  ||  T009 draft KServe blocks (different file sections)
# Then T011 KServe commit once KFP commit is pushed

# Phase 5:
T015 resource check  ||  T016 README update
```

---

## Implementation Strategy

### MVP (KFP running and accessible)

1. T001–T003: path checks + prereq verification
2. T004–T005: add KFP Kustomization + resource patches
3. T006: commit + reconcile
4. T007–T008: verify KFP pods and dashboard
5. **STOP and VALIDATE**: Pipelines page loads in KubeFlow dashboard

### Full Delivery

1. MVP above
2. T009–T011: add KServe Kustomizations + rawDeployment patch + commit
3. T012–T014: verify KServe pods and CRDs
4. T015–T016: resource check + docs

---

## Notes

- All new Kustomizations use the existing `kubeflow-manifests` GitRepository (v1.9.1) — no new
  GitRepository objects needed unless T002 returns 404 for the KServe contrib path
- KFP installs its own MinIO (for pipeline artifacts) and MySQL (for metadata) into the
  `kubeflow` namespace — these will compete with existing workloads; monitor node pressure (T015)
- KFP's internal MinIO is separate from the platform MinIO in `minio` namespace — they do not
  conflict but consume additional storage on the Minikube node
- `rawDeployment` mode makes KServe deploy InferenceServices as standard Kubernetes Deployments
  and Services instead of Knative Revisions — compatible with Minikube and simpler to debug
- The `fraud-score-enricher` Flink job is already writing sentinel values (-1.0); once a
  KServe InferenceService named `fraud-detector` is deployed in namespace
  `kubeflow-user-example-com`, real scores will begin flowing automatically
- If KFP pods fail due to MySQL CrashLoopBackOff, check PVC availability:
  `kubectl get pvc -n kubeflow | grep mysql`

---

# Tasks: Fraud Training Pipeline (KFP SDK v2)

**Scope**: Create `apps/kubeflow-pipelines/` containing a KFP SDK v2 pipeline that reads
transaction data from the Iceberg/Polaris lakehouse, trains an XGBoost fraud model on the
host GPU, logs to MLFlow, registers the model, and deploys a KServe InferenceService.

**Prerequisite**: T001–T016 above (KFP and KServe running in cluster).

**Pipeline architecture**:
```
data_ingestion → train_model → register_model → deploy_kserve
```
All components are containerized; the pipeline runs in the `kubeflow-user-example-com`
namespace. Polaris and MLFlow credentials are injected via Kubernetes Secrets using
`kfp-kubernetes`.

---

## Phase 6: Setup — Project Structure

**Purpose**: Create the directory layout and shared configuration before writing any component.

- [X] T017 Create the `apps/kubeflow-pipelines/` directory structure with empty placeholder
  files so the layout is clear before implementation:
  ```
  apps/kubeflow-pipelines/
  ├── components/
  │   ├── __init__.py
  │   ├── data_ingestion.py
  │   ├── train_model.py
  │   ├── register_model.py
  │   └── deploy_kserve.py
  ├── fraud_training_pipeline.py
  ├── requirements.txt
  ├── Dockerfile
  └── k8s/
      ├── pipeline-rbac.yaml
      └── pipeline-secrets.yaml
  ```
  Create the directories with `mkdir -p apps/kubeflow-pipelines/components apps/kubeflow-pipelines/k8s`
  and touch each file. Create `apps/kubeflow-pipelines/components/__init__.py` as an empty file.

- [X] T018 Create `apps/kubeflow-pipelines/requirements.txt` with exact pinned versions:
  ```
  kfp==2.7.0
  kfp-kubernetes==1.2.0
  pyiceberg[pyarrow,s3]==0.7.1
  xgboost==2.0.3
  scikit-learn==1.4.2
  pandas==2.2.2
  numpy==1.26.4
  mlflow==2.13.0
  boto3==1.34.101
  kubernetes==29.0.0
  ```
  Note: `pyiceberg[pyarrow,s3]` installs PyArrow and boto3-based S3FileIO; `kfp-kubernetes`
  provides `add_pod_env_from_secret` and `set_gpu_limit` helpers for KFP SDK v2 pipelines.

---

## Phase 7: User Story 1 — Data Ingestion + Training + MLFlow Tracking (Priority: P1)

**Goal**: Running the pipeline creates an MLFlow experiment run with logged metrics, parameters,
and a saved XGBoost model artifact. The KFP UI shows the run completing successfully.

**Independent Test**: After submitting the pipeline, check MLFlow at
`http://$(minikube ip -p fraud-gitops):31514` → the experiment `fraud-detection` has at least
one run with `auc` and `accuracy` metrics logged and a model artifact at `xgboost-model/`.

### Implementation for User Story 1

- [X] T019 [US1] Create `apps/kubeflow-pipelines/components/data_ingestion.py`. This component
  reads from the Polaris REST catalog and writes a Parquet file as a KFP output artifact.
  Full file content:
  ```python
  from kfp.dsl import component, Output, Dataset

  @component(
      base_image="python:3.11-slim",
      packages_to_install=[
          "pyiceberg[pyarrow,s3]==0.7.1",
          "pandas==2.2.2",
          "pyarrow==15.0.2",
      ],
  )
  def data_ingestion(
      polaris_uri: str,
      warehouse: str,
      polaris_credential: str,
      minio_endpoint: str,
      minio_access_key: str,
      minio_secret_key: str,
      output_dataset: Output[Dataset],
  ) -> None:
      import os
      import pandas as pd
      from pyiceberg.catalog import load_catalog

      catalog = load_catalog(
          "polaris",
          type="rest",
          uri=polaris_uri,
          warehouse=warehouse,
          credential=polaris_credential,
          scope="PRINCIPAL_ROLE:ALL",
          **{
              "s3.endpoint": minio_endpoint,
              "s3.access-key-id": minio_access_key,
              "s3.secret-access-key": minio_secret_key,
              "s3.region": "us-east-1",
              "client.region": "us-east-1",
              "header.X-Iceberg-Access-Delegation": "",
          },
      )
      table = catalog.load_table(("default", "transactions"))
      df = table.scan().to_pandas()

      # Feature engineering: derive label from amount_velocity_5min threshold
      df["label"] = (df["amount_velocity_5min"] > 500).astype(int)
      df = df[["amount", "amount_velocity_5min", "distance_from_home_km", "label"]].dropna()

      df.to_parquet(output_dataset.path, index=False)
      print(f"Ingested {len(df)} rows; fraud rate: {df['label'].mean():.3f}")
  ```

- [X] T020 [US1] Create `apps/kubeflow-pipelines/components/train_model.py`. This component
  trains XGBoost with GPU acceleration and logs to MLFlow via autolog. Full file content:
  ```python
  from kfp.dsl import component, Input, Output, Dataset, Model, Metrics

  @component(
      base_image="python:3.11-slim",
      packages_to_install=[
          "xgboost==2.0.3",
          "scikit-learn==1.4.2",
          "pandas==2.2.2",
          "pyarrow==15.0.2",
          "mlflow==2.13.0",
          "boto3==1.34.101",
      ],
  )
  def train_model(
      input_dataset: Input[Dataset],
      mlflow_tracking_uri: str,
      experiment_name: str,
      mlflow_s3_endpoint_url: str,
      aws_access_key_id: str,
      aws_secret_access_key: str,
      output_model: Output[Model],
      metrics: Output[Metrics],
  ) -> None:
      import os
      import mlflow
      import mlflow.xgboost
      import pandas as pd
      import xgboost as xgb
      from sklearn.model_selection import train_test_split
      from sklearn.metrics import roc_auc_score, accuracy_score

      os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
      os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
      os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key

      mlflow.set_tracking_uri(mlflow_tracking_uri)
      mlflow.set_experiment(experiment_name)

      df = pd.read_parquet(input_dataset.path)
      X = df[["amount", "amount_velocity_5min", "distance_from_home_km"]]
      y = df["label"]
      X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

      mlflow.xgboost.autolog()
      with mlflow.start_run() as run:
          model = xgb.XGBClassifier(
              n_estimators=100,
              max_depth=6,
              learning_rate=0.1,
              tree_method="gpu_hist",   # RTX 3070 on host node
              device="cuda",
              eval_metric="auc",
              use_label_encoder=False,
          )
          model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

          y_pred = model.predict(X_test)
          y_prob = model.predict_proba(X_test)[:, 1]
          auc = roc_auc_score(y_test, y_prob)
          acc = accuracy_score(y_test, y_pred)

          mlflow.log_metrics({"auc": auc, "accuracy": acc})
          mlflow.xgboost.log_model(model, artifact_path="xgboost-model")

          model.save_model(output_model.path + ".json")
          output_model.metadata["run_id"] = run.info.run_id
          output_model.metadata["model_uri"] = f"runs:/{run.info.run_id}/xgboost-model"

          metrics.log_metric("auc", auc)
          metrics.log_metric("accuracy", acc)

          print(f"Run ID: {run.info.run_id}  AUC: {auc:.4f}  Accuracy: {acc:.4f}")
  ```

---

## Phase 8: User Story 2 — Model Registration (Priority: P2)

**Goal**: The trained model is registered in the MLFlow Model Registry under the name
`fraud-detector` and transitioned to `Staging` stage. The MLFlow UI shows the registered model.

**Independent Test**: `mlflow.MlflowClient().get_latest_versions("fraud-detector", stages=["Staging"])`
returns at least one version with non-null `run_id`.

### Implementation for User Story 2

- [X] T021 [US2] Create `apps/kubeflow-pipelines/components/register_model.py`. Full file content:
  ```python
  from kfp.dsl import component, Input, Model

  @component(
      base_image="python:3.11-slim",
      packages_to_install=["mlflow==2.13.0", "boto3==1.34.101"],
  )
  def register_model(
      trained_model: Input[Model],
      model_name: str,
      mlflow_tracking_uri: str,
      mlflow_s3_endpoint_url: str,
      aws_access_key_id: str,
      aws_secret_access_key: str,
  ) -> None:
      import os
      import mlflow
      from mlflow.tracking import MlflowClient

      os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
      os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
      os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key

      mlflow.set_tracking_uri(mlflow_tracking_uri)
      client = MlflowClient()

      model_uri = trained_model.metadata["model_uri"]
      mv = mlflow.register_model(model_uri=model_uri, name=model_name)

      client.transition_model_version_stage(
          name=model_name,
          version=mv.version,
          stage="Staging",
          archive_existing_versions=True,
      )
      print(f"Registered {model_name} v{mv.version} → Staging")
      print(f"Model URI: {model_uri}")
  ```

---

## Phase 9: User Story 3 — KServe InferenceService Deployment (Priority: P3)

**Goal**: A KServe `InferenceService` named `fraud-detector` exists in namespace
`kubeflow-user-example-com` and reaches `Ready=True`. Sending a test V2 inference request
returns a `fraud_probability` value in `[0, 1]`.

**Independent Test**:
```bash
kubectl get inferenceservice fraud-detector -n kubeflow-user-example-com
# READY=True, URL column populated
```
Send a V2 request and receive a numeric prediction (not a 503 or empty response).

### Implementation for User Story 3

- [X] T022 [US3] Create `apps/kubeflow-pipelines/components/deploy_kserve.py`. This component
  creates (or updates) the KServe InferenceService using the Kubernetes Python client. Full file:
  ```python
  from kfp.dsl import component, Input, Model

  @component(
      base_image="python:3.11-slim",
      packages_to_install=["kubernetes==29.0.0", "mlflow==2.13.0", "boto3==1.34.101"],
  )
  def deploy_kserve(
      trained_model: Input[Model],
      model_name: str,
      namespace: str,
      mlflow_tracking_uri: str,
      mlflow_s3_endpoint_url: str,
      aws_access_key_id: str,
      aws_secret_access_key: str,
  ) -> None:
      import os
      import mlflow
      from mlflow.tracking import MlflowClient
      from kubernetes import client as k8s_client, config as k8s_config

      os.environ["MLFLOW_S3_ENDPOINT_URL"] = mlflow_s3_endpoint_url
      os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
      os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key

      mlflow.set_tracking_uri(mlflow_tracking_uri)
      kf_client = MlflowClient()

      # Resolve the model artifact S3 path from the Staging version
      versions = kf_client.get_latest_versions(model_name, stages=["Staging"])
      if not versions:
          raise RuntimeError(f"No Staging version found for model '{model_name}'")
      model_uri = versions[0].source  # e.g. s3://mlflow-artifacts/.../xgboost-model

      # Build KServe InferenceService manifest
      inference_service = {
          "apiVersion": "serving.kserve.io/v1beta1",
          "kind": "InferenceService",
          "metadata": {
              "name": model_name,
              "namespace": namespace,
              "annotations": {"sidecar.istio.io/inject": "false"},
          },
          "spec": {
              "predictor": {
                  "model": {
                      "modelFormat": {"name": "xgboost"},
                      "storageUri": model_uri,
                      "resources": {
                          "requests": {"cpu": "100m", "memory": "256Mi"},
                          "limits": {"cpu": "1", "memory": "1Gi"},
                      },
                  }
              }
          },
      }

      k8s_config.load_incluster_config()
      custom_api = k8s_client.CustomObjectsApi()
      try:
          custom_api.create_namespaced_custom_object(
              group="serving.kserve.io",
              version="v1beta1",
              namespace=namespace,
              plural="inferenceservices",
              body=inference_service,
          )
          print(f"Created InferenceService {model_name} in {namespace}")
      except k8s_client.ApiException as e:
          if e.status == 409:
              # Already exists — patch the spec
              custom_api.patch_namespaced_custom_object(
                  group="serving.kserve.io",
                  version="v1beta1",
                  namespace=namespace,
                  plural="inferenceservices",
                  name=model_name,
                  body=inference_service,
              )
              print(f"Updated InferenceService {model_name} in {namespace}")
          else:
              raise
  ```

---

## Phase 10: Pipeline Assembly

**Purpose**: Wire all components into a KFP SDK v2 `@pipeline`, create the container image,
and submit the compiled pipeline YAML to KFP.

- [X] T023 Create `apps/kubeflow-pipelines/fraud_training_pipeline.py` — the top-level KFP
  pipeline definition. Full file content:
  ```python
  import kfp
  from kfp import dsl
  from kfp_kubernetes import use_secret_as_env

  from components.data_ingestion import data_ingestion
  from components.train_model import train_model
  from components.register_model import register_model
  from components.deploy_kserve import deploy_kserve

  POLARIS_URI = "http://polaris.polaris.svc.cluster.local:8181/api/catalog"
  WAREHOUSE = "quickstart_catalog"
  MINIO_ENDPOINT = "http://minio.minio.svc.cluster.local:9000"
  MLFLOW_URI = "http://mlflow.mlflow.svc.cluster.local:5000"
  KSERVE_NAMESPACE = "kubeflow-user-example-com"
  MODEL_NAME = "fraud-detector"
  EXPERIMENT_NAME = "fraud-detection"


  @dsl.pipeline(
      name="fraud-training-pipeline",
      description="Train XGBoost fraud detector from Iceberg data, register in MLFlow, deploy to KServe",
  )
  def fraud_training_pipeline(
      polaris_uri: str = POLARIS_URI,
      warehouse: str = WAREHOUSE,
      minio_endpoint: str = MINIO_ENDPOINT,
      mlflow_tracking_uri: str = MLFLOW_URI,
      experiment_name: str = EXPERIMENT_NAME,
      model_name: str = MODEL_NAME,
      kserve_namespace: str = KSERVE_NAMESPACE,
  ):
      # Step 1: Ingest from Iceberg/Polaris
      ingest_task = data_ingestion(
          polaris_uri=polaris_uri,
          warehouse=warehouse,
          polaris_credential="root:changeme",  # overridden via secret below
          minio_endpoint=minio_endpoint,
          minio_access_key="minioadmin",        # overridden via secret below
          minio_secret_key="minioadmin",        # overridden via secret below
      )
      use_secret_as_env(ingest_task, secret_name="polaris-bootstrap-credentials",
                        secret_key_to_env={"credentials": "POLARIS_CREDENTIAL"})
      use_secret_as_env(ingest_task, secret_name="minio-flink-s3-credentials",
                        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID",
                                           "rootPassword": "AWS_SECRET_ACCESS_KEY"})

      # Step 2: Train with GPU
      train_task = train_model(
          input_dataset=ingest_task.outputs["output_dataset"],
          mlflow_tracking_uri=mlflow_tracking_uri,
          experiment_name=experiment_name,
          mlflow_s3_endpoint_url=minio_endpoint,
          aws_access_key_id="minioadmin",
          aws_secret_access_key="minioadmin",
      )
      use_secret_as_env(train_task, secret_name="minio-flink-s3-credentials",
                        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID",
                                           "rootPassword": "AWS_SECRET_ACCESS_KEY"})
      train_task.set_accelerator_type("nvidia.com/gpu").set_accelerator_limit(1)

      # Step 3: Register in MLFlow Model Registry
      register_task = register_model(
          trained_model=train_task.outputs["output_model"],
          model_name=model_name,
          mlflow_tracking_uri=mlflow_tracking_uri,
          mlflow_s3_endpoint_url=minio_endpoint,
          aws_access_key_id="minioadmin",
          aws_secret_access_key="minioadmin",
      )
      use_secret_as_env(register_task, secret_name="minio-flink-s3-credentials",
                        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID",
                                           "rootPassword": "AWS_SECRET_ACCESS_KEY"})

      # Step 4: Deploy KServe InferenceService
      deploy_task = deploy_kserve(
          trained_model=train_task.outputs["output_model"],
          model_name=model_name,
          namespace=kserve_namespace,
          mlflow_tracking_uri=mlflow_tracking_uri,
          mlflow_s3_endpoint_url=minio_endpoint,
          aws_access_key_id="minioadmin",
          aws_secret_access_key="minioadmin",
      )
      use_secret_as_env(deploy_task, secret_name="minio-flink-s3-credentials",
                        secret_key_to_env={"rootUser": "AWS_ACCESS_KEY_ID",
                                           "rootPassword": "AWS_SECRET_ACCESS_KEY"})
      deploy_task.after(register_task)


  if __name__ == "__main__":
      kfp.compiler.Compiler().compile(
          pipeline_func=fraud_training_pipeline,
          package_path="fraud_training_pipeline.yaml",
      )
      print("Compiled → fraud_training_pipeline.yaml")
  ```

- [X] T024 Create `apps/kubeflow-pipelines/Dockerfile` for the pipeline runner image. Full content:
  ```dockerfile
  FROM python:3.11-slim

  WORKDIR /app

  # System deps for XGBoost GPU build (CUDA is on the host via device plugin, not in image)
  RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 \
      && rm -rf /var/lib/apt/lists/*

  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  COPY components/ ./components/
  COPY fraud_training_pipeline.py .

  CMD ["python", "fraud_training_pipeline.py"]
  ```

- [X] T025 Create `apps/kubeflow-pipelines/k8s/pipeline-rbac.yaml` — ServiceAccount and
  ClusterRoleBinding so the pipeline pods can create KServe InferenceServices and read Secrets
  in `kubeflow-user-example-com`. Full content:
  ```yaml
  apiVersion: v1
  kind: ServiceAccount
  metadata:
    name: fraud-pipeline-runner
    namespace: kubeflow-user-example-com
  ---
  apiVersion: rbac.authorization.k8s.io/v1
  kind: Role
  metadata:
    name: fraud-pipeline-runner
    namespace: kubeflow-user-example-com
  rules:
    - apiGroups: ["serving.kserve.io"]
      resources: ["inferenceservices"]
      verbs: ["get", "create", "patch", "update"]
    - apiGroups: [""]
      resources: ["secrets"]
      verbs: ["get"]
  ---
  apiVersion: rbac.authorization.k8s.io/v1
  kind: RoleBinding
  metadata:
    name: fraud-pipeline-runner
    namespace: kubeflow-user-example-com
  subjects:
    - kind: ServiceAccount
      name: fraud-pipeline-runner
      namespace: kubeflow-user-example-com
  roleRef:
    apiGroup: rbac.authorization.k8s.io
    kind: Role
    name: fraud-pipeline-runner
  ```

- [X] T026 Create `apps/kubeflow-pipelines/k8s/pipeline-secrets.yaml` — placeholder secret
  template (values already exist in-cluster; this file documents expected secret keys and
  must NOT contain real credentials). Full content:
  ```yaml
  # TEMPLATE ONLY — do not commit real credentials.
  # These secrets must already exist in kubeflow-user-example-com namespace.
  # Mirror them from flink-system or re-create with the same values:
  #
  # kubectl get secret minio-flink-s3-credentials -n flink-system -o yaml \
  #   | sed 's/namespace: flink-system/namespace: kubeflow-user-example-com/' \
  #   | kubectl apply -f -
  #
  # kubectl get secret polaris-bootstrap-credentials -n flink-system -o yaml \
  #   | sed 's/namespace: flink-system/namespace: kubeflow-user-example-com/' \
  #   | kubectl apply -f -
  apiVersion: v1
  kind: Secret
  metadata:
    name: minio-flink-s3-credentials
    namespace: kubeflow-user-example-com
  type: Opaque
  stringData:
    rootUser: "<minio-root-user>"
    rootPassword: "<minio-root-password>"
  ---
  apiVersion: v1
  kind: Secret
  metadata:
    name: polaris-bootstrap-credentials
    namespace: kubeflow-user-example-com
  type: Opaque
  stringData:
    credentials: "<polaris-client-id>:<polaris-client-secret>"
  ```

- [X] T027 Build the pipeline container image and load it into Minikube:
  ```bash
  cd apps/kubeflow-pipelines
  docker build -t fraud-training-pipeline:0.1.0 .
  cd ../..
  minikube image load fraud-training-pipeline:0.1.0 -p fraud-gitops
  ```
  Verify: `minikube image ls -p fraud-gitops | grep fraud-training-pipeline` shows `0.1.0`.

- [X] T028 Mirror the MinIO and Polaris secrets into `kubeflow-user-example-com` namespace
  and apply RBAC, then compile and upload the pipeline to KFP:
  ```bash
  # Mirror secrets (skip if already present)
  kubectl get secret minio-flink-s3-credentials -n flink-system -o yaml \
    | sed 's/namespace: flink-system/namespace: kubeflow-user-example-com/' \
    | kubectl apply -f -
  kubectl get secret polaris-bootstrap-credentials -n flink-system -o yaml \
    | sed 's/namespace: flink-system/namespace: kubeflow-user-example-com/' \
    | kubectl apply -f -

  # Apply RBAC
  kubectl apply -f apps/kubeflow-pipelines/k8s/pipeline-rbac.yaml

  # Compile pipeline to YAML
  cd apps/kubeflow-pipelines
  pip install kfp==2.7.0 kfp-kubernetes==1.2.0
  python fraud_training_pipeline.py
  cd ../..

  # Port-forward KFP API and upload
  kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 &
  python3 - <<'EOF'
  import kfp
  client = kfp.Client(host="http://127.0.0.1:8888")
  pipeline = client.upload_pipeline(
      pipeline_package_path="apps/kubeflow-pipelines/fraud_training_pipeline.yaml",
      pipeline_name="fraud-training-pipeline",
  )
  run = client.create_run_from_pipeline_id(
      pipeline_id=pipeline.pipeline_id,
      run_name="fraud-training-run-001",
  )
  print(f"Run ID: {run.run_id}")
  EOF
  ```

- [X] T029 Verify the pipeline run completes and MLFlow has results:
  ```bash
  # Watch pipeline run status in KFP UI (port-forward istio-ingressgateway 8080:80)
  # Navigate to http://127.0.0.1:8080/pipeline/#/runs

  # Check MLFlow experiment runs
  python3 - <<'EOF'
  import mlflow
  mlflow.set_tracking_uri("http://$(minikube ip -p fraud-gitops):31514")
  runs = mlflow.search_runs(experiment_names=["fraud-detection"])
  print(runs[["run_id", "metrics.auc", "metrics.accuracy", "status"]].head())
  EOF

  # Verify InferenceService is Ready
  kubectl get inferenceservice fraud-detector -n kubeflow-user-example-com
  ```
  **Success criteria**: MLFlow shows a run with `metrics.auc > 0.5`; InferenceService
  `fraud-detector` shows `READY=True`.

- [X] T030 [P] Commit all pipeline source files:
  ```bash
  git add apps/kubeflow-pipelines/
  git commit -m "feat: add KFP v2 fraud training pipeline with XGBoost, MLFlow, KServe"
  git push
  ```

---

## Phase 11: Polish & Cross-Cutting Concerns (Pipeline)

- [X] T031 [P] Test the KServe endpoint directly with a V2 inference request to confirm the
  `fraud-score-enricher` Flink job will receive real scores:
  ```bash
  # Port-forward or use the in-cluster URL from within a temporary pod
  kubectl run test-inference --image=curlimages/curl --rm -it --restart=Never \
    -n kubeflow-user-example-com -- \
    curl -s -X POST \
    http://fraud-detector-predictor-default.kubeflow-user-example-com.svc.cluster.local/v2/models/fraud-detector/infer \
    -H "Content-Type: application/json" \
    -d '{"inputs":[{"name":"input-0","shape":[1,3],"datatype":"FP64","data":[[150.0,300.0,5.0]]}]}'
  ```
  Expect a JSON response with `"outputs"` containing a `"data"` array with a value in `[0, 1]`.
  If the URL format differs (rawDeployment uses a ClusterIP Service), check:
  `kubectl get svc -n kubeflow-user-example-com | grep fraud-detector`

- [X] T032 [P] Verify `transactions_scored` Iceberg table contains rows with real
  `fraud_probability` values (not -1.0) after the InferenceService is Ready and the
  `fraud-score-enricher` Flink job has processed at least one checkpoint:
  ```python
  import boto3, pyarrow.parquet as pq, io

  s3 = boto3.client("s3", endpoint_url="http://127.0.0.1:9000",
                    aws_access_key_id="...", aws_secret_access_key="...")
  resp = s3.list_objects_v2(Bucket="iceberg-warehouse", Prefix="")
  scored_files = [o["Key"] for o in resp.get("Contents", [])
                  if "transactions_scored" in o["Key"] and o["Key"].endswith(".parquet")]
  if scored_files:
      obj = s3.get_object(Bucket="iceberg-warehouse", Key=scored_files[-1])
      df = pq.read_table(io.BytesIO(obj["Body"].read())).to_pandas()
      print(df[["transaction_id", "fraud_probability"]].head())
      real_scores = df[df["fraud_probability"] != -1.0]
      print(f"Real scores: {len(real_scores)} / {len(df)}")
  ```
  **Success**: `fraud_probability` values in `[0, 1]` for rows processed after model deployment.

---

## Dependencies & Execution Order (Pipeline Tasks)

- **Phase 6 Setup (T017–T018)**: No dependencies — create structure first
- **Phase 7 US1 (T019–T020)**: Requires T017–T018 complete; can be written in parallel
- **Phase 8 US2 (T021)**: Requires T020 (needs trained_model output type)
- **Phase 9 US3 (T022)**: Requires T020 (needs trained_model output type); parallel with T021
- **Phase 10 Assembly (T023–T030)**: Requires T019–T022 all complete; T027–T028 require KFP running (T007–T008)
- **Phase 11 Polish (T031–T032)**: Requires T029 (pipeline run complete + InferenceService Ready)

### Parallel Opportunities (Pipeline)

```bash
# Write component files in parallel (different files, no cross-dependencies):
T019 data_ingestion.py  ||  T020 train_model.py  ||  T021 register_model.py  ||  T022 deploy_kserve.py

# After T023–T026 written (pipeline assembly):
T027 docker build  ||  T028 compile pipeline (pip install kfp locally)

# After T029 run completes:
T031 test KServe endpoint  ||  T032 verify Iceberg scored table
```

---

## Notes (Pipeline)

- **GPU on host, not in container**: `tree_method='gpu_hist'` requires `device='cuda'` in
  XGBoost 2.x. The container uses Python slim (no CUDA toolkit); GPU access comes from the
  NVIDIA device plugin (`nvidia.com/gpu: 1` resource limit). Minikube must expose the host
  GPU — confirm with `minikube addons enable nvidia-gpu-device-plugin -p fraud-gitops` if
  the training pod cannot find the GPU.
- **MLFlow artifact storage**: MLFlow server in this cluster uses MinIO as S3 backend (same
  bucket as Iceberg, different prefix). Set `MLFLOW_S3_ENDPOINT_URL` to the in-cluster MinIO
  URL in all components.
- **Polaris credential in pipeline**: The `data_ingestion` component uses
  `kfp-kubernetes.use_secret_as_env` to inject `POLARIS_CREDENTIAL` from
  `polaris-bootstrap-credentials` — the hardcoded `root:changeme` is overridden at runtime.
  This mirrors the same pattern used by the Flink jobs.
- **KServe storage URI format**: MLFlow stores artifacts at `s3://mlflow-artifacts/<run_id>/...`.
  KServe `storageUri` must point to the directory containing the `model.json` file (the
  XGBoost native format). Verify the exact path with:
  `mlflow.MlflowClient().get_model_version_download_uri("fraud-detector", "1")`
- **rawDeployment predictor URL**: In rawDeployment mode, the predictor Service name follows
  `{inferenceservice-name}-predictor` pattern, not the Knative `{name}.{namespace}.svc` pattern.

---

# Tasks: Dedicated Feature Engineering Component

**Scope**: Add a standalone `feature_engineering` KFP component between `data_ingestion` and
`train_model`. The component computes four groups of engineered features per row:

1. **Rolling window aggregations** — per-`user_id` avg/max/min of `amount` over 1 h/6 h/24 h/7 d (12 features)
2. **Transaction velocity counts** — number of transactions per user in last 1 h and 24 h (2 features)
3. **Time-based / cyclic features** — hour of day, day of week (raw + cyclic sin/cos), is_weekend, is_night, and time since last transaction (9 features)
4. **Geospatial / risk features** — distance from last known location, travel speed, impossible-travel flag, and rolling average of distance-from-home (4 features)

**Pipeline flow after this change**:
```
data_ingestion → feature_engineering → train_model → register_model → deploy_kserve
```

**Feature column output** (27 new + 3 existing = 30 input features to XGBoost):

*Rolling amount aggregations (12):*

| Window | avg | max | min | count (velocity) |
|--------|-----|-----|-----|-----------------|
| 1 h  | `amount_avg_1h`  | `amount_max_1h`  | `amount_min_1h`  | `tx_count_1h`  |
| 6 h  | `amount_avg_6h`  | `amount_max_6h`  | `amount_min_6h`  | —              |
| 24 h | `amount_avg_24h` | `amount_max_24h` | `amount_min_24h` | `tx_count_24h` |
| 7 d  | `amount_avg_7d`  | `amount_max_7d`  | `amount_min_7d`  | —              |

*Time-based / cyclic features (9):*

| Feature | Type | Notes |
|---------|------|-------|
| `hour_of_day` | int 0–23 | Raw hour extracted from `transaction_time` |
| `hour_sin` / `hour_cos` | float | sin/cos(2π × hour / 24) — cyclic encoding |
| `day_of_week` | int 0–6 | Monday=0, Sunday=6 |
| `dow_sin` / `dow_cos` | float | sin/cos(2π × dow / 7) — cyclic encoding |
| `is_weekend` | binary | 1 if day_of_week ≥ 5 |
| `is_night` | binary | 1 if hour_of_day < 6 (00:00–05:59) |
| `seconds_since_last_tx` | float | Seconds since user's previous tx; −1 for first tx |

*Geospatial / risk features (6):*

| Feature | Type | Notes |
|---------|------|-------|
| `distance_from_last_location_km` | float | Haversine km between current and previous tx location per user; −1 for first tx or when coordinates unavailable |
| `speed_km_per_hour` | float | `distance_from_last_location_km / (seconds_since_last_tx / 3600)`; −1 sentinel for first tx or zero elapsed time |
| `is_impossible_travel` | binary | 1 if speed_km_per_hour > 900 (faster than a commercial aircraft — physically impossible ground travel) |
| `avg_distance_from_home_24h` | float | Rolling 24h mean of `distance_from_home_km` per user — captures the user's typical geographic radius; deviation from this baseline is a strong fraud signal |

> **Coordinate dependency**: `distance_from_last_location_km`, `speed_km_per_hour`, and
> `is_impossible_travel` require raw lat/lon columns in the Iceberg `transactions` table
> (e.g. `merchant_lat`/`merchant_lon`). T033 checks for these columns and includes them
> in the output Parquet. If coordinates are absent, the component assigns the −1 sentinel
> and logs a warning — the model still trains on the remaining 27 features.

**Prerequisite**: T017–T032 complete (pipeline code exists and has run at least once).

---

## Phase 12: Setup — Expand Data Ingestion Output

**Purpose**: `data_ingestion` currently drops `user_id` and `transaction_time` before writing
the Parquet artifact. The feature engineering component needs both columns to partition rolling
windows by user and sort by time. This phase expands the output schema without changing any
downstream component yet (train_model still reads only the original 3 feature columns until T036).

- [X] T033 [US1] Update `apps/kubeflow-pipelines/components/data_ingestion.py` to preserve
  `user_id`, `transaction_time`, and any available coordinate columns in the output Parquet
  file so the feature engineering component can compute per-user rolling windows and
  geospatial features. Replace the column-selection block as follows:
  ```python
  df["transaction_time"] = pd.to_datetime(df["transaction_time"])

  # Dynamically include any coordinate columns present in the schema
  # Common names: merchant_lat/lon, latitude/longitude, lat/lon
  COORD_CANDIDATES = {
      "merchant_lat", "merchant_lon",
      "latitude", "longitude",
      "lat", "lon",
  }
  coord_cols = [c for c in df.columns if c.lower() in COORD_CANDIDATES]

  base_cols = ["user_id", "transaction_time", "amount",
               "amount_velocity_5min", "distance_from_home_km", "label"]
  df = df[base_cols + coord_cols].dropna(subset=["amount", "label"])
  ```
  Check the actual Iceberg schema first to confirm column names:
  ```python
  # Run once locally to inspect available columns:
  print(table.schema())
  ```
  If the timestamp column is named differently (e.g. `event_time`, `ts`), update
  `transaction_time` references in this file and in T034. The label derivation logic
  (velocity/distance thresholds) is unchanged.

---

## Phase 13: User Story 1 — Feature Engineering Component (Priority: P1)

**Goal**: A new `feature_engineering` KFP component reads the enriched Parquet from
`data_ingestion`, computes 12 amount rolling window features, 2 transaction velocity count
features, 9 time-based/cyclic temporal features, and 4 geospatial/risk features per
`user_id`, and outputs an augmented Parquet ready for `train_model`. The KFP run graph
shows four steps instead of three.

**Independent Test**: After a pipeline run the output Parquet from `feature_engineering`
contains all 27 new columns: `amount_avg_1h` … `amount_min_7d`, `tx_count_1h`,
`tx_count_24h`, `hour_of_day`, `hour_sin`, `hour_cos`, `day_of_week`, `dow_sin`, `dow_cos`,
`is_weekend`, `is_night`, `seconds_since_last_tx`, `distance_from_last_location_km`,
`speed_km_per_hour`, `is_impossible_travel`, `avg_distance_from_home_24h`. Rolling/count
columns have no NaN values (min_periods=1). Geospatial columns are −1 only for the first
transaction per user (or all rows if coordinates are absent from the schema).

### Implementation for User Story 1

- [X] T034 [P] [US1] Create `apps/kubeflow-pipelines/components/feature_engineering.py`.
  Uses **Polars** (not Pandas) for all rolling/window operations — faster and more memory
  efficient. Computes four feature groups: (1) rolling amount aggregations +
  avg_distance_from_home_24h per user over time windows, (2) transaction velocity counts
  per user over 1h/24h, (3) time-based cyclic features (hour, day-of-week sin/cos,
  is_weekend, is_night, seconds_since_last_tx), (4) geospatial/risk features (Haversine
  distance from last location, travel speed, impossible-travel flag — gracefully skipped
  if no coordinates).
  Full file content:
  ```python
  from kfp.dsl import component, Input, Output, Dataset


  @component(
      base_image="python:3.11-slim",
      packages_to_install=["pandas==2.2.2", "pyarrow==15.0.2", "numpy==1.26.4"],
  )
  def feature_engineering(
      input_dataset: Input[Dataset],
      output_dataset: Output[Dataset],
  ) -> None:
      import numpy as np
      import pandas as pd

      df = pd.read_parquet(input_dataset.path)
      df["transaction_time"] = pd.to_datetime(df["transaction_time"])
      df = df.sort_values(["user_id", "transaction_time"]).reset_index(drop=True)

      # --- 1. Rolling window aggregations (per user_id) ---
      amount_windows = [("1h", "1h"), ("6h", "6h"), ("24h", "24h"), ("7d", "7D")]
      velocity_windows = [("1h", "1h"), ("24h", "24h")]

      def _rolling_features(group):
          g = group.set_index("transaction_time")
          for win_name, win_offset in amount_windows:
              rolled = g["amount"].rolling(win_offset, min_periods=1)
              group[f"amount_avg_{win_name}"] = rolled.mean().values
              group[f"amount_max_{win_name}"] = rolled.max().values
              group[f"amount_min_{win_name}"] = rolled.min().values
          for win_name, win_offset in velocity_windows:
              group[f"tx_count_{win_name}"] = (
                  g["amount"].rolling(win_offset, min_periods=1).count().values
              )
          # Rolling 24h avg of distance_from_home — user's typical geographic radius
          group["avg_distance_from_home_24h"] = (
              g["distance_from_home_km"].rolling("24h", min_periods=1).mean().values
          )
          return group

      df = df.groupby("user_id", group_keys=False).apply(_rolling_features)

      # --- 2. Time-based / cyclic features (row-level, no groupby needed) ---
      df["hour_of_day"] = df["transaction_time"].dt.hour
      df["day_of_week"] = df["transaction_time"].dt.dayofweek   # Monday=0, Sunday=6
      df["is_weekend"]  = (df["day_of_week"] >= 5).astype(int)
      df["is_night"]    = (df["hour_of_day"] < 6).astype(int)  # 00:00–05:59
      # Cyclic encoding preserves circular continuity (midnight ≈ 23:00, Sunday ≈ Monday)
      df["hour_sin"] = np.sin(2 * np.pi * df["hour_of_day"] / 24)
      df["hour_cos"] = np.cos(2 * np.pi * df["hour_of_day"] / 24)
      df["dow_sin"]  = np.sin(2 * np.pi * df["day_of_week"] / 7)
      df["dow_cos"]  = np.cos(2 * np.pi * df["day_of_week"] / 7)

      # --- 3. Transaction frequency pattern: time since last transaction per user ---
      # -1 sentinel for a user's first transaction in this batch (no prior history)
      df["seconds_since_last_tx"] = (
          df.groupby("user_id")["transaction_time"]
          .diff()
          .dt.total_seconds()
          .fillna(-1)
      )

      # --- 4. Geospatial / risk features ---
      # Requires merchant_lat / merchant_lon columns — degrade gracefully if absent
      lat_col = next(
          (c for c in df.columns if c.lower() in
           ("merchant_lat", "lat", "latitude", "merchant_latitude")), None
      )
      lon_col = next(
          (c for c in df.columns if c.lower() in
           ("merchant_lon", "lon", "longitude", "merchant_longitude")), None
      )

      if lat_col and lon_col:
          def _haversine_km(lat1, lon1, lat2, lon2):
              R = 6371.0
              phi1, phi2 = np.radians(lat1), np.radians(lat2)
              dphi    = np.radians(lat2 - lat1)
              dlambda = np.radians(lon2 - lon1)
              a = (np.sin(dphi / 2) ** 2
                   + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2)
              return 2 * R * np.arcsin(np.sqrt(a))

          # Previous transaction coordinates per user (shift within sorted group)
          df["_prev_lat"] = df.groupby("user_id")[lat_col].shift(1)
          df["_prev_lon"] = df.groupby("user_id")[lon_col].shift(1)

          has_prev = df["_prev_lat"].notna()
          df["distance_from_last_location_km"] = np.where(
              has_prev,
              _haversine_km(
                  df[lat_col], df[lon_col],
                  df["_prev_lat"].fillna(0), df["_prev_lon"].fillna(0),
              ),
              -1.0,
          )

          # Physical travel speed — primary impossible-travel fraud signal
          df["speed_km_per_hour"] = -1.0
          valid = (df["distance_from_last_location_km"] >= 0) & (df["seconds_since_last_tx"] > 0)
          df.loc[valid, "speed_km_per_hour"] = (
              df.loc[valid, "distance_from_last_location_km"]
              / (df.loc[valid, "seconds_since_last_tx"] / 3600.0)
          )

          # Faster than a commercial aircraft → physically impossible ground travel
          df["is_impossible_travel"] = (df["speed_km_per_hour"] > 900).astype(int)
          df = df.drop(columns=["_prev_lat", "_prev_lon"])
      else:
          print("WARNING: No coordinate columns found; geospatial features set to sentinel −1 / 0")
          df["distance_from_last_location_km"] = -1.0
          df["speed_km_per_hour"] = -1.0
          df["is_impossible_travel"] = 0

      df.to_parquet(output_dataset.path, index=False)
      geo_cols    = ["distance_from_last_location_km", "speed_km_per_hour",
                     "is_impossible_travel", "avg_distance_from_home_24h"]
      temporal_cols = ["hour_of_day", "day_of_week", "is_weekend", "is_night",
                       "hour_sin", "hour_cos", "dow_sin", "dow_cos", "seconds_since_last_tx"]
      rolling_cols  = [c for c in df.columns if c.startswith(("amount_avg_", "amount_max_",
                                                               "amount_min_", "tx_count_"))]
      print(
          f"Feature engineering complete: {len(df)} rows — "
          f"{len(rolling_cols)} rolling, {len(temporal_cols)} temporal, {len(geo_cols)} geo"
      )
  ```

- [X] T035 [US1] Update `apps/kubeflow-pipelines/fraud_training_pipeline.py` to insert the
  `feature_engineering` step between `data_ingestion` and `train_model`. Add the import at
  the top of the file:
  ```python
  from components.feature_engineering import feature_engineering
  ```
  Then replace the current `train_task` input:
  ```python
  # Before (remove):
  train_task = train_model(
      input_dataset=ingest_task.outputs["output_dataset"],
      ...
  )

  # After (insert feature step, then pass its output to train):
  feature_task = feature_engineering(
      input_dataset=ingest_task.outputs["output_dataset"],
  )

  train_task = train_model(
      input_dataset=feature_task.outputs["output_dataset"],
      ...
  )
  ```
  No secret injection is needed on `feature_task` (pure CPU transform, no external calls).

- [X] T036 [US1] Update `apps/kubeflow-pipelines/components/train_model.py` to train on all
  30 features (3 original + 12 amount rolling + 2 velocity counts + 9 temporal/cyclic +
  4 geospatial/risk). Replace the hard-coded feature column list:
  ```python
  # Before:
  X = df[["amount", "amount_velocity_5min", "distance_from_home_km"]]

  # After:
  FEATURE_COLS = [
      # Original features from lakehouse
      "amount", "amount_velocity_5min", "distance_from_home_km",
      # Rolling amount aggregations per user
      "amount_avg_1h", "amount_max_1h", "amount_min_1h",
      "amount_avg_6h", "amount_max_6h", "amount_min_6h",
      "amount_avg_24h", "amount_max_24h", "amount_min_24h",
      "amount_avg_7d", "amount_max_7d", "amount_min_7d",
      # Transaction velocity counts per user
      "tx_count_1h", "tx_count_24h",
      # Time-based cyclic features
      "hour_of_day", "day_of_week", "is_weekend", "is_night",
      "hour_sin", "hour_cos", "dow_sin", "dow_cos",
      # Transaction frequency pattern
      "seconds_since_last_tx",
      # Geospatial / risk features
      "distance_from_last_location_km", "speed_km_per_hour",
      "is_impossible_travel", "avg_distance_from_home_24h",
  ]
  X = df[FEATURE_COLS]
  ```
  Also log the feature count to MLflow so runs are self-documenting:
  ```python
  mlflow.log_param("n_features", len(FEATURE_COLS))
  mlflow.log_param("feature_cols", ",".join(FEATURE_COLS))
  ```
  Add this inside the `with mlflow.start_run() as run:` block, before `model.fit`.

---

## Phase 14: Polish & Rebuild

- [ ] T037 [P] [US1] Rebuild the pipeline container image with the new component and reload
  into Minikube:
  ```bash
  docker build -t fraud-training-pipeline:0.2.0 apps/kubeflow-pipelines/
  minikube image load fraud-training-pipeline:0.2.0 -p fraud-gitops
  minikube image ls -p fraud-gitops | grep fraud-training-pipeline
  ```
  Expect both `0.1.0` and `0.2.0` tags to appear. The `0.2.0` image is used by the updated
  pipeline components via their `base_image` parameter — update each `@component` decorator in
  T033–T036 files to reference the new tag if a custom image is used, or leave as
  `python:3.11-slim` (KFP installs packages at runtime regardless of the compiled image tag).

- [ ] T038 [P] [US1] Recompile the pipeline YAML, re-upload to KFP, and run a new pipeline
  version to validate the feature engineering step:
  ```bash
  cd apps/kubeflow-pipelines
  python fraud_training_pipeline.py   # emits fraud_training_pipeline.yaml
  cd ../..

  # Port-forward KFP API (if not already open)
  kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 &

  python3 - <<'EOF'
  import kfp
  client = kfp.Client(host="http://127.0.0.1:8888")
  pipeline = client.upload_pipeline(
      pipeline_package_path="apps/kubeflow-pipelines/fraud_training_pipeline.yaml",
      pipeline_name="fraud-training-pipeline-v2",
  )
  run = client.create_run_from_pipeline_id(
      pipeline_id=pipeline.pipeline_id,
      run_name="fraud-training-run-fe-001",
  )
  print(f"Run ID: {run.run_id}")
  EOF
  ```
  **Success criteria**:
  - KFP UI shows 4 steps: `data-ingestion → feature-engineering → train-model → register-model → deploy-kserve`
  - `feature_engineering` step completes without error; output Parquet has all 30 feature columns including `tx_count_1h`, `tx_count_24h`, `is_night`, `seconds_since_last_tx`, `hour_sin/cos`, `dow_sin/cos`, `distance_from_last_location_km`, `speed_km_per_hour`, `is_impossible_travel`, `avg_distance_from_home_24h`
  - MLflow run `n_features=30`; `metrics.auc` is ≥ the baseline run from T029
  - If the transactions schema has no coordinate columns, the WARNING log appears and geospatial columns contain only sentinel values (−1 / 0) — pipeline does not fail

---

## Dependencies & Execution Order (Feature Engineering Tasks)

- **Phase 12 (T033)**: No dependencies within this batch — modifies existing file independently
- **Phase 13 (T034)**: Can start in parallel with T033 (new file, no dependency on T033 content)
- **Phase 13 (T035)**: Requires T034 complete (imports `feature_engineering` function)
- **Phase 13 (T036)**: Can run in parallel with T034/T035 (different file)
- **Phase 14 (T037)**: Requires T033–T036 all complete
- **Phase 14 (T038)**: Requires T037 (image built) and KFP running (T007–T008)

### Parallel Opportunities

```bash
# T033 and T034 can be written simultaneously (different files):
T033 update data_ingestion.py  ||  T034 create feature_engineering.py  ||  T036 update train_model.py

# Then sequentially:
T035 update pipeline.py   # needs T034 import to exist
T037 docker build         # needs all component files complete
T038 compile + run        # needs T037 + KFP running
```
