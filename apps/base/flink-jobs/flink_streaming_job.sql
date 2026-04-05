-- Polaris REST catalog (warehouse name must match Polaris; credential must match cluster secret — do not commit real passwords)
CREATE CATALOG polaris_catalog WITH (
  'type' = 'iceberg',
  'catalog-type' = 'rest',
  'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',
  'warehouse' = 'quickstart_catalog',
  'credential' = 'root:changeme',
  'scope' = 'PRINCIPAL_ROLE:ALL'
);

CREATE TABLE transactions_kafka (
  transaction_id STRING,
  user_id INT,
  amount DOUBLE,
  merchant STRING,
  lat DOUBLE,
  lon DOUBLE,
  ts TIMESTAMP(3),
  WATERMARK FOR ts AS ts - INTERVAL '5' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'transactions',
  'properties.bootstrap.servers' = 'platform-cluster-kafka-bootstrap.kafka.svc.cluster.local:9092',
  'format' = 'json',
  'scan.startup.mode' = 'earliest-offset'
);

CREATE TABLE IF NOT EXISTS polaris_catalog.default.transactions (
  transaction_id STRING,
  user_id INT,
  amount DOUBLE,
  merchant STRING,
  lat DOUBLE,
  lon DOUBLE,
  ts TIMESTAMP(3),
  processing_time TIMESTAMP(3),
  amount_velocity_5min DOUBLE,
  distance_from_home_km DOUBLE
) WITH (
  'format-version' = '2',
  'write.distribution-mode' = 'hash'
);

INSERT INTO polaris_catalog.default.transactions
SELECT
  transaction_id,
  user_id,
  amount,
  merchant,
  lat,
  lon,
  ts,
  CURRENT_TIMESTAMP AS processing_time,
  AVG(amount) OVER (PARTITION BY user_id ORDER BY ts RANGE BETWEEN INTERVAL '5' MINUTE PRECEDING AND CURRENT ROW) AS amount_velocity_5min,
  SQRT(POW(lat - 37.7749, 2) + POW(lon - -122.4194, 2)) * 111 AS distance_from_home_km
FROM transactions_kafka;
