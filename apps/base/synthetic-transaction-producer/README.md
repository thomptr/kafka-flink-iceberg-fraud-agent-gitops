# Synthetic transaction producer

Async Kafka producer using **aiokafka** and **faker**. Emits JSON compatible with `apps/base/flink-jobs/flink_streaming_job.sql` (`transaction_id`, `user_id`, `amount`, `merchant`, `lat`, `lon`, `ts`).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | yes | Comma-separated brokers (in-cluster DNS). |
| `KAFKA_TOPIC` | no | Default `transactions`. |
| `EVENTS_PER_SEC` | no | Throttle (default `10`). |

Do **not** commit real cluster secrets or `.env` files with real passwords.

## Build and load into Minikube

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

1. **Bootstrap Service must exist** (Strimzi creates it from the `Kafka` CR):

   ```bash
   kubectl get kafka -n kafka
   kubectl get svc -n kafka platform-cluster-kafka-bootstrap
   ```

   If the Service is missing, fix **Strimzi** / **`Kafka` `platform-cluster`** first; DNS will not resolve until the Service exists.

2. **Same-namespace address** in `deployment.yaml` is `platform-cluster-kafka-bootstrap:9092`. From another namespace use `platform-cluster-kafka-bootstrap.kafka:9092` or the full `*.svc.cluster.local` name.

3. The producer **retries** bootstrap for several minutes (env `KAFKA_BOOTSTRAP_MAX_ATTEMPTS`, `KAFKA_BOOTSTRAP_RETRY_DELAY_SEC`) so it can outlive slow Kafka reconciliation.

## Network

The producer must reach Kafka brokers on the cluster network. If you use namespaces, run the Deployment in the same cluster as Kafka (e.g. `kafka`) or ensure DNS/routing to `bootstrap` servers. See `deployment.yaml` for the chosen namespace.

This repo does not ship a `NetworkPolicy` for the producer. To restrict egress to Kafka only, add a policy in the `kafka` namespace that allows the producer pod to reach `platform-cluster-kafka-bootstrap` on port 9092 and blocks other egress as required by your security model.
