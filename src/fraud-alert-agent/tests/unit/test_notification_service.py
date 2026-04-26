import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def sample_alert_dict():
    return {
        "alert_id": "abc-123",
        "severity": "critical",
        "amount": 750.00,
        "fraud_probability": 0.93,
        "explanation": "High velocity transaction with new merchant in foreign country.",
    }


@pytest.mark.asyncio
async def test_send_slack_notification_posts_to_webhook(sample_alert_dict):
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("app.services.notification_service.settings") as mock_settings:
        mock_settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from app.services.notification_service import send_slack_notification
            await send_slack_notification(sample_alert_dict, "block")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
            assert "block" in str(payload).lower() or "fraud" in str(payload).lower()


@pytest.mark.asyncio
async def test_send_slack_notification_noop_when_no_webhook(sample_alert_dict):
    with patch("app.services.notification_service.settings") as mock_settings:
        mock_settings.SLACK_WEBHOOK_URL = ""
        with patch("httpx.AsyncClient") as mock_client_cls:
            from app.services.notification_service import send_slack_notification
            await send_slack_notification(sample_alert_dict, "block")
            mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_slack_notification_logs_warning_on_http_error(sample_alert_dict):
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("app.services.notification_service.settings") as mock_settings:
        mock_settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            from app.services.notification_service import send_slack_notification
            # Should not raise even on 5xx
            await send_slack_notification(sample_alert_dict, "block")


@pytest.mark.asyncio
async def test_send_slack_notification_logs_warning_on_connection_error(sample_alert_dict):
    with patch("app.services.notification_service.settings") as mock_settings:
        mock_settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/test"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client_cls.return_value = mock_client

            from app.services.notification_service import send_slack_notification
            # Should not raise on connection error
            await send_slack_notification(sample_alert_dict, "block")
