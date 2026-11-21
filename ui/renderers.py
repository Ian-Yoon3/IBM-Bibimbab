"""
ui/renderers.py — Response presentation helpers.

Stage A: renders the agent answer as chat messages using st.chat_message
and st.markdown. Richer structured cards (tables, KPI cards, approval
controls) belong to Stage B and Stage C.

The renderers never compute, modify, or reinterpret any value from the
result dict. Numbers are displayed exactly as received.
"""
from __future__ import annotations

import streamlit as st


# ---------------------------------------------------------------------------
# Single result renderer
# ---------------------------------------------------------------------------

def render_result(result: dict, label: str = "assistant") -> None:
    """Render one agent result inside an st.chat_message block.

    Stage A behaviour:
    - If the result contains an ``error`` key, show a warning banner and the
      safe answer text. No KPI cards or approval controls are shown.
    - Otherwise show the answer markdown.
    - In both cases the full answer text is shown — the structured view is
      reserved for Stage B renderers.
    """
    if result is None:
        return

    is_error = "error" in result
    answer = result.get("answer", "")

    with st.chat_message(label):
        if is_error:
            st.warning(
                "⚠ The AI service could not be reached. "
                "The response below is a safe fallback message.",
                icon="⚠️",
            )
            st.markdown(answer)
            # Offer retry in the caller; here we only render the content.
        else:
            st.markdown(answer)


def render_error_retry_banner(on_retry) -> None:
    """Show an inline banner with a Try again button for a failed request.

    *on_retry* is a zero-argument callable that will be invoked when the
    user clicks the button (e.g. ``st.session_state.request_pending = True``).
    """
    col1, col2 = st.columns([4, 1])
    with col1:
        st.error(
            "Connection error — the AI service did not respond. "
            "In Fixtures mode, retrying an error example will reproduce "
            "the same error response.",
            icon="🚫",
        )
    with col2:
        st.button("Try again", on_click=on_retry, type="secondary")


def render_unmatched_message() -> None:
    """Show the limitation message for unmatched free-text input."""
    st.info(
        "This demo uses saved examples. "
        "Choose an example, or use Live agent for a new analysis.",
        icon="ℹ️",
    )


def render_live_unavailable() -> None:
    """Explain that Live agent is not available at this stage."""
    st.warning(
        "**Live agent is not available yet.**  \n"
        "Live mode requires a configured `WX_API_KEY`. "
        "It will be enabled in Stage D once the API connection has been "
        "validated.  \n\n"
        "Switch to **Fixtures** mode to explore saved examples without an API key.",
        icon="🔒",
    )
