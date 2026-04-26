import structlog

from app.agents.state import FraudInvestigationState
from app.config import settings

log = structlog.get_logger(__name__)

ROUTE_CRITICAL = "CRITICAL"
ROUTE_STANDARD = "STANDARD"
ROUTE_MONITOR_ONLY = "MONITOR_ONLY"
ROUTE_FALSE_POSITIVE = "FALSE_POSITIVE"


def supervisor_node(state: FraudInvestigationState) -> dict:
    p = state["fraud_probability"]
    if p >= settings.FRAUD_THRESHOLD_CRITICAL:
        route = ROUTE_CRITICAL
    elif p >= settings.FRAUD_THRESHOLD_HIGH:
        route = ROUTE_STANDARD
    elif p >= settings.FRAUD_THRESHOLD_MEDIUM:
        route = ROUTE_MONITOR_ONLY
    else:
        route = ROUTE_FALSE_POSITIVE

    log.info(
        "supervisor_routed",
        transaction_id=state["transaction_id"],
        fraud_probability=p,
        route=route,
    )
    return {"route": route}
