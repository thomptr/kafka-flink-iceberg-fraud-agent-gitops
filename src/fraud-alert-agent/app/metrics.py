from prometheus_client import Counter, Gauge, Histogram

fraud_alerts_total = Counter(
    "fraud_alerts_total",
    "Total fraud alerts created",
    ["severity", "route"],
)

analysis_node_duration_seconds = Histogram(
    "analysis_node_duration_seconds",
    "Duration of analysis_node LLM calls",
    ["model"],
    buckets=[1, 5, 10, 20, 30, 60],
)

final_actions_total = Counter(
    "final_actions_total",
    "Final actions taken on fraud alerts",
    ["final_action", "rule_matched"],
)

iceberg_query_tool_calls_total = Counter(
    "iceberg_query_tool_calls_total",
    "Total iceberg_query_tool calls",
    ["namespace", "table_name", "status"],
)

iceberg_query_tool_duration_seconds = Histogram(
    "iceberg_query_tool_duration_seconds",
    "Duration of iceberg_query_tool calls in seconds",
    buckets=[0.1, 0.5, 1, 2, 5, 10],
)

iceberg_writes_total = Counter(
    "iceberg_writes_total",
    "Total Iceberg write operations",
    ["table", "status"],
)

sla_breaches_total = Counter(
    "sla_breaches_total",
    "Total SLA breaches",
)

mlflow_tool_calls_total = Counter(
    "mlflow_tool_calls_total",
    "Total MLflow tool calls",
    ["tool", "status"],
)

mlflow_tool_duration_seconds = Histogram(
    "mlflow_tool_duration_seconds",
    "Duration of MLflow tool calls",
    buckets=[0.1, 0.5, 1, 2, 5],
)

kafka_producer_events_total = Counter(
    "kafka_producer_events_total",
    "Total Kafka events published",
    ["topic", "event_type", "status"],
)

kafka_producer_duration_seconds = Histogram(
    "kafka_producer_duration_seconds",
    "Duration of Kafka produce calls",
    buckets=[0.01, 0.05, 0.1, 0.5, 1],
)

kafka_consumer_messages_total = Counter(
    "kafka_consumer_messages_total",
    "Total Kafka consumer messages processed",
    ["topic", "status"],
)

kafka_consumer_lag = Gauge(
    "kafka_consumer_lag",
    "Current Kafka consumer group lag",
    ["topic", "group_id"],
)

investigation_session_opens_total = Counter(
    "investigation_session_opens_total",
    "Total investigation sessions opened",
)

investigation_session_turn_duration_seconds = Histogram(
    "investigation_session_turn_duration_seconds",
    "Duration of investigation session turns (LLM + tools)",
    buckets=[1, 2, 5, 10, 15, 20, 30],
)

investigation_conclusions_total = Counter(
    "investigation_conclusions_total",
    "Total investigation conclusions recorded",
    ["outcome"],
)

investigation_node_duration_seconds = Histogram(
    "investigation_node_duration_seconds",
    "Per-node duration for LangGraph investigation",
    ["node"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60],
)
