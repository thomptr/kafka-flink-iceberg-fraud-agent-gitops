from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import FraudAlert

log = structlog.get_logger(__name__)

_SLA_OFFSETS = {
    "critical": timedelta(minutes=30),
    "high": timedelta(hours=2),
    "medium": timedelta(hours=8),
    "low": timedelta(hours=24),
}


def compute_sla_deadline(severity: str) -> datetime:
    offset = _SLA_OFFSETS.get(severity, timedelta(hours=8))
    return datetime.now(timezone.utc) + offset


async def get_breached_alerts() -> list[FraudAlert]:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FraudAlert).where(
                FraudAlert.sla_deadline < now,
                FraudAlert.status.in_(["open", "in_review"]),
            )
        )
        return list(result.scalars().all())
