# Runbook: Fraud Alert Agent

## 1. Tune Fraud Thresholds

Edit `apps/base/fraud-alert-agent/configmap.yaml` and adjust `FRAUD_THRESHOLD_CRITICAL/HIGH/MEDIUM`, then rollout:
```bash
kubectl rollout restart deployment/fraud-alert-agent -n fraud-agent
```

## 2. Tune analysis_node Prompt

Edit `src/fraud-alert-agent/app/agents/analysis_node.py` — update `_SYSTEM_PROMPT`. Build and redeploy:
```bash
docker build -t fraud-alert-agent:0.1.1 src/fraud-alert-agent/
kubectl set image deployment/fraud-alert-agent fraud-alert-agent=fraud-alert-agent:0.1.1 -n fraud-agent
```

## 3. Swap Ollama Model

Update `OLLAMA_MODEL` in `apps/base/fraud-alert-agent/configmap.yaml`. Pre-pull the new model via a Job or:
```bash
kubectl exec -n ollama deploy/ollama -- ollama pull mistral:7b
```

## 4. Replay an Investigation

Delete the Investigation and LangGraph checkpoint for the alert, then re-trigger via a new Kafka message:
```bash
# Delete checkpoint (LangGraph uses thread_id = alert_id)
psql $DATABASE_URL -c "DELETE FROM checkpoints WHERE thread_id = '<alert_id>';"
psql $DATABASE_URL -c "DELETE FROM investigations WHERE alert_id = '<alert_id>';"
# Re-inject a scored transaction
curl -X POST http://localhost:8080/inject/scored -d '{"transaction_id": "<orig_txn_id>", ...}'
```

## 5. Query fraud.investigations Iceberg

```python
from pyiceberg.catalog.rest import RestCatalog
catalog = RestCatalog("polaris", uri="http://polaris...:8181/api/catalog", credential="...", warehouse="fraud_warehouse")
table = catalog.load_table("fraud.investigations")
df = table.scan(row_filter="final_action = 'block'").to_arrow().to_pandas()
```

## 6. Compact fraud.investigations

```python
table.rewrite_data_files()
table.expire_snapshots()
```

## 7. List Polaris Tables

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/healthz  # checks polaris
# Or directly:
kubectl exec -n fraud-agent deploy/fraud-alert-agent -- python -c \
  "from app.tools.iceberg_query_tool import list_iceberg_tables; print(list_iceberg_tables.invoke({'namespace': 'fraud'}))"
```

## 8. Rotate Polaris Credential

Update the `polaris-credential` key in `fraud-agent-secrets` secret:
```bash
kubectl create secret generic fraud-agent-secrets --from-literal=polaris-credential=NEW_CRED \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/fraud-alert-agent -n fraud-agent
```

## 9. Look Up MLflow Model Version

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/metrics | jq .mlflow_model_version_in_use
```

## 10. Promote MLflow Model to Production

```python
from mlflow.tracking import MlflowClient
client = MlflowClient("http://mlflow.mlflow.svc.cluster.local:5000")
client.transition_model_version_stage("fraud-score-xgboost", version="3", stage="Production")
```

## 11. Inspect Kafka Topics

```bash
kubectl exec -n fraud-agent deploy/fraud-alert-agent -- python -c \
  "from app.tools.kafka_producer_tool import list_kafka_topics; print(list_kafka_topics.invoke({}))"
```

## 12. Check Kafka Consumer Lag

```bash
# Via metrics endpoint
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/metrics | jq .kafka_consumer_lag
# Via kubectl
kubectl exec -n kafka deploy/... -- kafka-consumer-groups.sh \
  --bootstrap-server platform-cluster-kafka-bootstrap:9092 \
  --describe --group fraud-alert-agent
```

## 13. Reset Kafka Consumer Offset (re-process transactions)

```bash
kubectl exec -n kafka ... -- kafka-consumer-groups.sh \
  --bootstrap-server platform-cluster-kafka-bootstrap:9092 \
  --group fraud-alert-agent \
  --topic scored-transactions \
  --reset-offsets --to-earliest --execute
```

## 14. Debug Failed Kafka Delivery

```bash
# Check step 4 (escalation) and step 5 (report) kafka_delivered field
curl -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/v1/alerts/{ALERT_ID}/investigation | jq '.steps[] | {step: .step_order, kafka_delivered}'
```

## 15. Restart Flink fraud-score-kafka-publisher (scored-transactions goes silent)

```bash
kubectl rollout restart flinkdeployment/fraud-score-kafka-publisher -n flink-system
# Verify topic has messages
kubectl exec -n kafka ... -- kafka-console-consumer.sh \
  --bootstrap-server platform-cluster-kafka-bootstrap:9092 \
  --topic scored-transactions --from-beginning --max-messages 5
```

## 16. Enable LangSmith Tracing

```bash
kubectl create secret generic fraud-agent-secrets \
  --from-literal=langchain-api-key=lsv2_... \
  --dry-run=client -o yaml | kubectl apply -f -
# Update configmap: LANGCHAIN_TRACING_V2=true
kubectl rollout restart deployment/fraud-alert-agent -n fraud-agent
```

## 17. Add Slack Channel

Edit `src/fraud-alert-agent/app/services/notification_service.py` — update `_CHANNEL_MAP`.

## 18. Postgres Recovery

```bash
# Check pod status
kubectl get pod -n fraud-agent -l app=postgres
# Inspect WAL/logs
kubectl logs -n fraud-agent statefulset/postgres
# Restore from backup (if enabled):
kubectl exec -n fraud-agent postgres-0 -- pg_restore -U fraud_agent -d fraud_agent /backup/latest.dump
```
