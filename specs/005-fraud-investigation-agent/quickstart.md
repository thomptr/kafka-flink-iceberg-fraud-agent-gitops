# Quickstart: Fraud Investigation Agent

**Feature**: 005-fraud-investigation-agent  
**Prerequisites**: `fraud-alert-agent` service running (see `src/fraud-alert-agent/README.md`)

---

## Local Development

### 1. Start the backend (fraud-alert-agent FastAPI service)

```bash
cd src/fraud-alert-agent
docker-compose up -d           # starts Postgres, Ollama, and the FastAPI service
# OR run directly:
uvicorn app.main:app --reload --port 8000
```

Apply the new migration (adds `investigation_sessions`, `session_turns`, `investigation_conclusions`):

```bash
alembic upgrade head
```

### 2. Verify the new session endpoints

```bash
export API_KEY="dev-secret"    # matches FRAUD_API_KEY in docker-compose.yml
export ALERT_ID="<uuid>"       # get from GET /api/v1/alerts

# Open a session
curl -s -X POST http://localhost:8000/api/v1/alerts/${ALERT_ID}/investigation-sessions \
  -H "X-API-Key: ${API_KEY}" \
  -H "X-Analyst-Id: analyst@example.com" | jq .

# Ask a follow-up question
export SESSION_ID="<uuid from above>"
curl -s -X POST http://localhost:8000/api/v1/investigation-sessions/${SESSION_ID}/turns \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"question": "Has this merchant been associated with fraud before?"}' | jq .

# Record a conclusion
curl -s -X POST http://localhost:8000/api/v1/investigation-sessions/${SESSION_ID}/conclude \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"outcome": "confirmed_fraud", "notes": "Merchant on blocklist; user pattern match confirmed."}' | jq .
```

### 3. Run the investigation UI (Streamlit)

```bash
cd src/fraud-alert-agent
pip install -e ".[dashboard]"  # streamlit and httpx are in the dashboard extras

FRAUD_AGENT_BASE_URL=http://localhost:8000 \
FRAUD_API_KEY=dev-secret \
streamlit run investigation_ui/app.py --server.port 8502
```

Open `http://localhost:8502` in a browser.

---

## Kubernetes (Minikube)

```bash
# Apply the new investigation UI manifests
kubectl apply -k apps/base/fraud-investigation-ui/

# Check rollout
kubectl rollout status deployment/fraud-investigation-ui -n fraud-agent

# Port-forward to access the UI
kubectl port-forward svc/fraud-investigation-ui 8502:80 -n fraud-agent
```

Open `http://localhost:8502`.

The investigation UI is pre-configured to reach the `fraud-alert-agent` service via cluster DNS:  
`http://fraud-alert-agent.fraud-agent.svc.cluster.local:8000`

---

## Investigation Session Walkthrough

1. **Select an alert**: Choose a fraud alert from the dropdown (filtered to `open` or `in_review` status).
2. **View initial explanation**: The agent immediately shows why the transaction was flagged — top risk signals with supporting data values.
3. **Ask questions**: Type questions in the chat input. Example prompts:
   - "Show me this user's last 10 transactions"
   - "What ML features had the highest fraud weight?"
   - "Is this merchant's location unusual for this user?"
4. **Explore evidence**: Ask for raw data: "Show me the full feature vector for this transaction"
5. **Record conclusion**: Use the sidebar to select `Confirmed Fraud`, `False Positive`, or `Escalate`, add notes, and submit.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FRAUD_AGENT_BASE_URL` | `http://localhost:8000` | Backend FastAPI service URL |
| `FRAUD_API_KEY` | `""` | API key for `X-API-Key` header |
| `SESSION_TIMEOUT_MINUTES` | `60` | Minutes of inactivity before session is abandoned |

---

## Troubleshooting

**Session creation returns 404**: Confirm the `alert_id` exists: `GET /api/v1/alerts/{id}`

**Initial explanation takes > 30s**: Ollama may be slow on CPU; check `kubectl logs -l app=ollama -n ollama`. GPU acceleration reduces inference to ~3–5s.

**"Session already concluded" (409)**: Another analyst concluded this alert. The UI shows the prior conclusion's analyst and timestamp.

**Streamlit shows "API error"**: Verify `FRAUD_AGENT_BASE_URL` is reachable and `FRAUD_API_KEY` matches the backend secret.

---

## GitOps / FluxCD Deployment

The investigation UI is deployed via FluxCD. The FluxCD `Kustomization` at
`clusters/minikube/apps.yaml` points to `./apps/minikube`, which now includes
`fraud-investigation-ui`.

### Release a new image version

```bash
# 1. Build and push the image
eval $(minikube docker-env)       # or push to your registry
docker build -t fraud-investigation-ui:0.1.1 src/streamlit-ui/

# 2. Update the image tag in the minikube overlay
# Edit apps/minikube/fraud-investigation-ui/kustomization.yaml
#   images:
#     - name: fraud-investigation-ui
#       newTag: "0.1.1"     ← update this line

git add apps/minikube/fraud-investigation-ui/kustomization.yaml
git commit -m "chore: bump fraud-investigation-ui to 0.1.1"
git push
```

### Monitor FluxCD reconciliation

```bash
# Check reconciliation status (runs every 10 minutes by default)
flux get kustomizations -n flux-system

# Force an immediate reconcile without waiting
flux reconcile kustomization apps -n flux-system

# Confirm pod is running
kubectl rollout status deployment/fraud-investigation-ui -n fraud-agent

# Port-forward to access the UI
kubectl port-forward svc/fraud-investigation-ui 8502:80 -n fraud-agent
```

Open `http://localhost:8502`.
