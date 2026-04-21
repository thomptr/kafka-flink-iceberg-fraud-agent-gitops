-- Creates the transactions_scored Iceberg table via the Polaris REST catalog.
-- Credential is overridden at runtime by SqlRunner when POLARIS_OAUTH_* env is set.
CREATE CATALOG polaris_catalog WITH (
  'type' = 'iceberg',
  'catalog-type' = 'rest',
  'uri' = 'http://polaris.polaris.svc.cluster.local:8181/api/catalog',
  'warehouse' = 'quickstart_catalog',
  'credential' = 'root:changeme',
  'scope' = 'PRINCIPAL_ROLE:ALL'
);

CREATE DATABASE IF NOT EXISTS `polaris_catalog`.`default`;

CREATE TABLE IF NOT EXISTS `polaris_catalog`.`default`.`transactions_scored` (
  transaction_id STRING,
  user_id INT,
  amount DOUBLE,
  merchant STRING,
  lat DOUBLE,
  lon DOUBLE,
  ts TIMESTAMP(3),
  processing_time TIMESTAMP(3),
  amount_velocity_5min DOUBLE,
  distance_from_home_km DOUBLE,
  fraud_probability DOUBLE
) WITH (
  'format-version' = '2',
  'write.distribution-mode' = 'hash'
);
