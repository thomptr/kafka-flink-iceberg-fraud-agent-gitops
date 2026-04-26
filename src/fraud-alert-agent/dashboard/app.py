"""Fraud Alert Agent — Streamlit dashboard.

Live alert queue with severity/status filtering, investigation trace viewer,
and metrics summary. Communicates with the FastAPI service via REST.
"""
import os
from datetime import datetime, timedelta, timezone

import httpx
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("FRAUD_AGENT_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("FRAUD_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY}
REFRESH_INTERVAL_MS = 10_000  # 10 seconds

SEVERITY_COLORS = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
}
STATUS_ICONS = {
    "open": "🔓",
    "in_review": "👁️",
    "resolved": "✅",
    "escalated": "⚠️",
    "sla_breached": "🚨",
}

# ── Page setup ─────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Fraud Alert Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st_autorefresh(interval=REFRESH_INTERVAL_MS, key="auto_refresh")

# ── API helpers ────────────────────────────────────────────────────────────────


def _get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{BASE_URL}{path}", headers=HEADERS, params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        st.error(f"API error on {path}: {exc}")
        return None


def fetch_alerts(
    severity: list[str] | None = None,
    status: list[str] | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    params: dict = {"page": page, "page_size": page_size}
    if severity:
        params["severity"] = severity[0] if len(severity) == 1 else severity
    if status:
        params["status"] = status[0] if len(status) == 1 else status
    if from_time:
        params["from_time"] = from_time.isoformat()
    if to_time:
        params["to_time"] = to_time.isoformat()
    result = _get("/api/v1/alerts", params=params)
    return result or {"items": [], "total": 0, "page": 1, "page_size": page_size}


def fetch_investigation(alert_id: str) -> dict | None:
    return _get(f"/api/v1/alerts/{alert_id}/investigation")


def fetch_metrics(window_hours: int = 24) -> dict | None:
    return _get("/api/v1/metrics", params={"window_hours": window_hours})


# ── Metrics panel ──────────────────────────────────────────────────────────────


def render_metrics_panel() -> None:
    metrics = fetch_metrics(window_hours=24)
    if not metrics:
        st.warning("Metrics unavailable")
        return

    cols = st.columns(6)
    cols[0].metric("Total Alerts (24h)", metrics.get("alert_count", "—"))

    route_dist = metrics.get("route_distribution", {})
    cols[1].metric("🔴 Critical", route_dist.get("critical", 0))
    cols[2].metric("🟠 High", route_dist.get("high", 0))

    iceberg_rate = metrics.get("iceberg_write_success_rate", 0)
    cols[3].metric("Iceberg Write Rate", f"{iceberg_rate:.1%}")

    kafka_rate = metrics.get("kafka_delivery_rate", 0)
    cols[4].metric("Kafka Delivery Rate", f"{kafka_rate:.1%}")

    model_ver = metrics.get("mlflow_model_version_in_use") or "—"
    cols[5].metric("Model Version", model_ver)


# ── Sidebar filters ────────────────────────────────────────────────────────────


def render_sidebar() -> tuple[list[str], list[str], datetime | None, datetime | None, int]:
    with st.sidebar:
        st.title("🛡️ Fraud Alerts")
        st.markdown("---")

        severity_opts = ["critical", "high", "medium", "low"]
        selected_severity = st.multiselect("Severity", severity_opts, default=[])

        status_opts = ["open", "in_review", "resolved", "escalated", "sla_breached"]
        selected_status = st.multiselect("Status", status_opts, default=[])

        st.markdown("**Time Range**")
        use_time_filter = st.checkbox("Filter by time", value=False)
        from_time: datetime | None = None
        to_time: datetime | None = None
        if use_time_filter:
            days_back = st.slider("Days back", 1, 30, 7)
            from_time = datetime.now(timezone.utc) - timedelta(days=days_back)
            to_time = datetime.now(timezone.utc)

        page_size = st.selectbox("Rows per page", [20, 50, 100], index=1)

        st.markdown("---")
        if st.button("🔄 Refresh now"):
            st.rerun()

        st.caption(f"Auto-refresh every {REFRESH_INTERVAL_MS // 1000}s")

    return selected_severity, selected_status, from_time, to_time, page_size


# ── Alerts table ───────────────────────────────────────────────────────────────


def render_alerts_table(
    severity: list[str],
    status: list[str],
    from_time: datetime | None,
    to_time: datetime | None,
    page_size: int,
) -> str | None:
    data = fetch_alerts(
        severity=severity or None,
        status=status or None,
        from_time=from_time,
        to_time=to_time,
        page=1,
        page_size=page_size,
    )
    items = data.get("items", [])
    total = data.get("total", 0)

    st.subheader(f"Alerts — {total} total")

    if not items:
        st.info("No alerts match your filters.")
        return None

    rows = []
    for a in items:
        sev = a.get("severity", "")
        sta = a.get("status", "")
        rows.append({
            "": SEVERITY_COLORS.get(sev, "⚪"),
            "ID": a["id"][:8] + "…",
            "_full_id": a["id"],
            "Transaction": a.get("transaction_id", "")[:16],
            "Amount": f"${a.get('amount', 0):.2f}",
            "Prob": f"{a.get('fraud_probability', 0):.2%}",
            "Severity": sev,
            "Status": f"{STATUS_ICONS.get(sta, '')} {sta}",
            "Merchant": (a.get("merchant") or "")[:20],
            "Created": (a.get("created_at") or "")[:19].replace("T", " "),
            "SLA": (a.get("sla_deadline") or "")[:19].replace("T", " "),
        })

    selected_idx = st.session_state.get("selected_row_idx")

    # Build display DataFrame excluding _full_id
    display_cols = ["", "ID", "Transaction", "Amount", "Prob", "Severity", "Status", "Merchant", "Created", "SLA"]

    import pandas as pd
    df = pd.DataFrame(rows)[display_cols]

    # Show table — use st.dataframe with on_select when available (Streamlit ≥1.35)
    try:
        event = st.dataframe(
            df,
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            key="alerts_df",
        )
        sel = event.selection.rows if hasattr(event, "selection") else []
        if sel:
            st.session_state["selected_alert_id"] = rows[sel[0]]["_full_id"]
            st.session_state["selected_row_idx"] = sel[0]
    except TypeError:
        # Fallback for older Streamlit without on_select
        st.dataframe(df, use_container_width=True)
        alert_ids = [r["_full_id"] for r in rows]
        display_ids = [r["ID"] for r in rows]
        chosen = st.selectbox(
            "Select alert to inspect:",
            options=range(len(alert_ids)),
            format_func=lambda i: f"{display_ids[i]} ({rows[i]['Severity']} / {rows[i]['Status']})",
            key="alert_selector",
        )
        if chosen is not None:
            st.session_state["selected_alert_id"] = alert_ids[chosen]

    return st.session_state.get("selected_alert_id")


# ── Investigation trace panel ──────────────────────────────────────────────────


def render_investigation_panel(alert_id: str) -> None:
    st.markdown("---")
    st.subheader("🔍 Investigation Trace")

    inv = fetch_investigation(alert_id)
    if not inv:
        st.info("No investigation found for this alert.")
        return

    status = inv.get("status", "unknown")
    confidence = inv.get("confidence")
    started = (inv.get("started_at") or "")[:19].replace("T", " ")
    completed = (inv.get("completed_at") or "")[:19].replace("T", " ")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Investigation Status", status)
    c2.metric("Confidence", f"{confidence:.2%}" if confidence else "—")
    c3.metric("Started", started or "—")
    c4.metric("Completed", completed or "—")

    steps = inv.get("steps", [])
    if steps:
        st.markdown("**Node Execution Steps**")
        for step in steps:
            node = step.get("node_name", "")
            tool = step.get("tool_name", "")
            duration = step.get("duration_ms")
            label = f"Step {step.get('step_order', '?')}: `{node}`"
            if tool:
                label += f" → `{tool}`"
            if duration is not None:
                label += f" ({duration}ms)"

            with st.expander(label, expanded=False):
                input_data = step.get("input")
                output_data = {k: v for k, v in step.items()
                               if k not in ("step_order", "node_name", "tool_name",
                                            "duration_ms", "created_at", "input")}

                col_left, col_right = st.columns(2)
                with col_left:
                    st.markdown("**Input**")
                    if input_data:
                        st.json(input_data)
                    else:
                        st.caption("—")
                with col_right:
                    st.markdown("**Output**")
                    if output_data:
                        st.json({k: v for k, v in output_data.items() if v is not None})
                    else:
                        st.caption("—")
    else:
        st.info("No steps recorded yet.")

    # Agent reasoning — displayed in a chat-style block
    # The investigation endpoint exposes `reasoning` on the Investigation model
    # but the current serialiser doesn't include it. We fetch the alert detail for summary.
    alert_detail = _get(f"/api/v1/alerts/{alert_id}")
    summary = alert_detail.get("summary") if alert_detail else None
    if summary:
        st.markdown("**Agent Reasoning Summary**")
        with st.chat_message("assistant"):
            st.markdown(summary)


# ── Main layout ────────────────────────────────────────────────────────────────


def main() -> None:
    st.title("🛡️ Fraud Alert Agent Dashboard")

    # Metrics strip
    with st.container():
        render_metrics_panel()

    st.markdown("---")

    # Sidebar filters
    severity, status, from_time, to_time, page_size = render_sidebar()

    # Alerts table
    selected_id = render_alerts_table(severity, status, from_time, to_time, page_size)

    # Investigation panel (shown when an alert is selected)
    if selected_id:
        render_investigation_panel(selected_id)


if __name__ == "__main__":
    main()
