import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import DecisionEvent, FraudAlert, Investigation, InvestigationStep

log = structlog.get_logger(__name__)

_INVESTIGATION_TIMEOUT = 300  # 5 minutes


async def start_investigation(alert: FraudAlert, initial_state: dict) -> None:
    from app.agents.graph import compiled_graph
    from app.agents.trace_callbacks import FraudGraphTraceCallback

    investigation_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        investigation = Investigation(
            id=uuid.UUID(investigation_id),
            alert_id=alert.id,
            status="running",
            started_at=started_at,
        )
        session.add(investigation)
        alert.investigation_id = uuid.UUID(investigation_id)
        alert.updated_at = datetime.now(timezone.utc)
        await session.commit()

    callback = FraudGraphTraceCallback(alert_id=str(alert.id))
    config = {
        "configurable": {
            "thread_id": str(alert.id),
            "investigation_id": investigation_id,
            "started_at": started_at,
        },
        "callbacks": [callback],
    }

    try:
        final_state = await asyncio.wait_for(
            compiled_graph.ainvoke(initial_state, config=config),
            timeout=_INVESTIGATION_TIMEOUT,
        )
        callback.end_root_span()

        completed_at = datetime.now(timezone.utc)
        await _record_steps(investigation_id, final_state, started_at)
        await _finalize_investigation(investigation_id, alert.id, final_state, completed_at)

    except asyncio.TimeoutError:
        callback.end_root_span(error=TimeoutError("investigation timeout"))
        log.warning("investigation_timeout", alert_id=str(alert.id))
        await _handle_timeout(investigation_id, alert.id)

    except Exception as exc:
        callback.end_root_span(error=exc)
        log.warning("investigation_error", alert_id=str(alert.id), error=str(exc))
        await _handle_error(investigation_id, alert.id, str(exc))


async def _record_steps(investigation_id: str, state: dict, started_at: datetime) -> None:
    inv_uuid = uuid.UUID(investigation_id)
    steps = [
        (0, "supervisor_node", {"route": state.get("route")}),
        (1, "data_query_node", {
            "snapshot_ids": state.get("snapshot_ids"),
            "tool_errors": state.get("tool_errors"),
        }),
        (2, "analysis_node", {
            "recommended_action": state.get("recommended_action"),
            "confidence": state.get("confidence"),
            "explanation_length": len(state.get("explanation", "")),
        }),
        (3, "recommendation_node", {
            "final_action": state.get("final_action"),
            "rule_matched": state.get("rule_matched"),
        }),
        (4, "escalation_node", {
            "final_action": state.get("final_action"),
            "kafka_delivered": state.get("kafka_delivered"),
            "kafka_topic": __import__("app.config", fromlist=["settings"]).settings.KAFKA_FRAUD_ALERTS_TOPIC,
        }),
        (5, "report_node", {
            "iceberg_snapshot_id": state.get("iceberg_snapshot_id"),
            "kafka_delivered": state.get("kafka_delivered"),
            "kafka_topic": __import__("app.config", fromlist=["settings"]).settings.KAFKA_FRAUD_NOTIFICATIONS_TOPIC,
            "report_written_at": datetime.now(timezone.utc).isoformat(),
        }),
    ]
    async with AsyncSessionLocal() as session:
        for step_order, node_name, output in steps:
            step = InvestigationStep(
                id=uuid.uuid4(),
                investigation_id=inv_uuid,
                step_order=step_order,
                node_name=node_name,
                output=output,
            )
            session.add(step)
        await session.commit()


async def _finalize_investigation(
    investigation_id: str, alert_id, final_state: dict, completed_at: datetime
) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Investigation).where(Investigation.id == uuid.UUID(investigation_id))
        )
        investigation = result.scalars().first()
        if investigation:
            investigation.status = "completed"
            investigation.completed_at = completed_at
            investigation.confidence = final_state.get("confidence")
            investigation.evidence = final_state.get("evidence")
            investigation.reasoning = final_state.get("explanation")

        alert_result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        alert = alert_result.scalars().first()
        if alert:
            alert.summary = final_state.get("explanation")
            alert.recommended_action = final_state.get("recommended_action")
            alert.final_action = final_state.get("final_action")
            alert.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def _handle_timeout(investigation_id: str, alert_id) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Investigation).where(Investigation.id == uuid.UUID(investigation_id))
        )
        investigation = result.scalars().first()
        if investigation:
            investigation.status = "timed_out"
            investigation.completed_at = datetime.now(timezone.utc)

        event = DecisionEvent(
            id=uuid.uuid4(),
            alert_id=alert_id,
            actor="agent",
            action="escalate",
            reason="timeout",
        )
        session.add(event)
        await session.commit()


async def _handle_error(investigation_id: str, alert_id, error_msg: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Investigation).where(Investigation.id == uuid.UUID(investigation_id))
        )
        investigation = result.scalars().first()
        if investigation:
            investigation.status = "error"
            investigation.completed_at = datetime.now(timezone.utc)
        await session.commit()
