import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.base import AsyncSessionLocal
from app.db.models import InvestigationConclusion, InvestigationSession, SessionTurn

log = structlog.get_logger(__name__)


class SessionNotFoundError(Exception):
    pass


class SessionInactiveError(Exception):
    """Session is concluded or abandoned — no new turns accepted."""
    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Session is {status}")


class ConflictError(Exception):
    """Another analyst has already concluded this alert."""
    def __init__(self, existing: InvestigationConclusion):
        self.existing = existing
        super().__init__(
            f"Alert already concluded as '{existing.outcome}' "
            f"by {existing.analyst_id} at {existing.created_at.isoformat()}"
        )


async def create_session(alert_id: str, analyst_id: str) -> InvestigationSession:
    async with AsyncSessionLocal() as session:
        obj = InvestigationSession(
            id=uuid.uuid4(),
            alert_id=alert_id,
            analyst_id=analyst_id,
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        log.info("session_created", session_id=str(obj.id), alert_id=alert_id, analyst_id=analyst_id)
        return obj


async def get_session(session_id: str) -> InvestigationSession:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(InvestigationSession).where(InvestigationSession.id == session_id)
        )
        obj = result.scalars().first()
        if not obj:
            raise SessionNotFoundError(session_id)
        return obj


async def create_turn(
    session_id: str,
    analyst_input: str,
    agent_response: str,
    tool_calls: list[str] | None = None,
) -> SessionTurn:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(InvestigationSession).where(InvestigationSession.id == session_id)
        )
        inv_session = result.scalars().first()
        if not inv_session:
            raise SessionNotFoundError(session_id)

        count_result = await db.execute(
            select(__import__("sqlalchemy").func.count(SessionTurn.id)).where(
                SessionTurn.session_id == session_id
            )
        )
        turn_number = (count_result.scalar() or 0) + 1

        turn = SessionTurn(
            id=uuid.uuid4(),
            session_id=session_id,
            turn_number=turn_number,
            analyst_input=analyst_input,
            agent_response=agent_response,
            tool_calls=tool_calls,
            created_at=datetime.now(timezone.utc),
        )
        db.add(turn)

        inv_session.last_active_at = datetime.now(timezone.utc)
        inv_session.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(turn)
        return turn


async def list_turns(session_id: str) -> list[SessionTurn]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SessionTurn)
            .where(SessionTurn.session_id == session_id)
            .order_by(SessionTurn.turn_number)
        )
        return list(result.scalars().all())


async def conclude_session(
    session_id: str,
    outcome: str,
    notes: str | None,
    analyst_id: str,
) -> InvestigationConclusion:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(InvestigationSession).where(InvestigationSession.id == session_id)
        )
        inv_session = result.scalars().first()
        if not inv_session:
            raise SessionNotFoundError(session_id)

        conclusion = InvestigationConclusion(
            id=uuid.uuid4(),
            session_id=session_id,
            alert_id=inv_session.alert_id,
            outcome=outcome,
            notes=notes,
            analyst_id=analyst_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(conclusion)

        inv_session.status = "concluded"
        inv_session.updated_at = datetime.now(timezone.utc)

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing_result = await db.execute(
                select(InvestigationConclusion).where(
                    InvestigationConclusion.alert_id == inv_session.alert_id
                )
            )
            existing = existing_result.scalars().first()
            raise ConflictError(existing)

        await db.refresh(conclusion)
        log.info(
            "session_concluded",
            session_id=session_id,
            outcome=outcome,
            analyst_id=analyst_id,
        )
        return conclusion


async def get_conclusion(session_id: str) -> InvestigationConclusion | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(InvestigationConclusion).where(
                InvestigationConclusion.session_id == session_id
            )
        )
        return result.scalars().first()
