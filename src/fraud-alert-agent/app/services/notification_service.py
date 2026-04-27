import structlog
import httpx

from app.config import settings

log = structlog.get_logger(__name__)

_CHANNEL_MAP = {
    "block": "#fraud-urgent",
    "escalate": "#fraud-escalations",
    "notify": "#fraud-alerts",
}


async def send_slack_notification(alert: dict, final_action: str) -> None:
    if not settings.SLACK_WEBHOOK_URL:
        return

    channel = _CHANNEL_MAP.get(final_action, "#fraud-alerts")
    alert_id = alert.get("alert_id", "unknown")
    transaction_id = alert.get("transaction_id", "unknown")
    explanation = alert.get("explanation", "")

    text = (
        f"*Fraud Alert* [{final_action.upper()}] — {channel}\n"
        f"Alert: `{alert_id}` | Transaction: `{transaction_id}` | Severity: {alert.get('severity', 'unknown')}\n"
        f"Amount: ${alert.get('amount', 0):.2f} | "
        f"Probability: {alert.get('fraud_probability', 0):.2%}\n"
        f"_Explanation_: {explanation[:300]}"
    )
    if settings.INVESTIGATION_UI_BASE_URL:
        text += (
            f"\n🔍 *Investigate in UI*: "
            f"{settings.INVESTIGATION_UI_BASE_URL}/?transaction_id={transaction_id}"
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.SLACK_WEBHOOK_URL,
                json={"text": text, "channel": channel},
            )
            if response.status_code != 200:
                log.warning(
                    "slack_notification_failed",
                    alert_id=alert_id,
                    status_code=response.status_code,
                )
    except Exception as exc:
        log.warning("slack_notification_error", alert_id=alert_id, error=str(exc))
