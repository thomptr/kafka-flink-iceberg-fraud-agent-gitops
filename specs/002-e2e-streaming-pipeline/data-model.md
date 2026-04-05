# Data Model: Synthetic credit-card streaming pipeline

**Feature**: `002-e2e-streaming-pipeline`  
**Date**: 2026-04-04

## Kafka: `CreditCardTransaction` (input)

Logical fields (see `contracts/kafka-transaction-event.md` for wire format):

| Field | Type | Notes |
|-------|------|--------|
| `event_id` | string (UUID) | Idempotency key for dedup experiments |
| `ts` | string (ISO-8601 UTC) | Event time |
| `card_id` | string | Tokenized or synthetic identifier |
| `amount` | decimal / scaled long | Currency minor units optional |
| `currency` | string | ISO 4217 |
| `merchant_id` | string | Synthetic |
| `mcc` | string | Merchant category code |
| `country` | string | ISO 3166-1 alpha-2 |

## Flink: `EnrichedTransaction` (output / Iceberg row)

Extends input with **derived** fields:

| Field | Type | Notes |
|-------|------|--------|
| *(all input columns)* | | Preserved or renamed for clarity |
| `window_start` | timestamp | Tumbling or sliding window start (processing or event time per job config) |
| `txn_count_10m` | long | Count per `card_id` in last 10 minutes |
| `amount_z` | double | Optional; null if insufficient history |
| `high_velocity` | boolean | Flag if `txn_count_10m` exceeds threshold |
| `ingest_ts` | timestamp | When Flink processed the record |

## Iceberg table

- **Catalog**: Polaris (`quickstart_catalog` or feature-specific catalog name TBD in implementation).  
- **Identifier**: e.g. `fraud.analytics.enriched_txn` (namespace + table).  
- **Partitioning**: **daily** on `ts` or `window_start` (implementation choice; document in job).  
- **Format**: Iceberg v2, Parquet.

## Relationships

- **1:N** Kafka messages → Flink state keyed by **`card_id`** for rolling features.  
- **1:1** enriched logical row → **append** to Iceberg (no upsert required in v1 unless fraud rules require corrections—out of scope).

## Validation rules

- **Reject** records with missing `event_id`, `ts`, or `card_id` (side output or metrics counter).  
- **Clamp** negative amounts to error stream.  
- **Schema evolution**: additive columns only in v1; breaking changes require new table or migration task.
