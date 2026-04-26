import asyncio
import json
import time

import structlog

from app.agents.llm import get_llm
from app.agents.state import FraudInvestigationState
from app.config import settings
from app.tools.mlflow_tool import get_latest_model_version, get_run_details

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a fraud investigation analyst. Analyze the provided transaction data and return a JSON object with exactly these fields:
{
  "explanation": "<2-3 sentence explanation of why this transaction is or is not fraudulent>",
  "evidence": [
    {"rank": 1, "type": "transaction_history|pattern_deviation|feature_value|rule_match", "description": "<specific finding>", "weight": "high|medium|low"}
  ],
  "recommended_action": "block|review|monitor",
  "confidence": 0.0
}
Provide at least 3 evidence items. confidence must be between 0.0 and 1.0."""


async def analysis_node(state: FraudInvestigationState) -> dict:
    model_version: dict = {}
    run_details: dict = {}

    # Fetch MLflow model provenance (non-fatal)
    try:
        loop = asyncio.get_event_loop()
        model_version = await loop.run_in_executor(
            None, get_latest_model_version.invoke, {"model_name": settings.MLFLOW_FRAUD_MODEL_NAME}
        )
        if "run_id" in model_version and model_version["run_id"]:
            run_details = await loop.run_in_executor(
                None, get_run_details.invoke, {"run_id": model_version["run_id"]}
            )
    except Exception as exc:
        log.warning("analysis_mlflow_error", alert_id=state["alert_id"], error=str(exc))

    context = {
        "transaction_id": state["transaction_id"],
        "user_id": state["user_id"],
        "amount": state["amount"],
        "merchant": state.get("merchant"),
        "fraud_probability": state["fraud_probability"],
        "severity": state.get("severity"),
        "transaction_history": state.get("transaction_history", [])[:10],
        "feature_values": state.get("feature_values"),
        "pattern_stats": state.get("pattern_stats"),
        "model_version": model_version.get("version"),
        "model_metrics": run_details.get("metrics", {}),
    }

    llm = get_llm()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context, default=str)},
    ]

    t0 = time.monotonic()
    try:
        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=settings.ANALYSIS_TIMEOUT_SECONDS,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        raw = response.content if hasattr(response, "content") else str(response)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        explanation = parsed.get("explanation", "Analysis unavailable.")
        evidence = parsed.get("evidence", [])
        recommended_action = parsed.get("recommended_action", "review")
        confidence = float(parsed.get("confidence", 0.5))
        log.info(
            "analysis_complete",
            alert_id=state["alert_id"],
            recommended_action=recommended_action,
            confidence=confidence,
            duration_ms=duration_ms,
            mlflow_model_version=model_version.get("version"),
            mlflow_model_stage=model_version.get("stage"),
        )
        return {
            "explanation": explanation,
            "evidence": evidence,
            "recommended_action": recommended_action,
            "confidence": confidence,
        }
    except asyncio.TimeoutError:
        log.warning("analysis_timeout", alert_id=state["alert_id"])
        return {
            "explanation": "Analysis timed out. Manual review required.",
            "evidence": [],
            "recommended_action": "review",
            "confidence": None,
            "error": "analysis_timeout",
        }
    except Exception as exc:
        log.warning("analysis_error", alert_id=state["alert_id"], error=str(exc))
        return {
            "explanation": "Analysis failed. Manual review required.",
            "evidence": [],
            "recommended_action": "review",
            "confidence": None,
            "error": str(exc),
        }
