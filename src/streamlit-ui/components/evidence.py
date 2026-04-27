import pandas as pd
import streamlit as st


def render_evidence_table(data: list[dict], title: str = "Evidence") -> None:
    if not data:
        st.info(f"No {title.lower()} available.")
        return
    st.caption(title)
    df = pd.DataFrame(data)
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].round(4)
    st.dataframe(df, use_container_width=True)
