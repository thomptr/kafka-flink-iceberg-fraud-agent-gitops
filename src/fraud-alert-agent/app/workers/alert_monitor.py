import asyncio

import structlog
from aiokafka.errors import ConsumerStoppedError

from app.agents.state import FraudInvestigationState
from app.config import settings

log = structlog.get_logger(__name__)


async def run_alert_monitor() -> None:
    from app.agents.graph import build_graph, compiled_graph
    from app.services.alert_service import create_alert
    from app.services.investigation_service import start_investigation
    from app.tools.kafka_producer_tool import create_scored_transactions_consumer

    # Ensure graph is built before starting
    if compiled_graph is None:
        await build_graph()

    consumer = create_scored_transactions_consumer()
    await consumer.start()
    log.info("alert_monitor_started", topic=settings.KAFKA_SCORED_TRANSACTIONS_TOPIC)

    try:
        async for msg in consumer:
            try:
                record: dict = msg.value
                fraud_probability = float(record.get("fraud_probability", 0.0))

                if fraud_probability < settings.FRAUD_THRESHOLD_MEDIUM:
                    await consumer.commit()
                    continue

                transaction_id = str(record.get("transaction_id", ""))
                user_id = int(record.get("user_id", 0))
                amount = float(record.get("amount", 0.0))
                merchant = record.get("merchant")

                # Determine severity for alert creation
                if fraud_probability >= settings.FRAUD_THRESHOLD_CRITICAL:
                    severity = "critical"
                elif fraud_probability >= settings.FRAUD_THRESHOLD_HIGH:
                    severity = "high"
                else:
                    severity = "medium"

                log.info(
                    "alert_monitor_message",
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                    transaction_id=transaction_id,
                    fraud_probability=fraud_probability,
                )

                alert = await create_alert(
                    transaction_id=transaction_id,
                    user_id=user_id,
                    amount=amount,
                    fraud_probability=fraud_probability,
                    merchant=merchant,
                    severity=severity,
                )

                if alert is None:
                    # ON CONFLICT DO NOTHING — duplicate message, skip investigation
                    await consumer.commit()
                    continue

                initial_state = FraudInvestigationState(
                    alert_id=str(alert.id),
                    transaction_id=transaction_id,
                    user_id=user_id,
                    amount=amount,
                    fraud_probability=fraud_probability,
                    merchant=merchant,
                    route="",
                    transaction_history=[],
                    feature_values=None,
                    pattern_stats=None,
                    snapshot_ids={},
                    severity=severity,
                    sla_deadline=None,
                    explanation="",
                    evidence=[],
                    recommended_action="",
                    confidence=None,
                    final_action="",
                    rule_matched="",
                    iceberg_snapshot_id=None,
                    kafka_delivered=False,
                    tool_errors=[],
                    error=None,
                )

                await start_investigation(alert, initial_state)
                # Only commit after successful alert creation + investigation launch
                await consumer.commit()

            except ConsumerStoppedError:
                break
            except Exception as exc:
                log.warning("alert_monitor_error", error=str(exc))
                # Do NOT commit — message will be redelivered on pod restart

    except ConsumerStoppedError:
        pass
    finally:
        await consumer.stop()
        log.info("alert_monitor_stopped")
