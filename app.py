"""
app.py — Supply Chain Recovery Decision Agent
Entry point for the Streamlit application.

Stage A: Overview screen, fixture-based chat, example selector,
         New conversation reset, error/retry behaviour.
         Live agent is intentionally disabled until Stage D.

Permitted agent imports (UI contract):
    from agent.loop import run_agent
    from agent.decisions import record_decision, list_decisions
    from agent.overview import get_overview
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
    DEMO_CSS,
    inject_css,
    render_api_key_missing,
    render_error_retry_banner,
    render_find_plan_result,
    render_live_unavailable,
    render_result,
    render_unmatched_message,
    render_world_risk,
)
from ui.state import init_state, navigate_to, reset_conversation, switch_mode

# UI contract: permitted agent imports.
from agent.loop import run_agent
from agent.overview import get_overview

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
# Inject shared CSS once per session
# ---------------------------------------------------------------------------
inject_css()

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
        # Brand block
        st.markdown(
            '<div class="sidebar-brand">'
            '<span class="sidebar-brand-icon">🔗</span>'
            '<span class="sidebar-brand-text">Supply Chain<br>Recovery Agent</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        # --- Page links ---
        pages = [
            ("overview",   "🏠 Overview"),
            ("find_plan",  "🔍 Find a recovery plan"),
            ("compare",    "⚖️ Compare options"),
            ("impact",     "📊 Risk under uncertainty"),
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
            "📋 Saved examples",
            key="nav_log",
            use_container_width=True,
            disabled=True,
        )

        st.divider()

        # --- New conversation ---
        if st.button("🔄 New conversation", key="new_conv", use_container_width=True):
            reset_conversation()
            # Clear widget selections so a rerun cannot restore old state.
            for page_hint in ("find_plan", "compare", "impact"):
                selector_key = f"fixture_selector_{page_hint}"
                if selector_key in st.session_state:
                    del st.session_state[selector_key]
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
            # Clear widget selections so a rerun cannot restore old fixture data.
            for page_hint in ("find_plan", "compare", "impact"):
                selector_key = f"fixture_selector_{page_hint}"
                if selector_key in st.session_state:
                    del st.session_state[selector_key]
            st.rerun()

        if st.session_state.mode == "fixtures":
            st.caption("🗂 Demo mode — saved examples")
        else:
            st.caption("🔒 Live agent — not available in Stage A")


# ===========================================================================
# Overview screen
# ===========================================================================
def _page_overview() -> None:
    # Breadcrumb
    st.markdown(
        '<div class="breadcrumb">Overview</div>',
        unsafe_allow_html=True,
    )

    # Hero section
    if st.session_state.mode == "fixtures":
        mode_badge = '<span class="demo-badge">Demo mode</span>'
    else:
        mode_badge = '<span class="demo-badge" style="background:#fff3cd;color:#856404;border-color:#ffc107">Live agent</span>'

    situation = _overview_situation()
    situation_text = (
        situation
        if situation
        else "A key supplier has a delay in delivering materials, which could disrupt downstream production and customer deliveries."
    )

    # Two-column hero layout — left: text + button, right: illustration
    hero_col, img_col = st.columns([3, 2])
    with hero_col:
        st.markdown(
            f"""
<div class="hero-section">
  {mode_badge}
  <div class="hero-title">Supply Chain<br>Recovery</div>
  <div class="hero-subtitle">{situation_text}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        if st.session_state.mode == "fixtures":
            if st.button(
                "Find a recovery plan  →",
                key="cta_find",
                type="primary",
                use_container_width=False,
            ):
                navigate_to("find_plan")
                st.rerun()

    with img_col:
        import pathlib as _pathlib
        _img_path = _pathlib.Path(__file__).parent / "ui" / "assets" / "supply-chain-recovery.png"
        if _img_path.exists():
            st.image(
                str(_img_path),
                use_container_width=True,
            )

    if st.session_state.mode != "fixtures":
        render_live_unavailable()
        return

    st.divider()

    # Secondary action cards
    st.markdown(
        "<p style='font-size:0.9rem;color:#57606a;margin-bottom:1rem'>"
        "Or explore another angle:</p>",
        unsafe_allow_html=True,
    )

    card_col1, card_col2 = st.columns(2)

    with card_col1:
        st.markdown(
            """
<div class="action-card">
  <div class="action-card-icon">⚖️</div>
  <div class="action-card-body">
    <div class="action-card-title">Compare options</div>
    <div class="action-card-desc">Review and contrast viable recovery scenarios.</div>
  </div>
  <div class="action-card-arrow">›</div>
</div>
""",
            unsafe_allow_html=True,
        )
        if st.button("Go to Compare options", key="cta_compare",
                     use_container_width=True, type="secondary"):
            navigate_to("compare")
            st.rerun()

    with card_col2:
        st.markdown(
            """
<div class="action-card">
  <div class="action-card-icon">📊</div>
  <div class="action-card-body">
    <div class="action-card-title">Risk under uncertainty</div>
    <div class="action-card-desc">See how each option holds up when the arrival date is uncertain.</div>
  </div>
  <div class="action-card-arrow">›</div>
</div>
""",
            unsafe_allow_html=True,
        )
        if st.button("Go to Risk under uncertainty", key="cta_impact",
                     use_container_width=True, type="secondary"):
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

