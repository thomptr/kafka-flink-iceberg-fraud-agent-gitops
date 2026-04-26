import structlog

from app.agents.state import FraudInvestigationState
from app.config import settings

log = structlog.get_logger(__name__)


def recommendation_node(state: FraudInvestigationState) -> dict:
    recommended_action = state.get("recommended_action", "review")
    confidence = state.get("confidence")
    severity = state.get("severity", "medium")
    error = state.get("error")

    if (
        recommended_action == "block"
        and confidence is not None
        and confidence >= settings.BLOCK_CONFIDENCE_THRESHOLD
        and severity in ("critical", "high")
    ):
        final_action = "block"
        rule_matched = "block_threshold"
    elif (
        severity == "critical"
        or (confidence is not None and confidence >= settings.ESCALATE_CONFIDENCE_THRESHOLD)
        or error
    ):
        final_action = "escalate"
        rule_matched = "escalate_critical"
    else:
        final_action = "notify"
        rule_matched = "notify_default"

    log.info(
        "recommendation_decided",
        alert_id=state["alert_id"],
        final_action=final_action,
        rule_matched=rule_matched,
    )
    return {"final_action": final_action, "rule_matched": rule_matched}
