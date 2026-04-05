# Bootstrap Runbook

## Minikube Profile

Use a dedicated profile with at least 8 CPUs, 16 GiB memory, and 80 GiB disk for
the full stack.

```bash
minikube start --profile fraud-gitops --cpus 8 --memory 16384 --disk-size 80g
```

### GPU: streaming stack vs Kubeflow training

- **Kafka, Flink, Polaris, Grafana, and the `002` streaming path** do not require a GPU. You can start Minikube **without** `--gpus` for that work only (narrower surface area if the NVIDIA stack glitches).

- **Kubeflow notebooks and model training** often need a GPU. Minikube’s supported form is **`--gpus all`** (not necessarily `--gpus nvidia`—those can differ). If **`--gpus all`** has worked on your host before, use it for GPU-backed profiles—for example:

  ```bash
  minikube start --profile fraud-gitops --cpus 8 --memory 16384 --disk-size 80g \
    --driver docker --container-runtime docker --gpus all
  ```

- Practical split: **CPU-only** profile for GitOps/streaming-only; **GPU** profile with **`--gpus all`** when you need Kubeflow training and your machine already passes GPUs into Docker reliably.

#### If Minikube fails with `WSL environment detected but no adapters were found`

Minikube passes **`--gpus all`** into `docker run` for the kicbase node. Docker then runs the **NVIDIA prestart hook**. That hook fails when it thinks it is in **WSL** but **no GPU is visible** to `nvidia-container-cli` (common on **WSL2** until the Windows GPU driver + WSL CUDA stack is fully working).

**Workaround (cluster up today):** start **without** any `--gpus` flag so the Minikube container does not use the NVIDIA hook:

```bash
minikube start --profile fraud-gitops --cpus 8 --memory 16384 --disk-size 80g \
  --driver docker --container-runtime docker
```

Use this for Kafka/Flink/Polaris/Grafana and other CPU workloads. Kubeflow GPU training on this host has to wait until GPU-in-Docker works in **the same environment** where you run Minikube.

**Verify the GPU path inside WSL before retrying `--gpus all`:**

1. In the same Ubuntu/WSL session: `nvidia-smi` must succeed. If it does not, follow [NVIDIA’s WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html) (Windows NVIDIA driver, WSL2 updated, etc.).
2. Then: `docker run --rm --gpus all nvcr.io/nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi` must succeed. If (1) works but (2) fails, fix Docker + NVIDIA Container Toolkit integration for WSL.
3. Only then retry `minikube start … --gpus all`.

**Note:** A machine that showed “Ubuntu 22.04” can still be **WSL**; GPU passthrough differs from **bare-metal Linux**. If you previously had GPU Minikube working, it may have been on native Linux, Docker Desktop’s Linux VM, or an older driver/WSL combo.

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

kubectl -n flink-system create secret generic minio-flink-s3-credentials \
  --from-literal=rootUser='<same-value-as-minio-rootUser>' \
  --from-literal=rootPassword='<same-value-as-minio-rootPassword>'

# Flink → Iceberg (Polaris REST): OAuth client must match polaris-bootstrap-credentials (third field = root password).
kubectl -n flink-system create secret generic polaris-flink-oauth \
  --from-literal=credential='root:<same-password-as-polaris-bootstrap-credentials>'
```

**Polaris warehouse for Flink**: Iceberg needs a catalog named **`quickstart_catalog`** (matching `warehouse` in `flink_streaming_job.sql`) and the **MinIO bucket** from the warehouse URI (default **`iceberg-warehouse`** for `s3://iceberg-warehouse/polaris`). If the bucket does not exist, Iceberg returns **S3 404 bucket does not exist**. The **`polaris-ensure-quickstart-catalog`** Job creates the bucket (via boto3 + `polaris-storage-credentials`) before registering the catalog. After `infra-controllers` reconciles, Flux applies that Job. If the job failed (e.g. Polaris not ready), delete it and let Flux recreate it, or run the script locally with port-forward (install **`boto3`** first, or create the bucket manually, e.g. **`mc mb`** against MinIO):

```bash
# From repo root; uses the same logic as the in-cluster Job (stdlib Python only).
export POLARIS_BOOTSTRAP_CREDENTIALS="$(kubectl -n polaris get secret polaris-bootstrap-credentials -o jsonpath='{.data.credentials}' | base64 -d)"
export POLARIS_CATALOG_URI="http://127.0.0.1:8181/api/catalog"
kubectl -n polaris port-forward svc/polaris 8181:8181
# In another shell:
python3 infrastructure/controllers/base/polaris/ensure_polaris_catalog.py
```

## Reconciliation Order

1. `infra-controllers`
2. `infra-configs`
3. `apps`

## Troubleshooting: `nvidia-container-runtime` / FailedCreatePodSandbox

**Symptom**: Pods (for example Grafana in `monitoring`) stay pending with events like `Failed to create pod sandbox` and `nvidia-container-runtime did not terminate successfully: exit status 2`.

**Cause**: The node’s container engine (often **Docker** behind Minikube) is using the **NVIDIA** OCI runtime as the **default** for every container, or the NVIDIA Container Toolkit is broken. Stack components such as Grafana do not request GPUs; the NVIDIA shim can fail and block all pods on that node.

**What to do**:

1. On the host running Docker, inspect `/etc/docker/daemon.json`. If you see `"default-runtime": "nvidia"`, change it to **`"default-runtime": "runc"`** (or remove the line so `runc` is default). Keep a `runtimes` entry for `nvidia` if you still need GPU containers explicitly.
2. Restart Docker: `sudo systemctl restart docker` (or equivalent).
3. Recreate the Minikube profile or restart it so workloads use the fixed engine: `minikube stop` / `minikube start` with your usual flags.

If you do not need NVIDIA integration on this machine, you can also remove or disable the NVIDIA Container Toolkit until Docker’s default runtime is plain `runc`.

## Troubleshooting: ZooKeeper “Refusing session request” / zxid mismatch (Strimzi)

**Symptom**: ZooKeeper logs show `Authenticated Id 'CN=platform-cluster-kafka,...' for Scheme 'x509'` (normal), then `Refusing session request ... as it has seen zxid ... our last zxid is ... client must try another server`.

**Cause**: The broker’s idea of the ZooKeeper transaction log is **ahead** of what this ZK instance has on disk. That usually happens after **ZooKeeper restarted** or **lost its data** (for example **`ephemeral` storage** in `Kafka` CR) while **Kafka brokers** did not restart together, or after a **node reschedule** that recreated ZK empty.

**What to do now**:

1. Restart Kafka brokers so they open **fresh** sessions: `kubectl -n kafka delete pod -l strimzi.io/name=platform-cluster-kafka` (Strimzi recreates them). If problems persist, restart ZooKeeper pods the same way (`strimzi.io/name=platform-cluster-zookeeper`) and then brokers again.
2. Confirm the cluster recovers: `kubectl -n kafka get kafka platform-cluster -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'; echo`

**Longer term**: `infrastructure/configs/base/kafka/kafka-cluster.yaml` uses **ephemeral** storage for Kafka and ZooKeeper, so **any** ZK pod restart wipes its data and makes zxid mismatches likely. For a stable dev cluster, use **persistent** `persistent-claim` storage (and accept that changing storage on an existing cluster typically requires deleting the `Kafka` CR and PVCs, then reapplying—Strimzi treats storage as immutable).

## Success Targets

- Core platform ready within 15 minutes
- Full stack ready within 45 minutes on the recommended profile
- Routine reconciliations ready within 5 minutes after approved changes
