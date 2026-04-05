# Grafana dashboards (streaming pipeline)

This runbook lists Grafana.com dashboards and custom panels used for the Kafka → Flink → Iceberg path (`002-e2e-streaming-pipeline`).

## Flink

| Dashboard | Grafana.com ID | Notes |
|-----------|------------------|--------|
| Flink Job Metrics | **14161** | Import from grafana.com; datasource Prometheus. Shows job throughput, checkpoints, backpressure. |

**Ownership**: update this file when switching dashboard versions or IDs.

## Kafka

| Dashboard | ID | Notes |
|-----------|-----|--------|
| Strimzi Kafka + JVM (JMX) | [**24626**](https://grafana.com/grafana/dashboards/24626-strimzi-kafka-dashboard-with-jvm-metrics/) | Prometheus only; expects Strimzi JMX metrics (`kafka_*`, `java_lang_*`, …). Wired in this repo via `kafka-metrics` ConfigMap + PodMonitor (see below). |

### Dashboard 24626 — Strimzi Kafka with JVM metrics

Upstream: [Strimzi Kafka Dashboard with JVM Metrics](https://grafana.com/grafana/dashboards/24626-strimzi-kafka-dashboard-with-jvm-metrics/) (Grafana Labs).

**What this repo deploys (Flux / GitOps)**

1. **`ConfigMap` `kafka-metrics`** (`infrastructure/configs/base/kafka/kafka-metrics-configmap.yaml`) — JMX Prometheus exporter rules for Kafka and ZooKeeper (from [Strimzi 0.41 examples](https://github.com/strimzi/strimzi-kafka-operator/blob/0.41.0/packaging/examples/metrics/kafka-metrics.yaml)).
2. **`Kafka` `platform-cluster`** (`infrastructure/configs/base/kafka/kafka-cluster.yaml`) — `spec.kafka.metricsConfig` and `spec.zookeeper.metricsConfig` reference that ConfigMap so Strimzi exposes **`tcp-prometheus`** (`/metrics`) on broker and ZooKeeper pods.
3. **`PodMonitor` `strimzi-kafka-brokers`** (`infrastructure/controllers/base/monitoring/strimzi-kafka-podmonitor.yaml`) — scrapes Kafka broker pods in namespace **`kafka`** with labels `strimzi.io/cluster=platform-cluster`, `strimzi.io/kind=Kafka`, for **kube-prometheus-stack** (`release: kube-prometheus-stack`).

**Apply order:** `infra-controllers` (Prometheus Operator + PodMonitor CRD) → `infra-configs` (ConfigMap + Kafka CR) → reconcile; Strimzi will roll Kafka/ZooKeeper pods after metrics are enabled.

**Grafana import**

1. **Dashboards → Import** → ID **24626** (or upload JSON from the Grafana.com page).
2. **Datasource:** choose your in-cluster **Prometheus** (from kube-prometheus-stack), **not** a Kafka bootstrap URL.
3. **Variables:** set **`kubernetes_namespace`** to **`kafka`**, **`strimzi_cluster_name`** to **`platform-cluster`** (defaults match this repo).

**Verify Prometheus**

- **Status → Targets** in Prometheus UI: look for **`strimzi-kafka-brokers`** (or pod targets under namespace `kafka` on path `/metrics`).
- **Graph:** `java_lang_memory_heapmemoryusage_used` or `kafka_server_brokertopicmetrics_messagesinpersec` should return series after scrape succeeds.

### Kafka plugins: Prometheus vs direct broker connection

Most Strimzi / JVM dashboards (including **24626**) use **Prometheus** only. They query `kafka_*`, `kafka_server_*`, `java_lang_*`, etc., scraped from JMX. You **do not** enter bootstrap servers in Grafana for those—only the **Prometheus** datasource.

If your dashboard or a **Grafana Kafka plugin** asks for a **direct broker connection** (bootstrap servers, client id, security protocol), use values aligned with this repo’s Strimzi `Kafka` (`infrastructure/configs/base/kafka/kafka-cluster.yaml`): **plain** listener, **no TLS**, **no SASL**.

| Field | Value |
|-------|--------|
| **Bootstrap servers** | `platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092` |
| **Client ID** | Any unique logical id for Grafana (e.g. `grafana-kafka-overview` or `grafana-ds-1`). Not a Kubernetes ServiceAccount; used only as the Kafka client `client.id` if the plugin opens a client to the cluster. |
| **Security protocol** | **`PLAINTEXT`** (no TLS on the `plain` listener; not `SASL_SSL` / `SSL` unless you add listeners and TLS in Strimzi). |

If the form also has **SASL**: leave disabled / none for this dev stack. If you add TLS to Strimzi later, switch to **`SSL`** or **`SASL_SSL`** and configure truststore/keystore per Strimzi docs.

Grafana runs in **`monitoring`**; the bootstrap DNS above resolves cluster-wide. For a Grafana instance **outside** the cluster you would need an ingress/NodePort on Kafka or port-forward to a broker—out of scope for the default in-cluster setup.

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
