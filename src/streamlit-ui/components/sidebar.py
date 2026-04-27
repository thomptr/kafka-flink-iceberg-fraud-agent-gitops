import streamlit as st

from api_client import FraudAgentClient, SessionConflictError
from components.evidence import render_evidence_table


_SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}

_OUTCOME_LABELS = {
    "confirmed_fraud": "Confirmed Fraud",
    "false_positive": "False Positive",
    "escalate": "Escalate",
}


def render_sidebar(client: FraudAgentClient) -> tuple[str | None, str | None]:
    """Render sidebar alert selector and conclusion form.

    Returns (selected_alert_id, session_id).
    """
    st.subheader("Select Alert")

    if st.button("🔄 Refresh alerts"):
        st.session_state.pop("alerts_cache", None)

    if "alerts_cache" not in st.session_state:
        with st.spinner("Loading alerts…"):
            try:
                st.session_state["alerts_cache"] = client.list_alerts(status="open,in_review")
            except Exception as exc:
                st.error(f"API error: {exc}")
                st.session_state["alerts_cache"] = []

    alerts = st.session_state["alerts_cache"]
    if not alerts:
        st.info("No open alerts found.")
        return None, None

    alert_options = {
        f"{_SEVERITY_EMOJI.get(a['severity'], '⚪')} {a['transaction_id'][:16]}… (${a['amount']:.2f})": a["id"]
        for a in alerts
    }
    selected_label = st.selectbox("Alert", list(alert_options.keys()))
    selected_alert_id = alert_options[selected_label] if selected_label else None

    selected_alert = next((a for a in alerts if a["id"] == selected_alert_id), None)
    if selected_alert:
        st.caption(f"Severity: **{selected_alert['severity'].upper()}** | "
                   f"Probability: **{selected_alert['fraud_probability']:.0%}**")

    if st.button("🔍 Start Investigation", type="primary", disabled=selected_alert_id is None):
        with st.spinner("Opening investigation session…"):
            try:
                resp = client.open_session(selected_alert_id)
                st.session_state["session_id"] = resp["session_id"]
                st.session_state["selected_alert_id"] = selected_alert_id
                st.session_state["session_status"] = resp["status"]
                st.session_state["turns"] = [resp["initial_turn"]]
                st.session_state["selected_alert"] = selected_alert
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to open session: {exc}")

    st.markdown("---")

    # Conclusion form (only shown when a session is active)
    session_id = st.session_state.get("session_id")
    session_status = st.session_state.get("session_status", "active")

    if session_id and session_status == "active":
        st.subheader("Record Conclusion")
        outcome = st.radio(
            "Outcome",
            options=list(_OUTCOME_LABELS.keys()),
            format_func=lambda k: _OUTCOME_LABELS[k],
        )
        notes = st.text_area("Notes (optional)")
        if st.button("✅ Submit Conclusion"):
            with st.spinner("Submitting…"):
                try:
                    client.conclude_session(session_id=session_id, outcome=outcome, notes=notes or None)
                    st.session_state["session_status"] = "concluded"
                    st.success(f"Concluded: **{_OUTCOME_LABELS[outcome]}**")
                    st.rerun()
                except SessionConflictError as e:
                    st.error(f"⚠️ {e.detail}")
                except Exception as exc:
                    st.error(f"Error: {exc}")

    elif session_id and session_status == "concluded":
        st.info("✅ This investigation is concluded.")

    # Raw history expander
    if selected_alert:
        with st.expander("📋 View raw transaction history"):
            rows = client.get_transaction_history(
                user_id=selected_alert.get("user_id", 0), limit=50
            )
            if rows:
                render_evidence_table(rows, title="Raw Transaction History")
            else:
                st.caption("Iceberg direct access not configured or no data available.")

    return selected_alert_id, session_id
