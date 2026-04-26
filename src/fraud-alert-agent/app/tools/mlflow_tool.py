import structlog
from langchain_core.tools import tool
from mlflow.tracking import MlflowClient
from pydantic import BaseModel

from app.config import settings

log = structlog.get_logger(__name__)


def _get_client() -> MlflowClient:
    return MlflowClient(tracking_uri=settings.MLFLOW_TRACKING_URI)


class MLFlowModelInput(BaseModel):
    model_name: str


class MLFlowRunInput(BaseModel):
    run_id: str


@tool(args_schema=MLFlowModelInput)
def get_latest_model_version(model_name: str) -> dict:
    """Return the latest registered MLflow model version metadata."""
    try:
        client = _get_client()
        versions = client.get_latest_versions(model_name, stages=["Production", "Staging", "None"])
        if not versions:
            return {"error": "no versions found", "model_name": model_name}
        best = max(versions, key=lambda v: int(v.version))
        log.info(
            "mlflow_model_version",
            model_name=model_name,
            version=best.version,
            stage=best.current_stage,
        )
        return {
            "model_name": model_name,
            "version": best.version,
            "stage": best.current_stage,
            "run_id": best.run_id,
            "source": best.source,
            "creation_timestamp": best.creation_timestamp,
            "description": best.description,
        }
    except Exception as exc:
        log.warning("mlflow_model_version_error", model_name=model_name, error=str(exc))
        return {"error": str(exc), "model_name": model_name}


@tool(args_schema=MLFlowRunInput)
def get_run_details(run_id: str) -> dict:
    """Return MLflow run metadata including metrics and params."""
    try:
        client = _get_client()
        run = client.get_run(run_id)
        return {
            "run_id": run_id,
            "status": run.info.status,
            "metrics": dict(run.data.metrics),
            "params": dict(run.data.params),
            "tags": dict(run.data.tags),
            "start_time": run.info.start_time,
            "end_time": run.info.end_time,
            "artifact_uri": run.info.artifact_uri,
        }
    except Exception as exc:
        log.warning("mlflow_run_details_error", run_id=run_id, error=str(exc))
        return {"error": str(exc), "run_id": run_id}
