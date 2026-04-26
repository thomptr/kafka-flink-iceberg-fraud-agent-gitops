import asyncio

import structlog

from app.agents.state import FraudInvestigationState
from app.config import settings

log = structlog.get_logger(__name__)

_CHANNEL_MAP = {
    "block": "#fraud-urgent",
    "escalate": "#fraud-escalations",
    "notify": "#fraud-alerts",
}


async def escalation_node(state: FraudInvestigationState) -> dict:
    route = state.get("route", "MONITOR_ONLY")
    final_action = state.get("final_action", "notify")

    if route == "MONITOR_ONLY":
        final_action = "notify"
    elif route == "FALSE_POSITIVE":
        final_action = "notify"

    # Send Slack notification (non-fatal)
    slack_ok = False
    try:
        from app.services.notification_service import send_slack_notification
        alert_summary = {
            "alert_id": state["alert_id"],
            "transaction_id": state["transaction_id"],
            "amount": state["amount"],
            "fraud_probability": state["fraud_probability"],
            "severity": state.get("severity", "medium"),
            "explanation": state.get("explanation", ""),
        }
        await send_slack_notification(alert_summary, final_action)
        slack_ok = True
    except Exception as exc:
        log.warning("escalation_slack_error", alert_id=state["alert_id"], error=str(exc))

    # Publish to fraud-alert-events Kafka topic (non-fatal)
    kafka_delivered = False
    try:
        from app.tools.kafka_producer_tool import publish_kafka_event
        result = publish_kafka_event.invoke({
            "topic": settings.KAFKA_FRAUD_ALERTS_TOPIC,
            "event_type": "escalation_triggered",
            "payload": {
                "alert_id": state["alert_id"],
                "final_action": final_action,
                "severity": state.get("severity"),
                "fraud_probability": state["fraud_probability"],
            },
            "key": state["alert_id"],
        })
        kafka_delivered = result.get("delivered", False)
    except Exception as exc:
        log.warning("escalation_kafka_error", alert_id=state["alert_id"], error=str(exc))

    log.info(
        "escalation_complete",
        alert_id=state["alert_id"],
        final_action=final_action,
        kafka_delivered=kafka_delivered,
        kafka_topic=settings.KAFKA_FRAUD_ALERTS_TOPIC,
    )
    return {"final_action": final_action, "kafka_delivered": kafka_delivered}
