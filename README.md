# FluxCD GitOps Monorepo for Minikube

This repository is a public GitOps monorepo for a Minikube-based local platform.
It uses FluxCD to reconcile shared infrastructure and workloads from a single
source of truth while keeping plaintext secrets, private keys, and passwords out
of Git.

```sh
minikube start --profile fraud-gitops \
  --cpus 8 \
  --memory 16384 \
  --disk-size 80g \
  --driver docker \
  --container-runtime docker \
  --gpus all
```

```sh
minikube start --profile fraud-gitops \
  --cpus 8 \
  --memory 16384 \
  --disk-size 80g \
  --driver docker \
  --container-runtime docker \
  --gpus all
```

## Stack

- FluxCD
- MinIO
- Apache Polaris catalog
- Strimzi Kafka
- Flink Kubernetes Operator
- Kubeflow core controllers for the dashboard and notebooks
- MLflow
- Prometheus
- Grafana
- **Ollama** — local LLM inference (llama3.1:8b), deployed to the `ollama` namespace with GPU toleration
- **Fraud Alert Agent** — 7-node LangGraph multi-agent pipeline: event-driven Kafka consumer (`alert_monitor`) → LLM investigation → `fraud.investigations` Iceberg table; 7 registered LangChain tools; Flink `fraud-score-kafka-publisher` publishes `transactions_scored` → `scored-transactions` Kafka topic

## Repository Layout

```text
clusters/
infrastructure/
apps/
  base/fraud-alert-agent/      # K8s manifests: deployment, postgres, configmap, tempo, otel-collector
  base/fraud-investigation-ui/ # K8s manifests: Streamlit investigation UI deployment + service
  base/ollama/                 # Ollama GPU deployment + llama3.1:8b pull Job
  minikube/fraud-alert-agent/
  minikube/fraud-investigation-ui/
  minikube/ollama/
src/
  fraud-alert-agent/           # FastAPI service + LangGraph agents + tools
  streamlit-ui/                # Analyst investigation chat UI (Streamlit)
docs/
  architecture.md              # End-to-end system flow and LangGraph node diagrams
  runbooks/
    fraud-alert-agent.md       # Operations runbook (includes investigation session procedures)
specs/
  004-fraud-alert-agent/       # Feature spec, plan, tasks, quickstart
  005-fraud-investigation-agent/ # Investigation agent spec, plan, tasks, quickstart
scripts/
```

- `clusters/minikube/` contains the Flux entrypoint and reconciliation order.
- `infrastructure/` contains shared platform controllers and cluster-wide config.
- `apps/` contains workload-level definitions such as MLflow and sample Flink jobs.
- `src/` contains application source code separate from Flux/GitOps YAML.

## Fraud Alert Agent — Usage

### Local dev quickstart

```bash
cd src/fraud-alert-agent
docker compose up -d postgres
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Minikube deploy

```bash
eval $(minikube docker-env -p fraud-gitops)
docker build -t fraud-alert-agent:0.1.0 src/fraud-alert-agent/
kubectl apply -k apps/minikube/fraud-alert-agent/
kubectl apply -k apps/minikube/ollama/
```

### Benefits

- 80%+ of fraud alerts fully investigated before an analyst opens them
- P95 investigation time < 60 seconds end-to-end including Ollama inference
- Complete LangGraph trace log per investigation (node, tool, LLM events) for auditability
- Event-driven Kafka consumer (sub-5s alert lag) replaces polling
- LangSmith remote tracing opt-in via single env var for production debugging
- Iceberg `fraud.investigations` table enables SQL analytics over historical investigation data

### End-to-End Demo

```bash
# Port-forwards
kubectl port-forward svc/fraud-alert-agent -n fraud-agent 8000:8000 &
kubectl port-forward svc/synthetic-transaction-producer -n kafka 8080:8080 &

# 1. Inject a high-probability scored transaction
curl -X POST http://localhost:8080/inject/scored \
  -H "Content-Type: application/json" \
  -d '{"user_id": 99999, "amount": 8500.00, "fraud_probability": 0.95, "merchant": "Test Fraud Merchant", "distance_from_home_km": 450.0}'

# 2. Poll for alert (~5s)
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/api/v1/alerts?severity=critical&status=open"

# 3. Watch investigation complete (~60s)
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/api/v1/alerts/{ALERT_ID}/investigation"

# 4. Approve/override
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  "http://localhost:8000/api/v1/alerts/{ALERT_ID}/decisions" \
  -d '{"actor": "demo@example.com", "action": "approve", "outcome": "block"}'

# 5. View trace logs
kubectl logs -n fraud-agent deploy/fraud-alert-agent | grep node_end
```

See [`docs/architecture.md`](docs/architecture.md) for system diagrams and [`specs/004-fraud-alert-agent/quickstart.md`](specs/004-fraud-alert-agent/quickstart.md) for full integration scenarios.

## Public Repo Rules

- Do not commit plaintext `Secret` manifests.
- Do not commit kubeconfigs, tokens, passwords, TLS private keys, or `.env` files.
- For local Minikube work, create Kubernetes secrets directly in the cluster with
  `kubectl create secret` and keep them out of Git.
- SOPS or external secret managers are optional future enhancements, not required
  for the local workflow.

## Quick Start

1. Start Minikube with the documented sizing profile.
2. Run `make validate` to render and lint all Flux-managed paths.
3. Bootstrap Flux to `clusters/minikube`.
4. Create the required Kubernetes secrets locally in Minikube.
5. Verify `infra-controllers`, `infra-configs`, and `apps` reconcile in order.
6. Port-forward Apache Polaris and MinIO, then run `scripts/verify_polaris_pyiceberg.py` (install `pyiceberg`, `pyarrow`, and `boto3`; set `POLARIS_S3_ACCESS_KEY_ID` / `POLARIS_S3_SECRET_ACCESS_KEY` to MinIO keys unless you enable vended credentials with `POLARIS_USE_VENDED_CREDENTIALS=1`). The script creates the `iceberg-warehouse` bucket if missing.

For the local Minikube workflow, Kubeflow is enabled as a pinned core install.
Heavier add-ons such as Pipelines, KServe, Katib, and Spark Operator remain out
of the active controller path so the Flink-first platform can stay lighter.

See `docs/runbooks/bootstrap.md` for the operator workflow and
`docs/runbooks/secret-management.md` for secret handling.

For the Kafka → Flink SQL → Iceberg (Polaris) streaming path on Minikube, use
`specs/002-e2e-streaming-pipeline/quickstart.md` after Flux and local secrets are applied.

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
```


