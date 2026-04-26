from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analysis_node import analysis_node
from app.agents.data_query_node import data_query_node
from app.agents.escalation_node import escalation_node
from app.agents.recommendation_node import recommendation_node
from app.agents.report_node import report_node
from app.agents.state import FraudInvestigationState
from app.agents.supervisor_node import supervisor_node, ROUTE_CRITICAL, ROUTE_STANDARD
from app.agents.triage_node import triage_node
from app.config import settings
from app.tools.iceberg_query_tool import list_iceberg_tables, query_iceberg_table
from app.tools.kafka_producer_tool import (
    list_kafka_topics,
    publish_kafka_event,
    read_recent_kafka_messages,
)
from app.tools.mlflow_tool import get_latest_model_version, get_run_details

compiled_graph = None
_checkpointer: AsyncPostgresSaver | None = None


def _route_from_supervisor(state: FraudInvestigationState) -> str:
    route = state.get("route", "MONITOR_ONLY")
    if route in (ROUTE_CRITICAL, ROUTE_STANDARD):
        return "triage_node"
    elif route == "MONITOR_ONLY":
        return "triage_monitor_only"
    else:
        return "escalation_node"


def _route_from_triage(state: FraudInvestigationState) -> str:
    route = state.get("route", "MONITOR_ONLY")
    if route in (ROUTE_CRITICAL, ROUTE_STANDARD):
        return "data_query_node"
    return "escalation_node"


async def build_graph() -> None:
    global compiled_graph, _checkpointer

    _checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    await _checkpointer.setup()

    builder = StateGraph(FraudInvestigationState)

    builder.add_node("supervisor_node", supervisor_node)
    builder.add_node("triage_node", triage_node)
    builder.add_node("data_query_node", data_query_node)
    builder.add_node("analysis_node", analysis_node)
    builder.add_node("recommendation_node", recommendation_node)
    builder.add_node("escalation_node", escalation_node)
    builder.add_node("report_node", report_node)

    builder.add_edge(START, "supervisor_node")
    builder.add_conditional_edges(
        "supervisor_node",
        _route_from_supervisor,
        {
            "triage_node": "triage_node",
            "triage_monitor_only": "triage_node",
            "escalation_node": "escalation_node",
        },
    )
    builder.add_conditional_edges(
        "triage_node",
        _route_from_triage,
        {
            "data_query_node": "data_query_node",
            "escalation_node": "escalation_node",
        },
    )
    builder.add_edge("data_query_node", "analysis_node")
    builder.add_edge("analysis_node", "recommendation_node")
    builder.add_edge("recommendation_node", "escalation_node")
    builder.add_edge("escalation_node", "report_node")
    builder.add_edge("report_node", END)

    # Register the 7 LangChain tools on the graph
    tools = [
        query_iceberg_table,
        list_iceberg_tables,
        get_latest_model_version,
        get_run_details,
        publish_kafka_event,
        list_kafka_topics,
        read_recent_kafka_messages,
    ]
    builder.add_node("tools", __import__("langgraph.prebuilt", fromlist=["ToolNode"]).ToolNode(tools))

    compiled_graph = builder.compile(checkpointer=_checkpointer)
