from datetime import datetime, timezone

import structlog

from app.agents.state import FraudInvestigationState
from app.config import settings

log = structlog.get_logger(__name__)


async def report_node(state: FraudInvestigationState, config: dict | None = None) -> dict:
    configurable = (config or {}).get("configurable", {})
    investigation_id = configurable.get("investigation_id", "unknown")
    started_at_raw = configurable.get("started_at")
    started_at = started_at_raw if isinstance(started_at_raw, datetime) else datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)

    from app.services.report_writer import write_investigation_report
    snapshot_id = write_investigation_report(
        dict(state), investigation_id, started_at, completed_at
    )

    # Publish investigation_completed to fraud-notifications (non-fatal)
    kafka_delivered = False
    try:
        from app.tools.kafka_producer_tool import publish_kafka_event
        result = publish_kafka_event.invoke({
            "topic": settings.KAFKA_FRAUD_NOTIFICATIONS_TOPIC,
            "event_type": "investigation_completed",
            "payload": {
                "alert_id": state["alert_id"],
                "final_action": state.get("final_action"),
                "iceberg_snapshot_id": snapshot_id,
                "investigation_id": investigation_id,
            },
            "key": state["alert_id"],
        })
        kafka_delivered = result.get("delivered", False)
    except Exception as exc:
        log.warning("report_kafka_error", alert_id=state["alert_id"], error=str(exc))

    log.info(
        "report_written",
        investigation_id=investigation_id,
        alert_id=state["alert_id"],
        iceberg_snapshot_id=snapshot_id,
        kafka_delivered=kafka_delivered,
    )
    return {"iceberg_snapshot_id": snapshot_id, "kafka_delivered": kafka_delivered}
