from typing import TypedDict

from langgraph.graph.message import MessagesState


class InvestigationSessionState(MessagesState):
    session_id: str
    alert_id: str
    analyst_id: str
