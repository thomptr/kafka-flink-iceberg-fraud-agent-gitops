"""Async synthetic credit-card-style JSON events into Kafka (matches Flink SQL schema)."""

from __future__ import annotations

import asyncio
import json
import os
import random
import uuid
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer
from faker import Faker

_fake = Faker()


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return v


def _build_record() -> dict:
    lat, lon = float(_fake.latitude()), float(_fake.longitude())
    return {
        "transaction_id": str(uuid.uuid4()),
        "user_id": random.randint(1, 50_000),
        "amount": round(random.uniform(1.0, 500.0), 2),
        "merchant": _fake.company(),
        "lat": lat,
        "lon": lon,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }


async def _run() -> None:
    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS")
    topic = os.environ.get("KAFKA_TOPIC", "transactions")
    rate = float(os.environ.get("EVENTS_PER_SEC", "10"))

    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap.split(","),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: str(k).encode("utf-8") if k is not None else None,
    )
    await producer.start()
    try:
        interval = 1.0 / max(rate, 0.1)
        while True:
            rec = _build_record()
            key = str(rec["user_id"])
            await producer.send_and_wait(topic, value=rec, key=key)
            await asyncio.sleep(interval)
    finally:
        await producer.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
