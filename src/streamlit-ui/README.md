# Fraud Investigation UI

Streamlit chat interface for investigating fraud alerts. Analysts open a session, ask questions,
explore evidence, and record a binding conclusion (Confirmed Fraud / False Positive / Escalate).

## Prerequisites

- `fraud-alert-agent` backend running (see `src/fraud-alert-agent/README.md`)
- Python 3.11+

## Local Development

```bash
cd src/streamlit-ui
pip install -e ".[dev]"

FRAUD_AGENT_BASE_URL=http://localhost:8000 \
FRAUD_API_KEY=dev-secret \
ANALYST_ID=analyst@example.com \
streamlit run app.py --server.port 8502
```

Open `http://localhost:8502`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FRAUD_AGENT_BASE_URL` | `http://localhost:8000` | Backend FastAPI service URL |
| `FRAUD_API_KEY` | `""` | API key for `X-API-Key` header |
| `ANALYST_ID` | `analyst` | Analyst identity sent in `X-Analyst-Id` header |
| `ICEBERG_CATALOG_URI` | `""` | Optional direct Iceberg catalog for raw history lookup |

## GitOps / FluxCD Deployment

See `specs/005-fraud-investigation-agent/quickstart.md` for the full GitOps release process.

```bash
# Build and push image
docker build -t fraud-investigation-ui:0.1.0 .
docker push <registry>/fraud-investigation-ui:0.1.0

# Update tag and push to trigger FluxCD reconciliation
# Edit apps/minikube/fraud-investigation-ui/kustomization.yaml → newTag: "0.1.0"
git add apps/minikube/fraud-investigation-ui/kustomization.yaml
git commit -m "chore: bump fraud-investigation-ui to 0.1.0"
git push

# Monitor reconciliation
flux get kustomizations -n flux-system
kubectl rollout status deployment/fraud-investigation-ui -n fraud-agent
```
