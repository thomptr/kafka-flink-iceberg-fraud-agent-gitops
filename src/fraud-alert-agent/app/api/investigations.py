from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import verify_api_key
from app.db.base import AsyncSessionLocal
from app.db.models import FraudAlert, Investigation, InvestigationStep

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/alerts/{alert_id}/investigation")
async def get_investigation(alert_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        alert_result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        alert = alert_result.scalars().first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if not alert.investigation_id:
            raise HTTPException(status_code=404, detail="No investigation found for this alert")

        inv_result = await session.execute(
            select(Investigation).where(Investigation.id == alert.investigation_id)
        )
        investigation = inv_result.scalars().first()
        if not investigation:
            raise HTTPException(status_code=404, detail="Investigation not found")

        steps_result = await session.execute(
            select(InvestigationStep)
            .where(InvestigationStep.investigation_id == investigation.id)
            .order_by(InvestigationStep.step_order)
        )
        steps = steps_result.scalars().all()

    return {
        "investigation_id": str(investigation.id),
        "alert_id": alert_id,
        "status": investigation.status,
        "confidence": float(investigation.confidence) if investigation.confidence else None,
        "started_at": investigation.started_at.isoformat() if investigation.started_at else None,
        "completed_at": investigation.completed_at.isoformat() if investigation.completed_at else None,
        "steps": [_serialize_step(s) for s in steps],
    }


def _serialize_step(step: InvestigationStep) -> dict:
    output = step.output or {}
    data: dict = {
        "step_order": step.step_order,
        "node_name": step.node_name,
        "tool_name": step.tool_name,
        "duration_ms": step.duration_ms,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }
    # Expose key output fields per step
    if step.step_order == 1:
        data["snapshot_ids"] = output.get("snapshot_ids")
    elif step.step_order == 2:
        data["model_version"] = output.get("model_version")
        data["run_id"] = output.get("run_id")
    elif step.step_order == 3:
        data["rule_matched"] = output.get("rule_matched")
    elif step.step_order == 4:
        data["kafka_delivered"] = output.get("kafka_delivered")
        data["kafka_topic"] = output.get("kafka_topic")
    elif step.step_order == 5:
        data["iceberg_snapshot_id"] = output.get("iceberg_snapshot_id")
        data["kafka_delivered"] = output.get("kafka_delivered")
    return data
