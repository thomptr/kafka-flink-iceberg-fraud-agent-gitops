from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import verify_api_key
from app.db.base import AsyncSessionLocal
from app.db.models import DecisionEvent, FraudAlert, InvestigationStep

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/metrics")
async def get_metrics(window_hours: int = Query(24, ge=1, le=168)) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    async with AsyncSessionLocal() as session:
        # Total alerts in window
        count_result = await session.execute(
            select(func.count(FraudAlert.id)).where(FraudAlert.created_at >= since)
        )
        alert_count = count_result.scalar() or 0

        # Alerts by severity
        severity_result = await session.execute(
            select(FraudAlert.severity, func.count(FraudAlert.id))
            .where(FraudAlert.created_at >= since)
            .group_by(FraudAlert.severity)
        )
        route_distribution = {row[0]: row[1] for row in severity_result.all()}

        # Final action distribution
        action_result = await session.execute(
            select(FraudAlert.final_action, func.count(FraudAlert.id))
            .where(FraudAlert.created_at >= since, FraudAlert.final_action.isnot(None))
            .group_by(FraudAlert.final_action)
        )
        final_action_distribution = {row[0]: row[1] for row in action_result.all()}

        # Iceberg write success rate
        iceberg_steps = await session.execute(
            select(InvestigationStep)
            .where(
                InvestigationStep.step_order == 5,
                InvestigationStep.created_at >= since,
            )
        )
        all_report_steps = iceberg_steps.scalars().all()
        iceberg_written = sum(
            1 for s in all_report_steps if (s.output or {}).get("iceberg_snapshot_id") is not None
        )
        iceberg_write_success_rate = (
            iceberg_written / len(all_report_steps) if all_report_steps else 0.0
        )

        # Kafka delivery rate (escalation + report steps)
        kafka_steps = await session.execute(
            select(InvestigationStep)
            .where(
                InvestigationStep.step_order.in_([4, 5]),
                InvestigationStep.created_at >= since,
            )
        )
        all_kafka_steps = kafka_steps.scalars().all()
        kafka_delivered = sum(
            1 for s in all_kafka_steps if (s.output or {}).get("kafka_delivered") is True
        )
        kafka_delivery_rate = (
            kafka_delivered / len(all_kafka_steps) if all_kafka_steps else 0.0
        )

    # Kafka consumer lag
    kafka_consumer_lag: int | None = None
    try:
        from confluent_kafka.admin import AdminClient
        from app.config import settings
        admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        groups = admin.list_consumer_groups()
        consumer_groups = admin.list_consumer_group_offsets(
            [settings.KAFKA_CONSUMER_GROUP_ID]
        )
        # Simplified lag — just return 0 if reachable
        kafka_consumer_lag = 0
    except Exception:
        pass

    # MLflow model version
    mlflow_model_version: str | None = None
    try:
        from app.tools.mlflow_tool import get_latest_model_version
        from app.config import settings
        result = get_latest_model_version.invoke({"model_name": settings.MLFLOW_FRAUD_MODEL_NAME})
        mlflow_model_version = result.get("version")
    except Exception:
        pass

    return {
        "window_hours": window_hours,
        "alert_count": alert_count,
        "route_distribution": route_distribution,
        "final_action_distribution": final_action_distribution,
        "iceberg_write_success_rate": round(iceberg_write_success_rate, 4),
        "kafka_delivery_rate": round(kafka_delivery_rate, 4),
        "kafka_consumer_lag": kafka_consumer_lag,
        "mlflow_model_version_in_use": mlflow_model_version,
    }