def _make_retry_callback(fixture_id: str):
    """Return a zero-argument callback that queues *fixture_id* for retry.

    The callback records the target fixture_id in session state so that
    the next rerun can process it via _handle_pending_retry().  It does
    not call st.rerun() itself because Streamlit's on_click callbacks run
    before rendering — the subsequent automatic rerun is sufficient.
    """
    def _callback() -> None:
        st.session_state["_pending_retry_fixture_id"] = fixture_id
    return _callback


def _handle_pending_retry() -> None:
    """Process a queued retry request (if any) before rendering messages.

    If session state contains _pending_retry_fixture_id, call
    _add_fixture_to_conversation() with that fixture_id and clear the
    key so subsequent reruns are no-ops.  Triggers st.rerun() so the
    new message is immediately visible.
    """
    pending = st.session_state.pop("_pending_retry_fixture_id", None)
    if pending is not None:
        # Retry must bypass the idempotency check: the user explicitly asked
        # to re-run the same fixture (force=True).
        _add_fixture_to_conversation(pending, force=True)
        st.rerun()


def _render_display_messages() -> None:
    """Re-render every stored conversation message from display_messages."""
    for idx, msg in enumerate(st.session_state.display_messages):
        msg_type = msg.get("type")
        if msg_type == "user":
            with st.chat_message("user"):
                prefix = "**Example question:** " if msg.get("is_fixture") else ""
                st.markdown(f"{prefix}{msg['text']}")
        elif msg_type == "assistant":
            render_result(msg["result"])
            if msg.get("is_error") and msg.get("show_retry"):
                # Regression C fix: pass a unique key per message so that
                # multiple historical error banners do not collide on the
                # same Streamlit element ID.
                # Issue 1 fix: bind a real retry callback using the message's
                # fixture_id instead of a no-op lambda.
                retry_fixture_id = msg.get("fixture_id")
                on_retry = (
                    _make_retry_callback(retry_fixture_id)
                    if retry_fixture_id is not None
                    else lambda: None
                )
                render_error_retry_banner(on_retry=on_retry, msg_key=str(idx))
        elif msg_type == "unmatched":
            render_unmatched_message()


def _add_fixture_to_conversation(fixture_id: str, *, force: bool = False) -> None:
    """Record a fixture selection in display_messages (idempotent by fixture_id).

    If the most-recently stored turn already corresponds to this fixture_id,
    do nothing — prevents duplicates on ordinary reruns.

    Pass force=True to bypass the idempotency check.  This is used by
    the retry path and by explicit reselection after a placeholder navigation,
    where the user deliberately wants the same fixture appended again.
    """
    msgs = st.session_state.display_messages

    # Idempotency check: skip if the last stored turn is already this fixture.
    # Bypassed when force=True (retry, explicit reselection after placeholder).
    if not force and msgs:
        last = msgs[-1]
        if last.get("fixture_id") == fixture_id:
            return

    entry = _catalog[fixture_id]
    result = get_result_copy(_catalog, fixture_id)
    if result is None:
        return

    # Update active state.
    st.session_state.active_result = result
    st.session_state.active_proposal = result.get("proposal")
    st.session_state.submitted_request = {
        "fixture_id": fixture_id,
        "mode": "fixtures",
    }

    # Append user message.
    msgs.append({
        "type": "user",
        "text": entry["question"],
        "is_fixture": True,
        "fixture_id": fixture_id,
        "mode": "fixtures",
    })
    # Append assistant message.
    msgs.append({
        "type": "assistant",
        "result": result,
        "is_error": is_error_fixture(result),
        "show_retry": is_error_fixture(result),
        "fixture_id": fixture_id,
        "mode": "fixtures",
    })


