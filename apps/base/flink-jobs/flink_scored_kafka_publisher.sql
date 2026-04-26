-- Flink SQL job: read transactions_scored Iceberg table (streaming) and publish to scored-transactions Kafka topic.
-- Runtime mode: STREAMING (incremental read from Iceberg via Polaris REST catalog)

SET 'parallelism.default' = '1';

-- Polaris REST catalog (same credentials as flink_streaming_job.sql — overridden at runtime by SqlRunner)
CREATE CATALOG polaris_catalog WITH (
  'type' = 'iceberg',
  'catalog-type' = 'rest',
  'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',
  'warehouse' = 'quickstart_catalog',
  'credential' = 'root:changeme',
  'scope' = 'PRINCIPAL_ROLE:ALL'
);

-- Kafka sink for scored transactions
CREATE TABLE scored_transactions_kafka (
  transaction_id STRING,
  user_id INT,
  amount DOUBLE,
  merchant STRING,
  fraud_probability DOUBLE,
  amount_velocity_5min DOUBLE,
  distance_from_home_km DOUBLE,
  ts TIMESTAMP(3),
  processing_time TIMESTAMP(3)
) WITH (
  'connector' = 'kafka',
  'topic' = 'scored-transactions',
  'properties.bootstrap.servers' = 'platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092',
  'format' = 'json',
  'json.timestamp-format.standard' = 'ISO-8601'
);

-- Stream scored transactions from Iceberg to Kafka
INSERT INTO scored_transactions_kafka
SELECT
  transaction_id,
  user_id,
  CAST(amount AS DOUBLE),
  merchant,
  CAST(fraud_probability AS DOUBLE),
  CAST(amount_velocity_5min AS DOUBLE),
  CAST(distance_from_home_km AS DOUBLE),
  CAST(ts AS TIMESTAMP(3)),
  CAST(processing_time AS TIMESTAMP(3))
FROM polaris_catalog.`default`.transactions_scored;
