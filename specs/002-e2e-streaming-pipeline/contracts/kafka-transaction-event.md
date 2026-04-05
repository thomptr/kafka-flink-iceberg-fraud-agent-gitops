# Contract: Kafka message — synthetic credit-card transaction

**Topic** (suggested): `synthetic.creditcard.txn` (actual name to match GitOps `KafkaTopic`).

**Wire format**: **JSON** (v1). Optional future: **Avro** + Schema Registry (out of scope until registered).

## JSON schema (informative)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["event_id", "ts", "card_id", "amount", "currency", "merchant_id", "mcc", "country"],
  "properties": {
    "event_id": { "type": "string", "format": "uuid" },
    "ts": { "type": "string", "description": "ISO-8601 UTC" },
    "card_id": { "type": "string", "minLength": 1 },
    "amount": { "type": "number" },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "merchant_id": { "type": "string" },
    "mcc": { "type": "string" },
    "country": { "type": "string", "pattern": "^[A-Z]{2}$" }
  },
  "additionalProperties": false
}
```

## Producer requirements

- **Key**: `card_id` (string) recommended for partition affinity.  
- **Value**: JSON payload as above.  
- **Ordering**: not guaranteed across partitions; Flink keyed state uses `card_id`.

## Versioning

- **v1**: This document. Breaking changes → new topic suffix (`.v2`) or new table with migration plan.
