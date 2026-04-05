# Synthetic transaction producer

Async Kafka producer using **aiokafka** and **faker**. Emits JSON compatible with `apps/base/flink-jobs/flink_streaming_job.sql` (`transaction_id`, `user_id`, `amount`, `merchant`, `lat`, `lon`, `ts`).

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | yes | Comma-separated brokers (in-cluster DNS). |
| `KAFKA_TOPIC` | no | Default `transactions`. |
| `EVENTS_PER_SEC` | no | Throttle (default `10`). |

Do **not** commit real cluster secrets or `.env` files with real passwords.

## Local build

```bash
docker build -t synthetic-transaction-producer:dev .
```

## Network

The producer must reach Kafka brokers on the cluster network. If you use namespaces, run the Deployment in the same cluster as Kafka (e.g. `kafka`) or ensure DNS/routing to `bootstrap` servers. See `deployment.yaml` for the chosen namespace.

This repo does not ship a `NetworkPolicy` for the producer. To restrict egress to Kafka only, add a policy in the `kafka` namespace that allows the producer pod to reach `platform-cluster-kafka-bootstrap` on port 9092 and blocks other egress as required by your security model.
