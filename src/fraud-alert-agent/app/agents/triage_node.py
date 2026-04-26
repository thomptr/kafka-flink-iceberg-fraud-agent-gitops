from datetime import datetime, timedelta, timezone

import structlog

from app.agents.state import FraudInvestigationState

log = structlog.get_logger(__name__)

_SLA_OFFSETS = {
    "critical": timedelta(minutes=30),
    "high": timedelta(hours=2),
    "medium": timedelta(hours=8),
    "low": timedelta(hours=24),
}

_ROUTE_TO_SEVERITY = {
    "CRITICAL": "critical",
    "STANDARD": "high",
    "MONITOR_ONLY": "medium",
    "FALSE_POSITIVE": "low",
}


def triage_node(state: FraudInvestigationState) -> dict:
    route = state.get("route", "MONITOR_ONLY")
    severity = _ROUTE_TO_SEVERITY.get(route, "medium")
    deadline = datetime.now(timezone.utc) + _SLA_OFFSETS.get(severity, timedelta(hours=8))
    log.info("triage_classified", alert_id=state["alert_id"], severity=severity)
    return {"severity": severity, "sla_deadline": deadline.isoformat()}
