"""
app.py — Supply Chain Recovery Decision Agent
Entry point for the Streamlit application.

Stage A: Overview screen, fixture-based chat, example selector,
         New conversation reset, error/retry behaviour.
         Live agent is intentionally disabled until Stage D.

Permitted agent imports (UI contract):
    from agent.loop import run_agent
    from agent.decisions import record_decision, list_decisions
Live calls are gated behind a WX_API_KEY check; they are never made in
Stage A.

On Streamlit Community Cloud, copy Streamlit secrets into os.environ so
that agent/llm.py can find them. Done inside try/except so a local run
without a secrets file does not crash.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Secrets → environment (Community Cloud compatibility, Stage D prep)
# ---------------------------------------------------------------------------
try:
    import streamlit as st
    for _key in ("WX_API_KEY", "WX_PROJECT_ID", "WX_URL", "WX_MODEL_ID"):
        if _key in st.secrets and _key not in os.environ:
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass  # No secrets file or not on Community Cloud — that is fine.

import streamlit as st

from ui.fixtures import (
    UNMATCHED_MESSAGE,
    build_fixture_catalog,
    get_fixture_options,
    get_result_copy,
    is_error_fixture,
    load_fixtures,
)
from ui.renderers import (
    render_error_retry_banner,
    render_live_unavailable,
    render_result,
    render_unmatched_message,
)
from ui.state import init_state, navigate_to, reset_conversation, switch_mode

# ---------------------------------------------------------------------------
# Streamlit page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Supply Chain Recovery Decision Agent",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session-state bootstrap
# ---------------------------------------------------------------------------
init_state()

# ---------------------------------------------------------------------------
# Load fixtures once per session (cached so disk is read only on first load)
# ---------------------------------------------------------------------------
@st.cache_resource
def _load() -> tuple[list[dict], dict[str, dict], list[tuple[str, str]]]:
    fixtures = load_fixtures()
    catalog = build_fixture_catalog(fixtures)
    options = get_fixture_options(fixtures)
    return fixtures, catalog, options


_fixtures, _catalog, _fixture_options = _load()

# ---------------------------------------------------------------------------
# Situation text for the Overview screen (from first recommendation fixture)
# ---------------------------------------------------------------------------
def _overview_situation() -> str:
    """Return the situation text from the first recommendation fixture."""
    for entry in _fixtures:
        view = entry["result"].get("view")
        if view and view.get("type") == "recommendation":
            return view.get("situation", "")
    return ""


# ===========================================================================
# Sidebar — navigation and controls
# ===========================================================================
def _sidebar() -> None:
    with st.sidebar:
        st.markdown("## Navigation")

        # --- Page links ---
        pages = [
            ("overview",   "🏠 Overview"),
            ("find_plan",  "🔍 Find a recovery plan"),
            ("compare",    "⚖️ Compare options"),
            ("impact",     "📊 Understand the impact"),
        ]
        for page_id, label in pages:
            active = st.session_state.current_page == page_id
            button_type = "primary" if active else "secondary"
            if st.button(label, key=f"nav_{page_id}", use_container_width=True,
                         type=button_type):
                navigate_to(page_id)
                st.rerun()

        # Decision log — marked as upcoming
        st.button(
            "📋 Decision log  *(upcoming)*",
            key="nav_log",
            use_container_width=True,
            disabled=True,
        )

        st.divider()

        # --- New conversation ---
        if st.button("🔄 New conversation", key="new_conv", use_container_width=True):
            reset_conversation()
            navigate_to("overview")
            st.rerun()

        st.divider()

        # --- Mode selector ---
        st.markdown("**Mode**")
        mode_choice = st.radio(
            "Mode",
            options=["Fixtures", "Live agent"],
            index=0 if st.session_state.mode == "fixtures" else 1,
            key="mode_radio",
            label_visibility="collapsed",
        )
        new_mode = "fixtures" if mode_choice == "Fixtures" else "live"
        if new_mode != st.session_state.mode:
            switch_mode(new_mode)
            st.rerun()

        if st.session_state.mode == "fixtures":
            st.caption("🗂 Demo mode — saved examples")
        else:
            st.caption("🤖 Live agent (requires API key)")


# ===========================================================================
# Overview screen
# ===========================================================================
def _page_overview() -> None:
    st.title("Supply Chain Recovery Decision Agent")
    st.markdown(
        "Compare recovery options for a supplier delay and record your decision."
    )

    # Prominent demo / mode indicator
    if st.session_state.mode == "fixtures":
        st.info(
            "**Demo mode — saved examples**  \n"
            "You are viewing real responses captured from a previous agent run. "
            "No AI service calls are made in this mode.",
            icon="🗂",
        )
    else:
        st.warning(
            "**Live agent mode**  \n"
            "Submitting a request will call the watsonx.ai service and use credits.",
            icon="🤖",
        )

    # D01 disruption context
    situation = _overview_situation()
    if situation:
        st.markdown("### Example case — Disruption D01")
        st.markdown(
            f"> {situation}  \n"
            "> *(Dates are from the saved example, not today's date.)*"
        )

    st.divider()

    # Three starting actions
    st.markdown("### Where would you like to start?")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**🔍 Find a recovery plan**")
        st.markdown(
            "Get a recommendation for the best recovery option given your budget."
        )
        if st.button("Find a recovery plan", key="cta_find", use_container_width=True):
            navigate_to("find_plan")
            st.rerun()

    with col2:
        st.markdown("**⚖️ Compare options**")
        st.markdown(
            "See all recovery options side by side, without committing to one."
        )
        if st.button("Compare options", key="cta_compare", use_container_width=True):
            navigate_to("compare")
            st.rerun()

    with col3:
        st.markdown("**📊 Understand the impact**")
        st.markdown(
            "Learn which customers and orders are affected by the disruption."
        )
        if st.button("Understand the impact", key="cta_impact", use_container_width=True):
            navigate_to("impact")
            st.rerun()

    # Help glossary
    with st.expander("ℹ️ Key terms explained"):
        st.markdown(
            "**Maximum budget** — the maximum *additional* spending allowed for a "
            "recovery action. Existing costs (e.g. the original purchase order) are "
            "not counted against this budget.\n\n"
            "**Extra cost** — the additional cost of a specific recovery option. "
            "An option may cost less than the budget; the budget is a ceiling, not "
            "a spending target.\n\n"
            "**Total days late** — the *sum* of individual order delays across all "
            "late orders. An order that is 3 days late and another that is 5 days "
            "late give a total of 8 days late — not that every order is 8 days late.\n\n"
            "**Approval** — recording your decision in the log. It does not place a "
            "purchase order or issue a warehouse transfer instruction."
        )


# ===========================================================================
# Chat / example-selector screen (shared by Find plan, Compare, Impact pages)
# ===========================================================================

def _fixture_selector(page_hint: str) -> None:
    """Render the example selector for a given page context."""

    # Filter labels for context (optional nicety — show all entries)
    st.markdown("#### Choose a saved example")
    st.caption(
        "Select an entry from the list below. "
        "The successful response and the connection-error response share the same "
        "question text; they are listed separately and are independently selectable."
    )

    # Build display list: (fixture_id, label)
    selector_options = ["— select an example —"] + [fid for fid, _ in _fixture_options]
    selector_labels = ["— select an example —"] + [lbl for _, lbl in _fixture_options]

    # Map fixture_id → label for display
    id_to_label = {fid: lbl for fid, lbl in _fixture_options}

    chosen_index = st.selectbox(
        "Saved examples",
        options=range(len(selector_options)),
        format_func=lambda i: selector_labels[i],
        index=0,
        key=f"fixture_selector_{page_hint}",
        label_visibility="collapsed",
    )

    if chosen_index == 0:
        # Nothing selected yet — show hint
        st.caption("Select an example above to load its response.")
        return

    chosen_id = selector_options[chosen_index]
    _handle_fixture_selection(chosen_id)


def _handle_fixture_selection(fixture_id: str) -> None:
    """Load and display the selected fixture result."""
    result = get_result_copy(_catalog, fixture_id)
    if result is None:
        st.error("Could not load the selected example. The fixture catalog may have changed.")
        return

    # Store as active result (without overloading with proposal from old result)
    st.session_state.active_result = result
    st.session_state.active_proposal = result.get("proposal")
    st.session_state.submitted_request = {
        "fixture_id": fixture_id,
        "mode": "fixtures",
    }

    # Show the question
    entry = _catalog[fixture_id]
    question = entry["question"]

    with st.chat_message("user"):
        st.markdown(f"**Example question:** {question}")

    # Render the result
    render_result(result)

    # If it's an error fixture, show the retry banner
    if is_error_fixture(result):
        def _retry():
            # In Fixtures mode, retry simply reloads the same (error) fixture
            pass  # state already set; rerun will re-render the same result

        render_error_retry_banner(on_retry=_retry)


def _free_text_input(page_hint: str) -> None:
    """Accept free-text input but show limitation message if no match."""
    with st.form(key=f"free_text_form_{page_hint}", clear_on_submit=True):
        user_input = st.text_input(
            "Or type a question (Fixtures mode only matches saved examples)",
            placeholder="e.g. Our budget is 500 dollars. What should we do?",
            key=f"free_text_{page_hint}",
        )
        submitted = st.form_submit_button("Submit")

    if submitted and user_input.strip():
        # Check whether any fixture matches the input exactly
        matched_id = None
        for fid, entry in _catalog.items():
            if entry["question"].strip() == user_input.strip():
                matched_id = fid
                break  # use first match; duplicates are handled by fixture_id
        if matched_id:
            _handle_fixture_selection(matched_id)
        else:
            render_unmatched_message()


# ===========================================================================
# Page: Find a recovery plan
# ===========================================================================
def _page_find_plan() -> None:
    st.header("🔍 Find a recovery plan")
    st.markdown(
        "Select a saved example to see how the agent recommends a recovery option "
        "for a given budget. Budget forms and live submissions will be available in "
        "Stage B."
    )
    _fixture_selector("find_plan")
    st.divider()
    _free_text_input("find_plan")


# ===========================================================================
# Page: Compare options
# ===========================================================================
def _page_compare() -> None:
    st.header("⚖️ Compare options")
    st.markdown(
        "Select a saved comparison example to see recovery options side by side."
    )
    _fixture_selector("compare")
    st.divider()
    _free_text_input("compare")


# ===========================================================================
# Page: Understand the impact
# ===========================================================================
def _page_impact() -> None:
    st.header("📊 Understand the impact")
    st.markdown(
        "Select a saved example to understand which orders and customers are "
        "affected by the disruption."
    )
    _fixture_selector("impact")
    st.divider()
    _free_text_input("impact")


# ===========================================================================
# Main router
# ===========================================================================
def main() -> None:
    _sidebar()

    page = st.session_state.current_page

    if page == "overview":
        _page_overview()
    elif page == "find_plan":
        _page_find_plan()
    elif page == "compare":
        _page_compare()
    elif page == "impact":
        _page_impact()
    else:
        # Fallback for future pages
        st.info(f"Page '{page}' is not yet implemented.")


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module on every rerun; call main() at module level.
    main()
