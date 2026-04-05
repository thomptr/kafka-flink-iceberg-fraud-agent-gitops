# Grafana dashboards (streaming pipeline)

This runbook lists Grafana.com dashboards and custom panels used for the Kafka → Flink → Iceberg path (`002-e2e-streaming-pipeline`).

## Flink

| Dashboard | Grafana.com ID | Notes |
|-----------|------------------|--------|
| Flink Job Metrics | **14161** | Import from grafana.com; datasource Prometheus. Shows job throughput, checkpoints, backpressure. |

**Ownership**: update this file when switching dashboard versions or IDs.

## Kafka

| Dashboard | Source | Notes |
|-----------|--------|--------|
| Kafka Overview | Search Grafana.com for “Kafka Overview” (Strimzi / JMX exporter variants) | Pick one that matches metrics exposed in your cluster (`kafka_*` or `kafka_server_*`); record the final dashboard UID in this table after import. |

**Final UID (this cluster)**: *TBD after import — fill in after choosing a dashboard.*

## Iceberg write latency (custom)

Pure Flink SQL does not emit a dedicated Iceberg commit histogram in this repo. Until a Java sink wrapper adds `user_scope_iceberg_commit_latency_ms`, use:

- Flink checkpoint duration / alignment metrics as a proxy (`flink_jobmanager_job_numberOfCompletedCheckpoints`, checkpoint times from dashboard 14161).
- Task/operator metrics whose names contain `Iceberg` or sink commit timing (exact names vary by Flink and Iceberg connector versions — confirm in Prometheus **Targets** → Flink job, then **Graph** autocomplete).

**Example PromQL (adjust metric names after discovery)**:

```promql
# Placeholder — replace with an Iceberg- or checkpoint-related series from your scrape
rate(flink_taskmanager_job_task_operator_numRecordsOutPerSecond[5m])
```

Saved panel JSON for copy/paste: `docs/runbooks/grafana-iceberg-latency-panel.json`.

## Optional alerting

See `docs/runbooks/flink-checkpoints.md` for checkpoint/S3 failure signals. Add a `PrometheusRule` in the monitoring stack when you want automated pages for high checkpoint duration or failed checkpoints.
