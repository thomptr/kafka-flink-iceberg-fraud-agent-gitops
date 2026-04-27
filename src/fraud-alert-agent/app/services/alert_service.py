import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.base import AsyncSessionLocal
from app.db.models import FraudAlert
from app.services.sla_service import compute_sla_deadline

log = structlog.get_logger(__name__)


async def create_alert(
    transaction_id: str,
    user_id: int,
    amount: float,
    fraud_probability: float,
    merchant: str | None,
    severity: str,
) -> FraudAlert | None:
    sla_deadline = compute_sla_deadline(severity)
    async with AsyncSessionLocal() as session:
        stmt = (
            insert(FraudAlert)
            .values(
                id=uuid.uuid4(),
                transaction_id=transaction_id,
                user_id=user_id,
                amount=amount,
                merchant=merchant,
                fraud_probability=fraud_probability,
                severity=severity,
                status="open",
                sla_deadline=sla_deadline,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_fraud_alerts_transaction_id")
            .returning(FraudAlert)
        )
        result = await session.execute(stmt)
        await session.commit()
        row = result.first()
        if row is None:
            log.info("alert_duplicate_skipped", transaction_id=transaction_id)
            return None
        alert = row[0]
        log.info("alert_created", alert_id=str(alert.id), transaction_id=transaction_id)
        return alert


async def get_alert(alert_id: str) -> FraudAlert | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        return result.scalars().first()


async def get_alert_by_transaction_id(transaction_id: str) -> FraudAlert | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FraudAlert).where(FraudAlert.transaction_id == transaction_id)
        )
        return result.scalars().first()


async def update_alert_status(alert_id: str, status: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        alert = result.scalars().first()
        if alert:
            alert.status = status
            alert.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def update_alert_actions(
    alert_id: str,
    recommended_action: str | None = None,
    final_action: str | None = None,
    summary: str | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FraudAlert).where(FraudAlert.id == alert_id)
        )
        alert = result.scalars().first()
        if alert:
            if recommended_action is not None:
                alert.recommended_action = recommended_action
            if final_action is not None:
                alert.final_action = final_action
            if summary is not None:
                alert.summary = summary
            alert.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def list_alerts(
    severity: str | None = None,
    status: str | None = None,
    final_action: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FraudAlert], int]:
    async with AsyncSessionLocal() as session:
        query = select(FraudAlert)
        if severity:
            query = query.where(FraudAlert.severity == severity)
        if status:
            query = query.where(FraudAlert.status == status)
        if final_action:
            query = query.where(FraudAlert.final_action == final_action)
        if from_time:
            query = query.where(FraudAlert.created_at >= from_time)
        if to_time:
            query = query.where(FraudAlert.created_at <= to_time)

        count_result = await session.execute(
            select(__import__("sqlalchemy").func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        query = (
            query.order_by(FraudAlert.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(query)
        return list(result.scalars().all()), total
