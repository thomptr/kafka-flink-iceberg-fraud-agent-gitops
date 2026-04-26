import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache

import structlog
from aiokafka import AIOKafkaConsumer
from confluent_kafka import Consumer, KafkaError, Producer
from confluent_kafka.admin import AdminClient
from langchain_core.tools import tool
from pydantic import BaseModel

from app.config import settings

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _get_producer() -> Producer:
    return Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})


class KafkaEventInput(BaseModel):
    topic: str
    event_type: str
    payload: dict
    key: str | None = None


@tool(args_schema=KafkaEventInput)
def publish_kafka_event(topic: str, event_type: str, payload: dict, key: str | None = None) -> dict:
    """Publish a structured event to a Kafka topic."""
    try:
        producer = _get_producer()
        message = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "fraud-alert-agent",
            "payload": payload,
        }
        encoded = json.dumps(message).encode("utf-8")
        encoded_key = key.encode("utf-8") if key else None
        producer.produce(topic, value=encoded, key=encoded_key)
        producer.flush(timeout=5.0)
        log.info("kafka_event_published", topic=topic, event_type=event_type)
        return {"topic": topic, "event_type": event_type, "delivered": True, "error": None}
    except Exception as exc:
        log.warning("kafka_publish_error", topic=topic, event_type=event_type, error=str(exc))
        return {"topic": topic, "event_type": event_type, "delivered": False, "error": str(exc)}


@tool
def list_kafka_topics() -> list[str]:
    """List all non-internal Kafka topic names."""
    try:
        admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        metadata = admin.list_topics(timeout=5)
        return sorted(t for t in metadata.topics if not t.startswith("__"))
    except Exception as exc:
        log.warning("list_kafka_topics_error", error=str(exc))
        return []


def create_scored_transactions_consumer() -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        settings.KAFKA_SCORED_TRANSACTIONS_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_CONSUMER_GROUP_ID,
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="latest",
    )


@tool
def read_recent_kafka_messages(
    topic: str, max_messages: int = 10, timeout_seconds: float = 5.0
) -> list[dict]:
    """Read recent messages from a Kafka topic for inspection."""
    try:
        group_id = f"agent-inspector-{uuid.uuid4()}"
        consumer = Consumer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([topic])
        messages: list[dict] = []
        import time
        deadline = time.monotonic() + timeout_seconds
        while len(messages) < max_messages and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            msg = consumer.poll(timeout=min(1.0, remaining))
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    break
                continue
            try:
                messages.append(json.loads(msg.value().decode("utf-8")))
            except Exception:
                pass
        consumer.close()
        return messages
    except Exception as exc:
        log.warning("read_recent_kafka_messages_error", topic=topic, error=str(exc))
        return [{"error": str(exc)}]
