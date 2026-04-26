import os

import streamlit as st

st.set_page_config(
    page_title="Fraud Investigation",
    page_icon="🔍",
    layout="wide",
)

from api_client import FraudAgentClient, SessionConflictError
from components.chat import render_chat_history
from components.sidebar import render_sidebar
from components.visualizations import render_transaction_timeline, render_location_map

FRAUD_AGENT_BASE_URL = os.environ.get("FRAUD_AGENT_BASE_URL", "http://localhost:8000")
FRAUD_API_KEY = os.environ.get("FRAUD_API_KEY", "")
ANALYST_ID = os.environ.get("ANALYST_ID", "analyst")

# --- Session state init ---
for key, default in [
    ("session_id", None),
    ("selected_alert_id", None),
    ("selected_alert", None),
    ("turns", []),
    ("session_status", "active"),
    ("auto_open_session", False),
    ("analyst_id", ANALYST_ID),
]:
    if key not in st.session_state:
        st.session_state[key] = default

client = FraudAgentClient(
    base_url=FRAUD_AGENT_BASE_URL,
    api_key=FRAUD_API_KEY,
    analyst_id=st.session_state["analyst_id"],
)

# --- Deep-link: ?transaction_id=<uuid> ---
query_params = st.query_params
transaction_id_param = query_params.get("transaction_id")

if transaction_id_param and st.session_state["session_id"] is None:
    with st.spinner(f"Opening investigation for transaction {transaction_id_param}…"):
        try:
            resp = client.run_investigation(transaction_id_param)
            st.session_state["session_id"] = resp["session_id"]
            st.session_state["selected_alert_id"] = resp["alert_id"]
            st.session_state["session_status"] = resp["status"]
            st.session_state["turns"] = [resp["initial_turn"]]
            st.session_state["auto_open_session"] = True
        except Exception as exc:
            if "404" in str(exc) or "No alert" in str(exc):
                st.warning(f"No alert found for transaction_id {transaction_id_param}.")
            else:
                st.error(f"Failed to auto-open investigation: {exc}")

# --- Sidebar ---
with st.sidebar:
    render_sidebar(client)

# --- Main area ---
st.title("🔍 Fraud Investigation Agent")

session_id = st.session_state.get("session_id")
session_status = st.session_state.get("session_status", "active")

if session_id is None:
    st.info("Select a fraud alert from the sidebar to begin an investigation.")
else:
    # Status banner for concluded sessions
    if session_status == "concluded":
        st.info("✅ This investigation has been concluded. The transcript is shown in read-only mode below.")

    # Fetch latest turns if not already loaded
    if not st.session_state.get("turns"):
        try:
            st.session_state["turns"] = client.get_turns(session_id)
        except Exception as exc:
            st.error(f"Failed to load turns: {exc}")

    render_chat_history(st.session_state.get("turns", []))

    # Chat input (disabled when session concluded/abandoned)
    if session_status == "active":
        question = st.chat_input("Ask a question about this transaction…")
        if question:
            with st.spinner("Thinking…"):
                try:
                    turn = client.create_turn(session_id=session_id, question=question)
                    st.session_state["turns"].append(turn)
                    st.rerun()
                except SessionConflictError:
                    st.session_state["session_status"] = "concluded"
                    st.warning("Session was already concluded by another analyst.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"API error: {exc}")
    else:
        st.chat_input("Investigation concluded — no further questions accepted.", disabled=True)

    # Visualizations expander (US3)
    alert = st.session_state.get("selected_alert")
    if alert:
        with st.expander("📈 Transaction Timeline & Locations", expanded=False):
            rows = client.get_transaction_history(user_id=alert.get("user_id", 0), limit=100)
            col1, col2 = st.columns(2)
            with col1:
                render_transaction_timeline(
                    rows, flagged_transaction_id=alert.get("transaction_id")
                )
            with col2:
                render_location_map(rows)
