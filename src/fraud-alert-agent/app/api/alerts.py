from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import verify_api_key
from app.services.alert_service import get_alert, list_alerts

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/alerts")
async def get_alerts(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    final_action: str | None = Query(None),
    from_time: datetime | None = Query(None),
    to_time: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    alerts, total = await list_alerts(
        severity=severity,
        status=status,
        final_action=final_action,
        from_time=from_time,
        to_time=to_time,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_alert(a) for a in alerts],
    }


@router.get("/alerts/{alert_id}")
async def get_alert_detail(alert_id: str) -> dict:
    alert = await get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _serialize_alert(alert, detailed=True)


def _serialize_alert(alert: Any, detailed: bool = False) -> dict:
    data = {
        "id": str(alert.id),
        "transaction_id": alert.transaction_id,
        "user_id": alert.user_id,
        "amount": float(alert.amount),
        "merchant": alert.merchant,
        "fraud_probability": float(alert.fraud_probability),
        "severity": alert.severity,
        "status": alert.status,
        "recommended_action": alert.recommended_action,
        "final_action": alert.final_action,
        "sla_deadline": alert.sla_deadline.isoformat() if alert.sla_deadline else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }
    if detailed:
        data["summary"] = alert.summary
        data["investigation_id"] = str(alert.investigation_id) if alert.investigation_id else None
    return data
