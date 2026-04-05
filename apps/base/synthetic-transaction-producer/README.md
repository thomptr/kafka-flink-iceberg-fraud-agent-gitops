# Synthetic transaction producer

Async Kafka producer using **aiokafka** and **faker**. Emits JSON compatible with `apps/base/flink-jobs/flink_streaming_job.sql` (`transaction_id`, `user_id`, `amount`, `merchant`, `lat`, `lon`, `ts`).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | yes | Comma-separated brokers (in-cluster DNS). |
| `KAFKA_TOPIC` | no | Default `transactions`. |
| `EVENTS_PER_SEC` | no | Throttle (default `10`). |
| `CONTROL_PORT` | no | HTTP control API port (default `8080`). |
| `CONTROL_API_TOKEN` | no | If set, `POST /pause`, `POST /resume`, and `GET /status` require header `Authorization: Bearer <token>`. `GET /health` stays open for probes. |

## Pause / resume (HTTP)

The pod serves a small control API on **`CONTROL_PORT`** (default **8080**), started **before** Kafka connects so you can probe it during bootstrap.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness/readiness (`ok`). |
| `GET` | `/status` | JSON body with boolean `paused`. |
| `POST` | `/pause` | Stop sending (producer stays connected to Kafka). |
| `POST` | `/resume` | Resume sending at `EVENTS_PER_SEC`. |

From your machine (replace the pod name if needed):

```bash
kubectl -n kafka port-forward svc/synthetic-transaction-producer 8080:8080
curl -sS -X POST http://127.0.0.1:8080/pause
curl -sS http://127.0.0.1:8080/status
curl -sS -X POST http://127.0.0.1:8080/resume
```

With `CONTROL_API_TOKEN` set in the Deployment:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" -X POST http://127.0.0.1:8080/pause
```

**Alternative without code:** `kubectl -n kafka scale deployment/synthetic-transaction-producer --replicas=0` to stop the workload entirely (not the same as pause-in-process).

Do **not** commit real cluster secrets or `.env` files with real passwords.

## Build and load into Minikube

The Deployment uses **`strategy.type: Recreate`** so rollouts never run two producer pods at once (only one replica; there is a short window with zero pods during the switch).

The Deployment uses **`synthetic-transaction-producer:latest`** with **`imagePullPolicy: Never`**: Kubernetes will **not** pull from Docker Hub (there is no public image with that name). You must **build** the image and **load** it into the Minikube node’s container runtime.

**Order matters:** apply the **current** `deployment.yaml` (with `imagePullPolicy: Never`) to the cluster **before** relying on local images. If events still show **`Pulling image`** / **`ErrImagePull`**, the live Deployment is an older revision (`IfNotPresent` tries the registry when the image is missing). Push + `flux reconcile`, or from an up-to-date clone run `kubectl apply -k apps/minikube`, then confirm:

```bash
kubectl get deploy -n kafka synthetic-transaction-producer -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}'
# must print: Never
```

From the **repository root**:

```bash
docker build -t synthetic-transaction-producer:latest -f apps/base/synthetic-transaction-producer/Dockerfile apps/base/synthetic-transaction-producer
minikube image load synthetic-transaction-producer:latest
```

**Alternative** (build inside Minikube’s Docker so no `image load`):

```bash
eval $(minikube docker-env)
docker build -t synthetic-transaction-producer:latest -f apps/base/synthetic-transaction-producer/Dockerfile apps/base/synthetic-transaction-producer
eval $(minikube docker-env -u)
kubectl -n kafka rollout restart deployment/synthetic-transaction-producer
```

Then apply or wait for Flux: `kubectl apply -k apps/minikube` (or your usual GitOps path). If the Deployment already exists, restart after loading: `kubectl -n kafka rollout restart deployment/synthetic-transaction-producer`.

## Troubleshooting: `Name or service not known` / cannot bootstrap

If logs still show **`platform-cluster-kafka-bootstrap.kafka.svc.cluster.local`** and **`main.py` line ~48** as a single `await producer.start()`, you are on an **old container image or old Deployment** (current Git uses **`platform-cluster-kafka-bootstrap:9092`**, retries in `main.py`, and an **initContainer** that waits for TCP `:9092`). **Rebuild the image**, `minikube image load`, `kubectl apply -k apps/minikube`, then `kubectl -n kafka rollout restart deployment/synthetic-transaction-producer`.

1. **Bootstrap Service must exist** (Strimzi creates `platform-cluster-kafka-bootstrap` only after the `Kafka` CR reconciles).

   ```bash
   kubectl get kafka -n kafka
   kubectl get svc -n kafka
   kubectl get pods -n kafka
   ```

   If **`kubectl get svc -n kafka platform-cluster-kafka-bootstrap`** returns **NotFound**, the cluster does not have a working Strimzi Kafka yet. **DNS and the producer cannot succeed** until this Service exists.

   **Apply platform Kafka (same paths Flux uses):**

   ```bash
   # From repo root — Kafka CR + KafkaTopic live under infrastructure/configs
   kubectl apply -k infrastructure/configs/minikube
   ```

   Or with Flux: ensure **`infra-controllers`** (Strimzi operator) and **`infra-configs`** have reconciled, then `flux reconcile kustomization infra-configs --with-source`.

   Then wait until **`kubectl get kafka -n kafka platform-cluster`** shows **Ready** (or at least **Reconciliation** progressing) and **`kubectl get svc -n kafka`** lists **`platform-cluster-kafka-bootstrap`**. If the `Kafka` CR is missing, your Git revision may not be applied yet (push + reconcile, or apply the command above from an up-to-date clone).

2. **Same-namespace address** in `deployment.yaml` is `platform-cluster-kafka-bootstrap:9092`. From another namespace use `platform-cluster-kafka-bootstrap.kafka:9092` or the full `*.svc.cluster.local` name.

3. The producer **retries** bootstrap for several minutes (env `KAFKA_BOOTSTRAP_MAX_ATTEMPTS`, `KAFKA_BOOTSTRAP_RETRY_DELAY_SEC`) so it can outlive slow Kafka reconciliation.

## Network

The producer must reach Kafka brokers on the cluster network. If you use namespaces, run the Deployment in the same cluster as Kafka (e.g. `kafka`) or ensure DNS/routing to `bootstrap` servers. See `deployment.yaml` for the chosen namespace.

This repo does not ship a `NetworkPolicy` for the producer. To restrict egress to Kafka only, add a policy in the `kafka` namespace that allows the producer pod to reach `platform-cluster-kafka-bootstrap` on port 9092 and blocks other egress as required by your security model.
