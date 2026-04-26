import json

import streamlit as st

from components.evidence import render_evidence_table


def render_chat_history(turns: list[dict]) -> None:
    for i, turn in enumerate(turns):
        label = "Initial Explanation" if i == 0 else f"Turn {turn['turn_number']}"
        with st.chat_message("user"):
            if i == 0:
                st.caption("🔍 Initial Explanation Request")
            st.markdown(turn["analyst_input"])

        with st.chat_message("assistant"):
            if i == 0:
                st.markdown(f"**{label}**")
            response_text = turn["agent_response"]
            _render_response(response_text)

            if turn.get("tool_calls"):
                st.caption(f"🔧 Tools used: {', '.join(turn['tool_calls'])}")


def _render_response(text: str) -> None:
    """Render assistant response, extracting fenced JSON blocks as tables."""
    import re
    parts = re.split(r"```json\n?(.*?)\n?```", text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                if part.strip().startswith("I'm sorry") or part.strip().lower().startswith("i cannot"):
                    st.info(part.strip())
                else:
                    st.markdown(part.strip())
        else:
            try:
                data = json.loads(part.strip())
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    render_evidence_table(data, title="Evidence Data")
                else:
                    st.json(data)
            except json.JSONDecodeError:
                st.code(part.strip(), language="json")
