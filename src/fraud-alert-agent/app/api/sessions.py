import time
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.investigation_session_graph import get_session_graph
from app.api.deps import verify_api_key
from app.services import session_service
from app.services.alert_service import get_alert, get_alert_by_transaction_id
from app.services.session_service import ConflictError, SessionInactiveError, SessionNotFoundError
from app.metrics import (
    investigation_session_opens_total,
    investigation_session_turn_duration_seconds,
    investigation_conclusions_total,
)

log = structlog.get_logger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


async def _require_analyst_id(x_analyst_id: Annotated[str | None, Header()] = None) -> str:
    if not x_analyst_id:
        raise HTTPException(status_code=400, detail="X-Analyst-Id header is required")
    return x_analyst_id


def _serialize_turn(turn) -> dict:
    return {
        "turn_number": turn.turn_number,
        "analyst_input": turn.analyst_input,
        "agent_response": turn.agent_response,
        "tool_calls": turn.tool_calls,
        "created_at": turn.created_at.isoformat(),
    }


def _serialize_session(s) -> dict:
    return {
        "session_id": str(s.id),
        "alert_id": str(s.alert_id),
        "analyst_id": s.analyst_id,
        "status": s.status,
        "created_at": s.created_at.isoformat(),
        "last_active_at": s.last_active_at.isoformat(),
    }


def _serialize_conclusion(c) -> dict:
    return {
        "conclusion_id": str(c.id),
        "session_id": str(c.session_id),
        "alert_id": str(c.alert_id),
        "outcome": c.outcome,
        "notes": c.notes,
        "analyst_id": c.analyst_id,
        "created_at": c.created_at.isoformat(),
    }


async def _run_graph_turn(session_id: str, alert_id: str, analyst_id: str, question: str) -> tuple[str, list[str]]:
    graph = get_session_graph()
    config = {"configurable": {"thread_id": session_id}}
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config=config,
    )
    messages = result.get("messages", [])
    agent_response = ""
    tool_calls_used: list[str] = []
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
            agent_response = msg.content
            break
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls_used.extend(tc["name"] for tc in msg.tool_calls if "name" in tc)
    return agent_response or "(no response)", list(dict.fromkeys(reversed(tool_calls_used)))


# --- Open session ---

@router.post("/alerts/{alert_id}/investigation-sessions", status_code=201)
async def open_investigation_session(
    alert_id: str,
    analyst_id: str = Depends(_require_analyst_id),
) -> dict:
    alert = await get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    inv_session = await session_service.create_session(
        alert_id=alert_id, analyst_id=analyst_id
    )
    investigation_session_opens_total.inc()

    initial_prompt = (
        f"Explain why transaction {alert.transaction_id} was flagged as potentially fraudulent. "
        f"Include the top risk signals and their supporting data values. "
        f"The fraud probability score is {float(alert.fraud_probability):.2%}."
    )

    t0 = time.perf_counter()
    agent_response, tool_calls = await _run_graph_turn(
        session_id=str(inv_session.id),
        alert_id=alert_id,
        analyst_id=analyst_id,
        question=initial_prompt,
    )
    duration = time.perf_counter() - t0
    investigation_session_turn_duration_seconds.observe(duration)

    turn = await session_service.create_turn(
        session_id=str(inv_session.id),
        analyst_input=initial_prompt,
        agent_response=agent_response,
        tool_calls=tool_calls or None,
    )

    log.info(
        "session_opened",
        session_id=str(inv_session.id),
        alert_id=alert_id,
        analyst_id=analyst_id,
        duration_ms=int(duration * 1000),
    )

    return {
        "session_id": str(inv_session.id),
        "alert_id": alert_id,
        "status": inv_session.status,
        "initial_turn": _serialize_turn(turn),
    }


# --- Get session metadata ---

@router.get("/investigation-sessions/{session_id}")
async def get_investigation_session(session_id: str) -> dict:
    try:
        s = await session_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize_session(s)


# --- Session turns ---

class TurnRequest(BaseModel):
    question: str


@router.post("/investigation-sessions/{session_id}/turns")
async def create_session_turn(session_id: str, body: TurnRequest) -> dict:
    try:
        inv_session = await session_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    if inv_session.status != "active":
        raise HTTPException(
            status_code=409,
            detail=f"Session is {inv_session.status} — no new turns accepted",
        )

    t0 = time.perf_counter()
    agent_response, tool_calls = await _run_graph_turn(
        session_id=session_id,
        alert_id=str(inv_session.alert_id),
        analyst_id=inv_session.analyst_id,
        question=body.question,
    )
    duration = time.perf_counter() - t0
    investigation_session_turn_duration_seconds.observe(duration)

    turn = await session_service.create_turn(
        session_id=session_id,
        analyst_input=body.question,
        agent_response=agent_response,
        tool_calls=tool_calls or None,
    )

    log.info(
        "session_turn_created",
        session_id=session_id,
        turn_number=turn.turn_number,
        duration_ms=int(duration * 1000),
        tool_calls=tool_calls,
    )
    return _serialize_turn(turn)


@router.get("/investigation-sessions/{session_id}/turns")
async def list_session_turns(session_id: str) -> list[dict]:
    try:
        await session_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    turns = await session_service.list_turns(session_id)
    return [_serialize_turn(t) for t in turns]


# --- Conclude session ---

class ConcludeRequest(BaseModel):
    outcome: str
    notes: str | None = None


@router.post("/investigation-sessions/{session_id}/conclude", status_code=201)
async def conclude_session(
    session_id: str,
    body: ConcludeRequest,
    analyst_id: str = Depends(_require_analyst_id),
) -> dict:
    try:
        await session_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        conclusion = await session_service.conclude_session(
            session_id=session_id,
            outcome=body.outcome,
            notes=body.notes,
            analyst_id=analyst_id,
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    from app.services.alert_service import update_alert_status
    await update_alert_status(str(conclusion.alert_id), "resolved")

    investigation_conclusions_total.labels(outcome=body.outcome).inc()

    log.info(
        "session_concluded",
        session_id=session_id,
        outcome=body.outcome,
        analyst_id=analyst_id,
    )
    return _serialize_conclusion(conclusion)


@router.get("/investigation-sessions/{session_id}/conclude")
async def get_session_conclusion(session_id: str) -> dict:
    try:
        await session_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    conclusion = await session_service.get_conclusion(session_id)
    if not conclusion:
        raise HTTPException(status_code=404, detail="No conclusion recorded for this session")
    return _serialize_conclusion(conclusion)


# --- POST /api/v1/investigate (direct transaction_id entry point) ---

class InvestigateRequest(BaseModel):
    transaction_id: str
    analyst_id: str


@router.post("/investigate", status_code=201)
async def run_investigation(body: InvestigateRequest) -> dict:
    alert = await get_alert_by_transaction_id(body.transaction_id)
    if not alert:
        raise HTTPException(
            status_code=404,
            detail=f"No alert found for transaction_id {body.transaction_id}",
        )
    return await open_investigation_session(
        alert_id=str(alert.id),
        analyst_id=body.analyst_id,
    )
