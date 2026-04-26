import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.models import DecisionEvent, FraudAlert

log = structlog.get_logger(__name__)

_SWEEP_INTERVAL_SECONDS = 60


async def run_sla_worker() -> None:
    log.info("sla_worker_started")
    while True:
        try:
            await _sweep()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.warning("sla_worker_error", error=str(exc))
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
    log.info("sla_worker_stopped")


async def _sweep() -> None:
    from app.services.sla_service import get_breached_alerts
    from app.services.notification_service import send_slack_notification
    from app.tools.kafka_producer_tool import publish_kafka_event

    alerts = await get_breached_alerts()
    for alert in alerts:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(FraudAlert).where(FraudAlert.id == alert.id)
                )
                a = result.scalars().first()
                if a:
                    a.status = "sla_breached"
                    a.final_action = "escalate"
                    a.updated_at = datetime.now(timezone.utc)

                event = DecisionEvent(
                    id=uuid.uuid4(),
                    alert_id=alert.id,
                    actor="sla_bot",
                    action="escalate",
                    reason="SLA deadline exceeded",
                )
                session.add(event)
                await session.commit()

            await send_slack_notification(
                {
                    "alert_id": str(alert.id),
                    "transaction_id": alert.transaction_id,
                    "severity": alert.severity,
                    "amount": float(alert.amount),
                    "fraud_probability": float(alert.fraud_probability),
                    "explanation": f"SLA breached for alert {alert.id}",
                },
                "escalate",
            )

            publish_kafka_event.invoke({
                "topic": settings.KAFKA_FRAUD_ALERTS_TOPIC,
                "event_type": "sla_breached",
                "payload": {
                    "alert_id": str(alert.id),
                    "severity": alert.severity,
                    "sla_deadline": alert.sla_deadline.isoformat() if alert.sla_deadline else None,
                },
                "key": str(alert.id),
            })

            log.info("sla_breach_escalated", alert_id=str(alert.id), severity=alert.severity)
        except Exception as exc:
            log.warning("sla_sweep_alert_error", alert_id=str(alert.id), error=str(exc))
