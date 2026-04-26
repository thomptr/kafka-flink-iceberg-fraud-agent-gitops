import operator
from typing import Annotated

from typing_extensions import TypedDict


class FraudInvestigationState(TypedDict):
    alert_id: str
    transaction_id: str
    user_id: int
    amount: float
    fraud_probability: float
    merchant: str | None
    route: str
    transaction_history: Annotated[list[dict], operator.add]
    feature_values: dict | None
    pattern_stats: dict | None
    snapshot_ids: Annotated[dict, lambda a, b: {**a, **b}]
    severity: str
    sla_deadline: str | None
    explanation: str
    evidence: list[dict]
    recommended_action: str
    confidence: float | None
    final_action: str
    rule_matched: str
    iceberg_snapshot_id: int | None
    kafka_delivered: bool
    tool_errors: Annotated[list[str], operator.add]
    error: str | None
