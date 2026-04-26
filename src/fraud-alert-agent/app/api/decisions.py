import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import verify_api_key
from app.db.base import AsyncSessionLocal
from app.db.models import DecisionEvent, FraudAlert

router = APIRouter(dependencies=[Depends(verify_api_key)])


class DecisionCreate(BaseModel):
    actor: str
    action: str
    outcome: str | None = None
    reason: str | None = None


@router.post("/alerts/{alert_id}/decisions")
async def create_decision(alert_id: str, body: DecisionCreate) -> dict:
    if body.action == "approve" and not body.outcome:
        raise HTTPException(status_code=400, detail="outcome is required for approve action")
    if body.action == "override" and not body.reason:
        raise HTTPException(status_code=400, detail="reason is required for override action")

    async with AsyncSessionLocal() as session:
        alert_result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        alert = alert_result.scalars().first()
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        event = DecisionEvent(
            id=uuid.uuid4(),
            alert_id=uuid.UUID(alert_id),
            actor=body.actor,
            action=body.action,
            outcome=body.outcome,
            reason=body.reason,
        )
        session.add(event)

        if body.action in ("approve", "override"):
            alert.status = "resolved"
            alert.updated_at = datetime.now(timezone.utc)

        await session.commit()
        return {
            "id": str(event.id),
            "alert_id": alert_id,
            "actor": event.actor,
            "action": event.action,
            "outcome": event.outcome,
            "reason": event.reason,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }


@router.get("/alerts/{alert_id}/decisions")
async def list_decisions(alert_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DecisionEvent)
            .where(DecisionEvent.alert_id == alert_id)
            .order_by(DecisionEvent.created_at)
        )
        events = result.scalars().all()
        return [
            {
                "id": str(e.id),
                "alert_id": str(e.alert_id),
                "actor": e.actor,
                "action": e.action,
                "outcome": e.outcome,
                "reason": e.reason,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