def _add_typed_question_to_conversation(
    text: str,
    matched_id: str | None,
) -> None:
    """Record a typed question submission in display_messages.

    If matched_id is not None, records a successful fixture response.
    Otherwise records an unmatched limitation message.
    Does nothing if the last turn already matches this question text to
    prevent double-appending on rerun.
    """
    msgs = st.session_state.display_messages

    if matched_id is not None:
        result = get_result_copy(_catalog, matched_id)
        if result is None:
            return

        # Update active state.
        st.session_state.active_result = result
        st.session_state.active_proposal = result.get("proposal")
        st.session_state.submitted_request = {
            "fixture_id": matched_id,
            "mode": "fixtures",
        }

        msgs.append({
            "type": "user",
            "text": text,
            "is_fixture": False,
            "fixture_id": matched_id,
            "mode": "fixtures",
        })
        msgs.append({
            "type": "assistant",
            "result": result,
            "is_error": is_error_fixture(result),
            "show_retry": is_error_fixture(result),
            "fixture_id": matched_id,
            "mode": "fixtures",
        })
    else:
        # Unmatched — do not set active_result or submitted_request.
        msgs.append({
            "type": "user",
            "text": text,
            "is_fixture": False,
            "fixture_id": None,
            "mode": "fixtures",
        })
        msgs.append({
            "type": "unmatched",
            "fixture_id": None,
            "mode": "fixtures",
        })


def _fixture_selector(page_hint: str) -> None:
    """Render the example selector for a given page context.

    Regression A fix: selection is processed BEFORE rendering so that the
    resulting messages are visible on the same interaction (via st.rerun()).

    Regression B fix: ``last_handled_selector_{page_hint}`` tracks which
    fixture_id was most recently *processed*, independently of the widget
    value.  A selection is only processed when the chosen_id differs from
    that tracking key, so a form submission or ordinary rerun cannot replay
    a stale widget value and overwrite the current conversation.
    """
    st.markdown("#### Saved examples")
    st.caption("Pick a saved question to see the recorded answer.")

    # Build display list: (fixture_id, label)
    selector_options = ["— select an example —"] + [fid for fid, _ in _fixture_options]
    selector_labels = ["— select an example —"] + [lbl for _, lbl in _fixture_options]

    chosen_index = st.selectbox(
        "Saved examples",
        options=range(len(selector_options)),
        format_func=lambda i: selector_labels[i],
        index=0,
        key=f"fixture_selector_{page_hint}",
        label_visibility="collapsed",
    )

    handled_key = f"last_handled_selector_{page_hint}"

    if chosen_index == 0:
        # Issue 2 fix: selecting the placeholder resets the handled tracker so
        # that an explicit re-selection of the same fixture_id is recognised as
        # a new event on the next interaction.
        if handled_key in st.session_state:
            del st.session_state[handled_key]
        # Render the existing conversation and show the prompt.
        _handle_pending_retry()
        _render_display_messages()
        st.caption("Select an example above to load its response.")
        return

    chosen_id = selector_options[chosen_index]

    # Regression B: only process a selection when it is a *new* event —
    # i.e. the chosen_id has not already been handled in a previous render.
    # This prevents a stale widget value from replaying after a form
    # submission or an ordinary rerun.
    if st.session_state.get(handled_key) != chosen_id:
        # Issue 2 fix: if handled_key is absent (cleared by placeholder navigation),
        # the user is making an explicit intentional reselection — bypass the
        # idempotency check so the same fixture_id can be appended again.
        force_add = handled_key not in st.session_state
        _add_fixture_to_conversation(chosen_id, force=force_add)
        st.session_state[handled_key] = chosen_id
        # Regression A: immediately rerun so that _render_display_messages
        # on the next pass shows the newly added messages.
        st.rerun()

    # Issue 1 fix: process any pending retry request before rendering so
    # clicking a historical retry button adds the fixture and refreshes.
    _handle_pending_retry()
    # On subsequent reruns the selection is already handled; just render.
    _render_display_messages()


