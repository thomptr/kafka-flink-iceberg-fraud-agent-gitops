import pandas as pd
import streamlit as st

try:
    import altair as alt
    _ALTAIR_AVAILABLE = True
except ImportError:
    _ALTAIR_AVAILABLE = False


def render_transaction_timeline(
    transactions: list[dict],
    flagged_transaction_id: str | None = None,
) -> None:
    if not transactions:
        st.info("No transaction history available.")
        return
    if not _ALTAIR_AVAILABLE:
        st.warning("altair not installed — install with `pip install altair>=5.0`")
        return

    df = pd.DataFrame(transactions)
    if "ts" not in df.columns or "amount" not in df.columns:
        st.info("Transaction data missing required columns (ts, amount).")
        return

    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts", "amount"])
    df["amount"] = df["amount"].astype(float)
    df["merchant"] = df.get("merchant", pd.Series(["unknown"] * len(df))).fillna("unknown")

    base = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X("ts:T", title="Time"),
        y=alt.Y("amount:Q", title="Amount ($)"),
        color=alt.Color("merchant:N", title="Merchant"),
        tooltip=["ts:T", "amount:Q", "merchant:N"],
    )

    layers = [base]

    if flagged_transaction_id and "transaction_id" in df.columns:
        flagged = df[df["transaction_id"] == flagged_transaction_id]
        if not flagged.empty:
            highlight = alt.Chart(flagged).mark_rule(color="red", strokeWidth=2).encode(
                x="ts:T",
                tooltip=[alt.Tooltip("transaction_id:N", title="Flagged TX")],
            )
            layers.append(highlight)

    chart = alt.layer(*layers).properties(title="Transaction Amount Timeline", height=300)
    st.altair_chart(chart, use_container_width=True)


def render_location_map(transactions: list[dict]) -> None:
    valid = [
        r for r in transactions
        if r.get("lat") is not None and r.get("lon") is not None
    ]
    if not valid:
        st.info("No location data available.")
        return

    df = pd.DataFrame(valid)[["lat", "lon"]].copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna()

    if df.empty:
        st.info("No valid coordinates found.")
        return

    st.map(df, zoom=10)
