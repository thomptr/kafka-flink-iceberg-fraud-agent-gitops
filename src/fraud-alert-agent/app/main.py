import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.config import settings
from app.db.base import engine
from app.logging_config import configure_logging
from app.tracing import setup_tracing, shutdown_tracing

configure_logging()
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # OTEL must be first — registers TracerProvider before any instrumented code runs
    setup_tracing(app)

    if settings.LANGCHAIN_TRACING_V2 == "true" and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.agents.graph import build_graph
    from app.agents.investigation_session_graph import set_session_checkpointer
    from app.workers.alert_monitor import run_alert_monitor
    from app.workers.sla_worker import run_sla_worker

    pg_conn_string = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    async with AsyncPostgresSaver.from_conn_string(pg_conn_string) as checkpointer:
        await build_graph(checkpointer)
        set_session_checkpointer(checkpointer)

        monitor_task = asyncio.create_task(run_alert_monitor())
        sla_task = asyncio.create_task(run_sla_worker())

        log.info("fraud_alert_agent_started")
        yield

        monitor_task.cancel()
        sla_task.cancel()
        await asyncio.gather(monitor_task, sla_task, return_exceptions=True)

    await engine.dispose()
    shutdown_tracing()
    log.info("fraud_alert_agent_stopped")


app = FastAPI(title="Fraud Alert Agent", version="0.1.0", lifespan=lifespan)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    from app.db.base import AsyncSessionLocal
    from app.tools.iceberg_query_tool import list_iceberg_tables
    from app.tools.mlflow_tool import get_latest_model_version
    from app.tools.kafka_producer_tool import list_kafka_topics
    from confluent_kafka.admin import AdminClient
    import httpx

    checks: dict = {}

    # Postgres
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    # Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            checks["ollama"] = "ok" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as exc:
        checks["ollama"] = f"error: {exc}"

    # Polaris / Iceberg
    try:
        tables = list_iceberg_tables.invoke({"namespace": "fraud"})
        checks["polaris"] = "ok"
    except Exception as exc:
        checks["polaris"] = f"error: {exc}"

    # MLflow
    try:
        result = get_latest_model_version.invoke({"model_name": settings.MLFLOW_FRAUD_MODEL_NAME})
        checks["mlflow"] = "ok" if "error" not in result else f"error: {result['error']}"
    except Exception as exc:
        checks["mlflow"] = f"error: {exc}"

    # Kafka producer
    try:
        topics = list_kafka_topics.invoke({})
        checks["kafka_producer"] = "ok" if topics else "error: no topics"
    except Exception as exc:
        checks["kafka_producer"] = f"error: {exc}"

    # Kafka consumer
    try:
        admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
        admin.list_topics(timeout=3)
        checks["kafka_consumer"] = "ok"
    except Exception as exc:
        checks["kafka_consumer"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", **checks},
        status_code=status_code,
    )


# Routers are wired in as they are implemented
def _mount_routers() -> None:
    from app.api import alerts, investigations, decisions, metrics_api, sessions
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(investigations.router, prefix="/api/v1")
    app.include_router(decisions.router, prefix="/api/v1")
    app.include_router(metrics_api.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")


_mount_routers()