def _free_text_input(page_hint: str) -> None:
    """Accept free-text input but show limitation message if no match."""
    with st.form(key=f"free_text_form_{page_hint}", clear_on_submit=True):
        user_input = st.text_input(
            "Or type a question (demo mode answers only the saved questions)",
            placeholder="e.g. Our budget is 500 dollars. What should we do?",
            key=f"free_text_{page_hint}",
        )
        submitted = st.form_submit_button("Submit")

    if submitted and user_input.strip():
        # Check whether any fixture matches the input exactly.
        matched_id = None
        for fid, entry in _catalog.items():
            if entry["question"].strip() == user_input.strip():
                matched_id = fid
                break  # use first match; duplicates are handled by fixture_id
        _add_typed_question_to_conversation(user_input.strip(), matched_id)
        st.rerun()


# ===========================================================================
# Shared chat-page renderer (Fixtures mode body)
# ===========================================================================

def _render_fixtures_page(page_hint: str, header: str, description: str) -> None:
    """Render a fixture-based chat page (Find plan / Compare / Impact)."""
    # Breadcrumb
    st.markdown(
        '<div class="breadcrumb">'
        '<a href="#">Overview</a>'
        '<span>›</span>'
        f'{header.lstrip("🔍⚖️📊 ")}'
        '</div>',
        unsafe_allow_html=True,
    )
    st.header(header)
    st.markdown(description)
    _fixture_selector(page_hint)
    st.divider()
    _free_text_input(page_hint)


# ===========================================================================
# Page: Find a recovery plan  (budget form — Stage B+)
# ===========================================================================

def _build_find_plan_message(budget: int) -> str:
    """Build the user message sent to run_agent for a budget query."""
    return (
        f"Our budget is {budget} dollars. "
        "What should we do to maximise on-time orders?"
    )


def _validate_find_plan_result(result: dict, budget: int) -> str:
    """Validate a run_agent result for the find_plan budget form.

    Returns one of: "ok" | "over_budget" | "unsupported" | "unverifiable" | "api_error"

    Status meanings
    ---------------
    "api_error"    — result contains an "error" key (live call failed).
    "unsupported"  — view type is "unsupported"; backend shows its scope note.
    "unverifiable" — response lacks the structured data needed to verify:
                       · no view, or view type is not "recommendation"
                       · view settings budget != submitted budget
                       · recommended field is absent or empty (no explanation given)
                       · recommended row not found in rows, or extra_cost missing
    "over_budget"  — a recommendation exists but its extra_cost exceeds budget.
    "ok"           — recommendation exists and extra_cost is within budget.

    Note: "no_match" is intentionally not returned here.  The backend has no
    signal in the current fixture set that is specific to "no plans within
    budget" that cannot be confused with other reasons.  UI callers should
    treat "unsupported" and "unverifiable" as the two distinct non-ok paths.
    """
    if "error" in result:
        return "api_error"

    view = result.get("view")

    # Backend explicitly says the scenario is out of scope → show scope note
    if view and view.get("type") == "unsupported":
        return "unsupported"

    if not view or view.get("type") != "recommendation":
        return "unverifiable"

    settings = view.get("settings") or {}
    response_budget = settings.get("budget")
    if response_budget is None or int(response_budget) != int(budget):
        return "unverifiable"

    recommended_code = view.get("recommended")
    rows = view.get("rows", [])

    # Recommended field absent or empty: reason unknown → unverifiable
    if not recommended_code:
        return "unverifiable"

    rec_row = next((r for r in rows if r.get("code") == recommended_code), None)
    if rec_row is None:
        return "unverifiable"

    extra_cost = rec_row.get("extra_cost")
    if extra_cost is None:
        return "unverifiable"
    if int(extra_cost) > int(budget):
        return "over_budget"

    return "ok"


