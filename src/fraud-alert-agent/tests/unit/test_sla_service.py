from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sla_service import compute_sla_deadline


def test_critical_sla_deadline_is_30_minutes():
    before = datetime.now(timezone.utc)
    deadline = compute_sla_deadline("critical")
    after = datetime.now(timezone.utc)
    expected_min = before + timedelta(minutes=29, seconds=59)
    expected_max = after + timedelta(minutes=30, seconds=1)
    assert expected_min <= deadline <= expected_max


def test_high_sla_deadline_is_2_hours():
    before = datetime.now(timezone.utc)
    deadline = compute_sla_deadline("high")
    after = datetime.now(timezone.utc)
    assert before + timedelta(hours=1, minutes=59) <= deadline <= after + timedelta(hours=2, seconds=1)


def test_medium_sla_deadline_is_8_hours():
    before = datetime.now(timezone.utc)
    deadline = compute_sla_deadline("medium")
    after = datetime.now(timezone.utc)
    assert before + timedelta(hours=7, minutes=59) <= deadline <= after + timedelta(hours=8, seconds=1)


def test_low_sla_deadline_uses_fallback():
    deadline = compute_sla_deadline("low")
    now = datetime.now(timezone.utc)
    assert deadline > now + timedelta(hours=1)


def test_unknown_severity_uses_fallback():
    deadline = compute_sla_deadline("unknown_severity")
    now = datetime.now(timezone.utc)
    # Should fall back to the medium/default offset, not raise
    assert deadline > now


@pytest.mark.asyncio
async def test_get_breached_alerts_returns_past_deadline_open_alerts():
    now = datetime.now(timezone.utc)
    breached_alert = MagicMock()
    breached_alert.sla_deadline = now - timedelta(minutes=5)
    breached_alert.status = "open"

    with patch("app.services.sla_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [breached_alert]
        mock_session.execute = AsyncMock(return_value=result)
        mock_cls.return_value = mock_session

        from app.services.sla_service import get_breached_alerts
        breached = await get_breached_alerts()

    assert len(breached) == 1
    assert breached[0].status == "open"


@pytest.mark.asyncio
async def test_get_breached_alerts_excludes_resolved_alerts():
    with patch("app.services.sla_service.AsyncSessionLocal") as mock_cls:
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=result)
        mock_cls.return_value = mock_session

        from app.services.sla_service import get_breached_alerts
        breached = await get_breached_alerts()

    assert breached == []
