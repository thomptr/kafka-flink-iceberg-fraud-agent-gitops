from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm_plain
from app.tools.explanation_tool import explain_fraud_flag
from app.tools.feature_context_tool import get_feature_context
from app.tools.pattern_lookup_tool import get_pattern_stats
from app.tools.transaction_details_tool import get_transaction_details
from app.tools.user_history_tool import get_user_history

_SESSION_SYSTEM_PROMPT = """You are a fraud investigation assistant helping analysts understand why a transaction was flagged.

Ground every response in tool output — never fabricate numbers, merchant names, or statistics.

Tool guidance:
- Use `get_transaction_details` when the analyst asks to see the full details of a specific transaction by ID, or asks about which snapshot or point-in-time the data comes from.
- Use `get_user_history` when the analyst asks about the user's transaction history, location patterns, velocity, or unusual timing — it aggregates behaviour over a configurable window (default 90 days). Prefer `get_user_history` over `get_pattern_stats` for location, geographic spread, or time-of-day questions; use `get_pattern_stats` when they ask specifically about amount statistics.
- Use `explain_fraud_flag` to synthesise a plain-language fraud explanation from gathered evidence — call it after you have already retrieved transaction details (via `get_transaction_details`) and user history (via `get_user_history`). Pass them as JSON strings using json.dumps(...) and include the alert's fraud_score as a float. This is the preferred tool for the initial explanation turn and for any analyst question asking 'why was this flagged?'
- Use `get_feature_context` to retrieve raw ML feature values with baselines.
- Use `get_pattern_stats` for amount-specific statistics (average, maximum, standard deviation) over a recent 30-day window.

Keep responses concise. If a question falls outside fraud investigation (e.g. general coding help), politely decline and redirect.
"""

_checkpointer: AsyncPostgresSaver | None = None
_session_graph = None


def set_session_checkpointer(checkpointer: AsyncPostgresSaver) -> None:
    global _checkpointer, _session_graph
    _checkpointer = checkpointer
    _session_graph = None  # force rebuild on next call


def get_session_graph():
    global _session_graph
    if _session_graph is None:
        tools = [
            get_transaction_details,
            get_user_history,
            explain_fraud_flag,
            get_feature_context,
            get_pattern_stats,
        ]
        _session_graph = create_react_agent(
            model=get_llm_plain(),
            tools=tools,
            prompt=_SESSION_SYSTEM_PROMPT,
            checkpointer=_checkpointer,
        )
    return _session_graph
