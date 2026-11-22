"""
ui/state.py — Session-state initialisation and reset helpers.

Each concern is stored in its own key so that unrelated operations
(navigation, approval, log viewing) never accidentally trigger a new
analysis.

Keys
----
mode                "fixtures" | "live"
current_page        "overview" | "find_plan" | "compare" | "impact" | "log"
display_messages    list[dict] — rendered chat history (question, result, fixture_id, mode)
agent_history       list | None — history object returned by run_agent (live only)
active_result       dict | None — the most recent run_agent/fixture result shown
active_proposal     dict | None — proposal from active_result (None if none)
submitted_request   dict | None — snapshot: {budget, objective, fixture_id, question, mode}
request_pending     bool — True while a live call is in flight
last_failed_request dict | None — snapshot of the last failed request (for retry)
"""
from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------
# Scalar and None defaults are safe to share across sessions.
# Mutable defaults (lists, dicts) are produced fresh on each init call so
# that multiple sessions in the same process never share the same object.
_SCALAR_DEFAULTS: dict = {
    "mode": "fixtures",
    "current_page": "overview",
    "agent_history": None,
    "active_result": None,
    "active_proposal": None,
    "submitted_request": None,
    "request_pending": False,
    "last_failed_request": None,
}


def init_state() -> None:
    """Initialise every session-state key that does not yet exist.

    Safe to call on every Streamlit rerun — existing keys are untouched.
    Mutable defaults (lists) are created fresh for each session so that
    multiple concurrent sessions never share the same object.
    """
    for key, default in _SCALAR_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default
    # display_messages must be a fresh list for each session.
    if "display_messages" not in st.session_state:
        st.session_state["display_messages"] = []


def reset_conversation() -> None:
    """Clear conversation state without deleting the decision log.

    Resets: display_messages, agent_history, active_result, active_proposal,
    submitted_request, request_pending, last_failed_request, and any
    last_handled_selector_* tracking keys (Regression B).
    Does NOT reset: mode, current_page, or anything outside the conversation.
    """
    st.session_state.display_messages = []
    st.session_state.agent_history = None
    st.session_state.active_result = None
    st.session_state.active_proposal = None
    st.session_state.submitted_request = None
    st.session_state.request_pending = False
    st.session_state.last_failed_request = None
    # Clear selection-tracking keys (Regression B fix) so that returning to
    # Fixtures after a "New conversation" does not replay the old selection.
    _prefix = "last_handled_selector_"
    stale = [k for k in st.session_state if k.startswith(_prefix)]
    for k in stale:
        del st.session_state[k]


def switch_mode(new_mode: str) -> None:
    """Switch between 'fixtures' and 'live', clearing conversation state.

    History and active proposals from the previous mode are not carried over.
    """
    if st.session_state.mode != new_mode:
        st.session_state.mode = new_mode
        reset_conversation()


def navigate_to(page: str) -> None:
    """Change the current page without resetting the conversation."""
    st.session_state.current_page = page
