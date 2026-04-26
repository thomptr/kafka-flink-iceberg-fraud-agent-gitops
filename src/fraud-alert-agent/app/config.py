from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    ANALYSIS_TIMEOUT_SECONDS: int = 30
    FRAUD_API_KEY: str
    SLACK_WEBHOOK_URL: str = ""

    FRAUD_THRESHOLD_CRITICAL: float = 0.85
    FRAUD_THRESHOLD_HIGH: float = 0.70
    FRAUD_THRESHOLD_MEDIUM: float = 0.50
    BLOCK_CONFIDENCE_THRESHOLD: float = 0.85
    ESCALATE_CONFIDENCE_THRESHOLD: float = 0.90

    ICEBERG_CATALOG_URI: str = "http://localhost:8181/api/catalog"
    ICEBERG_WAREHOUSE: str = "fraud_warehouse"
    ICEBERG_INVESTIGATIONS_NAMESPACE: str = "fraud"
    POLARIS_CREDENTIAL: str = ""
    MINIO_ENDPOINT: str = "http://localhost:9000"
    AWS_ACCESS_KEY_ID: str = "minioadmin"
    AWS_SECRET_ACCESS_KEY: str = "minioadmin"

    MLFLOW_TRACKING_URI: str = "http://mlflow.mlflow.svc.cluster.local:5000"
    MLFLOW_FRAUD_MODEL_NAME: str = "fraud-score-xgboost"

    KAFKA_BOOTSTRAP_SERVERS: str = "platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092"
    KAFKA_FRAUD_ALERTS_TOPIC: str = "fraud-alert-events"
    KAFKA_FRAUD_NOTIFICATIONS_TOPIC: str = "fraud-notifications"
    KAFKA_SCORED_TRANSACTIONS_TOPIC: str = "scored-transactions"
    KAFKA_CONSUMER_GROUP_ID: str = "fraud-alert-agent"

    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "fraud-alert-agent"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector.fraud-agent.svc.cluster.local:4317"
    OTEL_SERVICE_NAME: str = "fraud-alert-agent"
    OTEL_TRACES_ENABLED: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
