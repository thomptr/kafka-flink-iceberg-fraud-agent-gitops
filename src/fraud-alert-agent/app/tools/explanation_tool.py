import concurrent.futures
import json

import structlog
from langchain_core.tools import tool

from app.agents.llm import get_llm_plain
from app.config import settings

log = structlog.get_logger(__name__)


@tool
def explain_fraud_flag(
    transaction_json: str,
    user_history_json: str,
    fraud_score: float,
) -> str:
    """Synthesise a plain-language fraud explanation from gathered evidence.

    Call this after you have already retrieved transaction details (via
    get_transaction_details) and user history (via get_user_history). Pass them as
    JSON strings using json.dumps(...) and include the alert's fraud_score as a float.
    This is the preferred tool for the initial explanation turn and for any analyst
    question asking 'why was this flagged?'
    """
    try:
        tx_dict = json.loads(transaction_json)
        history_dict = json.loads(user_history_json)
    except json.JSONDecodeError as exc:
        log.warning("explain_fraud_flag_parse_error", error=str(exc))
        return "Invalid input data — could not parse transaction or user history."

    system_msg = (
        f"Given this transaction details, user history, and model probability of "
        f"{fraud_score:.2%}, provide a clear, concise reason why it was flagged as "
        f"fraud. Highlight anomalies."
    )
    user_msg = json.dumps({"transaction": tx_dict, "user_history": history_dict}, default=str)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    llm = get_llm_plain()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(llm.invoke, messages)
            response = future.result(timeout=settings.ANALYSIS_TIMEOUT_SECONDS)
        return response.content
    except concurrent.futures.TimeoutError:
        log.warning("explain_fraud_flag_timeout", fraud_score=fraud_score)
        return "Explanation timed out — review the transaction data manually."
    except Exception as exc:
        log.warning("explain_fraud_flag_error", fraud_score=fraud_score, error=str(exc))
        return f"Explanation unavailable: {exc}"