def _page_find_plan(*, _run_agent_fn=None) -> None:
    """Budget input form for finding a recovery plan.

    Parameters
    ----------
    _run_agent_fn:
        Injectable override for run_agent — used exclusively by unit tests.
        Must never be passed from app code or the sidebar.
        When None (default), the real run_agent is used (requires WX_API_KEY).
    """
    # Breadcrumb
    st.markdown(
        '''<div class="breadcrumb">'''
        '''<a href="#">Overview</a>'''
        '''<span>›</span>'''
        "Find a recovery plan"
        '''</div>''',
        unsafe_allow_html=True,
    )
    st.header("🔍 Find a recovery plan")
    st.markdown(
        "Enter your maximum additional budget (USD) and click the button to "
        "get a recovery recommendation."
    )

    # --- Budget input form ---
    with st.form(key="find_plan_form", clear_on_submit=False):
        budget_input = st.number_input(
            "Budget (USD)",
            min_value=0,
            max_value=1_000_000,
            value=st.session_state.get("fp_budget") or 500,
            step=100,
            help="Maximum additional spend allowed for a recovery action.",
            key="find_plan_budget_widget",
        )
        submitted = st.form_submit_button(
            "Find a recovery plan",
            type="primary",
            use_container_width=False,
        )

    if submitted:
        budget = int(budget_input)

        # Determine which run_agent to call
        api_fn = _run_agent_fn
        if api_fn is None:
            # Check whether the real API key is configured.
            import os
            if not os.environ.get("WX_API_KEY"):
                # Clear any stale result so the previous answer is not shown.
                st.session_state.fp_budget = budget
                st.session_state.fp_result = None
                st.session_state.fp_status = "key_missing"
                st.rerun()
                return
            api_fn = run_agent

        # Clear previous result before calling so stale data never bleeds through.
        st.session_state.fp_budget = budget
        st.session_state.fp_result = None
        st.session_state.fp_status = None

        user_message = _build_find_plan_message(budget)
        try:
            result = api_fn(user_message)
        except Exception:
            st.session_state.fp_status = "api_error"
            st.rerun()
            return

        status = _validate_find_plan_result(result, budget)
        # Store the full result for "ok" and "unsupported" so the renderer
        # can display the recommendation card or the scope note respectively.
        st.session_state.fp_result = result if status in ("ok", "unsupported") else None
        st.session_state.fp_status = status
        st.rerun()

    # --- Render result / guidance ---
    status = st.session_state.get("fp_status")
    if status is None:
        # Nothing submitted yet — show API key guidance if key is absent.
        import os
        if _run_agent_fn is None and not os.environ.get("WX_API_KEY"):
            render_api_key_missing()
        return

    render_find_plan_result(
        status=status,
        budget=st.session_state.get("fp_budget"),
        result=st.session_state.get("fp_result"),
    )


# ===========================================================================
# Page: Compare options
# ===========================================================================
def _page_compare() -> None:
    _render_fixtures_page(
        "compare",
        "⚖️ Compare options",
        "Select a saved comparison example to see recovery options side by side.",
    )


# ===========================================================================
# Page: Risk under uncertainty
# ===========================================================================
def _page_impact(*, _get_overview_fn=None) -> None:
    """Risk under uncertainty page.

    Parameters
    ----------
    _get_overview_fn:
        Injectable override for get_overview — used exclusively by unit tests.
        When None (default), the real get_overview is used.
    """
    # Breadcrumb
    st.markdown(
        '<div class="breadcrumb">'
        '<a href="#">Overview</a>'
        '<span>›</span>'
        'Risk under uncertainty'
        '</div>',
        unsafe_allow_html=True,
    )
    st.header("📊 Risk under uncertainty")

    # Top-of-page overview: always rendered in both Fixtures and Live mode.
    overview_fn = _get_overview_fn if _get_overview_fn is not None else get_overview
    try:
        overview = overview_fn()
        overview_view = overview.get("view") or overview
        render_world_risk(overview_view)
    except Exception as exc:
        st.error(str(exc))

    st.divider()
    st.markdown("### Ask about risk")

    # In Live mode: no selector, show unavailable warning and stop.
    if st.session_state.mode == "live":
        render_live_unavailable()
        return

    # Fixtures mode: example selector and free-text form.
    _fixture_selector("impact")
    st.divider()
    _free_text_input("impact")


# ===========================================================================
# Live-mode guard — applied to every content page
# ===========================================================================

def _live_mode_guard() -> bool:
    """Return True if we are in Live mode and content should be blocked.

    When True, the caller should show render_live_unavailable() and return
    immediately without rendering any fixture controls or results.
    """
    return st.session_state.mode == "live"


# ===========================================================================
# Main router
# ===========================================================================
def main() -> None:
    _sidebar()

    page = st.session_state.current_page

    if page == "overview":
        _page_overview()
        return

    if page == "find_plan":
        # find_plan handles its own API-key check; skip the Live mode guard.
        _page_find_plan()
        return

    if page == "impact":
        # impact handles its own Live mode behaviour internally.
        # _get_overview_fn is intentionally not passed from the router.
        _page_impact()
        return

    # For all other non-overview pages: block entirely in Live mode.
    if _live_mode_guard():
        render_live_unavailable()
        return

    if page == "compare":
        _page_compare()
    else:
        # Fallback for future pages
        st.info(f"Page '{page}' is not yet implemented.")


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module on every rerun; call main() at module level.
    main()
