"""
ui/renderers.py — Response presentation helpers.

Stage A: renders the agent answer as chat messages using st.chat_message
and st.markdown. Richer structured cards (tables, KPI cards, approval
controls) are rendered here using view data from the fixture results.

The renderers never compute, modify, or reinterpret any value from the
result dict. Numbers are displayed exactly as received.
"""
from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# CSS injection — applied once per session by app.py
# ---------------------------------------------------------------------------

DEMO_CSS = """
<style>
/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background-color: #0f1b2d !important;
}
[data-testid="stSidebar"] * {
    color: #e8edf3 !important;
}
[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    color: #c9d4e0 !important;
    border: none !important;
    text-align: left !important;
    padding: 0.45rem 0.75rem !important;
    border-radius: 6px !important;
    font-size: 0.95rem !important;
    width: 100% !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background-color: rgba(255,255,255,0.08) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background-color: #3b82d4 !important;
    color: #ffffff !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    color: #c9d4e0 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
    color: #c9d4e0 !important;
}
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] .stCaption p {
    color: #8ca0b8 !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.12) !important;
}

/* ---- Sidebar brand label ---- */
.sidebar-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 1rem 0 1.25rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.12);
    margin-bottom: 0.75rem;
}
.sidebar-brand-icon {
    font-size: 1.5rem;
    line-height: 1;
}
.sidebar-brand-text {
    font-size: 0.85rem;
    font-weight: 600;
    color: #ffffff !important;
    line-height: 1.3;
}

/* ---- Overview hero ---- */
.hero-section {
    background: #ffffff;
    padding: 2.5rem 0 1.5rem 0;
}
.demo-badge {
    display: inline-block;
    background-color: #eef3fb;
    color: #3b82d4;
    border: 1px solid #c3d6f4;
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    margin-bottom: 0.75rem;
}
.hero-title {
    font-size: 2.4rem;
    font-weight: 700;
    color: #0f1b2d;
    line-height: 1.15;
    margin: 0.25rem 0 0.75rem 0;
}
.hero-subtitle {
    font-size: 1.0rem;
    color: #4a5568;
    line-height: 1.6;
    max-width: 480px;
    margin-bottom: 1.75rem;
}

/* ---- Main CTA button ---- */
.stButton > button[kind="primary"] {
    background-color: #3b82d4 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 1.0rem !important;
    font-weight: 600 !important;
    padding: 0.65rem 1.5rem !important;
    letter-spacing: 0.01em !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #2563b0 !important;
}

/* ---- Secondary action cards ---- */
.action-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 1.25rem 1.4rem;
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    cursor: pointer;
    transition: border-color 0.15s;
    min-height: 90px;
}
.action-card:hover {
    border-color: #3b82d4;
}
.action-card-icon {
    font-size: 1.6rem;
    line-height: 1;
    padding-top: 2px;
    flex-shrink: 0;
}
.action-card-body {}
.action-card-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: #0f1b2d;
    margin-bottom: 0.3rem;
}
.action-card-desc {
    font-size: 0.85rem;
    color: #57606a;
    line-height: 1.5;
}
.action-card-arrow {
    margin-left: auto;
    color: #9ca3af;
    font-size: 1.1rem;
    align-self: center;
    flex-shrink: 0;
}

/* ---- Result cards ---- */
.result-summary-card {
    background: #eef5ff;
    border: 1.5px solid #3b82d4;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    margin-bottom: 1.25rem;
}
.result-summary-icon {
    background: #3b82d4;
    color: #fff;
    border-radius: 50%;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1rem;
    flex-shrink: 0;
}
.result-summary-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: #0f1b2d;
    margin-bottom: 0.3rem;
}
.result-summary-desc {
    font-size: 0.88rem;
    color: #374151;
    line-height: 1.55;
}

.kpi-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 1.1rem 1.3rem;
}
.kpi-card-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: #57606a;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.6rem;
}
.kpi-badge {
    display: inline-block;
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 0.88rem;
    font-weight: 600;
    letter-spacing: 0.01em;
}
.kpi-badge-green {
    background: #d1fae5;
    color: #065f46;
}
.kpi-badge-yellow {
    background: #fef3c7;
    color: #92400e;
}
.kpi-badge-red {
    background: #fee2e2;
    color: #991b1b;
}
.kpi-badge-blue {
    background: #dbeafe;
    color: #1e3a8a;
}
.kpi-badge-purple {
    background: #ede9fe;
    color: #4c1d95;
}

/* ---- Comparison table ---- */
.cmp-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
    margin-top: 0.5rem;
}
.cmp-table th {
    background: #f7f8fa;
    color: #374151;
    font-weight: 600;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 2px solid #e5e7eb;
}
.cmp-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #f0f1f3;
    color: #1f2328;
    vertical-align: middle;
}
.cmp-table tr:last-child td {
    border-bottom: none;
}
.cmp-table tr.cmp-row-recommended {
    background: #f0f7ff;
    font-weight: 600;
}
.star-badge {
    color: #3b82d4;
    font-size: 0.95rem;
}

/* ---- Breadcrumb ---- */
.breadcrumb {
    font-size: 0.85rem;
    color: #57606a;
    margin-bottom: 1rem;
}
.breadcrumb a {
    color: #3b82d4;
    text-decoration: none;
}
.breadcrumb span {
    margin: 0 6px;
    color: #9ca3af;
}
</style>
"""


def inject_css() -> None:
    """Inject the shared CSS once. Call at the top of main()."""
    st.markdown(DEMO_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_cost(value: int | float | None) -> str:
    """Format an integer USD cost as $X,XXX."""
    if value is None:
        return "—"
    return f"${int(value):,}"


def _extra_cost_badge(extra_cost: int | float | None, budget: int | float | None) -> str:
    """Return an HTML badge for the extra cost KPI card."""
    if extra_cost is None:
        return '<span class="kpi-badge kpi-badge-blue">—</span>'
    cost_str = _fmt_cost(extra_cost)
    if budget is not None:
        within = int(extra_cost) <= int(budget)
        cls = "kpi-badge-green" if within else "kpi-badge-yellow"
        label = f"{cost_str} — within budget" if within else f"{cost_str} — over budget"
    else:
        cls = "kpi-badge-blue"
        label = cost_str
    return f'<span class="kpi-badge {cls}">{label}</span>'


def _delivery_impact_badge(total_days_late: int | None, on_time: int | None, total: int | None) -> str:
    """Return an HTML badge for the delivery impact KPI card."""
    if total_days_late is None or on_time is None or total is None:
        return '<span class="kpi-badge kpi-badge-blue">—</span>'
    if total_days_late == 0:
        cls = "kpi-badge-green"
        label = "All orders on time"
    elif total_days_late <= 5:
        cls = "kpi-badge-yellow"
        label = f"{on_time}/{total} on time · {total_days_late} day(s) late total"
    else:
        cls = "kpi-badge-red"
        label = f"{on_time}/{total} on time · {total_days_late} day(s) late total"
    return f'<span class="kpi-badge {cls}">{label}</span>'


# ---------------------------------------------------------------------------
# View-type renderers
# ---------------------------------------------------------------------------

def _render_recommendation_view(view: dict) -> None:
    """Render a recommendation or comparison view with structured cards."""
    vtype = view.get("type")  # "recommendation" or "comparison"
    rows = view.get("rows", [])
    recommended_code = view.get("recommended")  # None for comparison
    settings = view.get("settings") or {}
    budget = settings.get("budget")

    if not rows:
        # Fallback: show markdown
        st.markdown(view.get("markdown", ""))
        return

    # --- Budget header badge ---
    if budget is not None:
        st.markdown(
            f'<div style="margin-bottom:0.75rem">'
            f'<span class="demo-badge">Budget: {_fmt_cost(budget)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # --- Find the recommended row for the summary card ---
    if recommended_code and vtype == "recommendation":
        rec_row = next((r for r in rows if r.get("code") == recommended_code), None)
        if rec_row:
            ec = rec_row.get("extra_cost")
            on_time = rec_row.get("on_time_orders")
            tot = rec_row.get("total_orders")
            days_late = rec_row.get("total_days_late")
            cost_badge = _extra_cost_badge(ec, budget)
            delivery_badge = _delivery_impact_badge(days_late, on_time, tot)

            st.markdown(
                f"""
<div class="result-summary-card">
  <div class="result-summary-icon">✓</div>
  <div>
    <div class="result-summary-title">{rec_row.get("name", recommended_code)}</div>
    <div class="result-summary-desc">Recommended option: <strong>{recommended_code}</strong></div>
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

            kpi_col1, kpi_col2 = st.columns(2)
            with kpi_col1:
                st.markdown(
                    f"""
<div class="kpi-card">
  <div class="kpi-card-label">💰 Extra cost</div>
  {cost_badge}
</div>
""",
                    unsafe_allow_html=True,
                )
            with kpi_col2:
                st.markdown(
                    f"""
<div class="kpi-card">
  <div class="kpi-card-label">🚚 Delivery impact</div>
  {delivery_badge}
</div>
""",
                    unsafe_allow_html=True,
                )

    # --- Options table ---
    with st.expander("All options compared", expanded=(vtype == "comparison")):
        # Build rows HTML
        header = (
            "<table class='cmp-table'>"
            "<thead><tr>"
            "<th>Option</th>"
            "<th>On-time orders</th>"
            "<th>Days late (total)</th>"
            "<th>Extra cost</th>"
            "</tr></thead><tbody>"
        )
        body = ""
        for r in rows:
            code = r.get("code", "")
            name = r.get("name", code)
            is_rec = (code == recommended_code)
            row_class = "cmp-row-recommended" if is_rec else ""
            star = ' <span class="star-badge">★</span>' if is_rec else ""
            on_t = r.get("on_time_orders")
            tot_o = r.get("total_orders")
            days_l = r.get("total_days_late")
            ec = r.get("extra_cost")

            on_time_str = f"{on_t}/{tot_o}" if (on_t is not None and tot_o is not None) else "—"
            days_str = str(days_l) if days_l is not None else "—"
            cost_str = _fmt_cost(ec) if ec is not None else "$0"

            # Budget compliance indicator
            budget_note = ""
            if budget is not None and ec is not None:
                budget_note = " ✓" if int(ec) <= int(budget) else ""

            body += (
                f"<tr class='{row_class}'>"
                f"<td><strong>{name}</strong>{star}</td>"
                f"<td>{on_time_str}</td>"
                f"<td>{days_str}</td>"
                f"<td>{cost_str}{budget_note}</td>"
                f"</tr>"
            )

        st.markdown(header + body + "</tbody></table>", unsafe_allow_html=True)

    # Always show the full markdown answer too
    with st.expander("Full analysis", expanded=False):
        st.markdown(view.get("markdown", ""))


def _render_order_view(view: dict) -> None:
    """Render an order detail view."""
    detail = view.get("detail", {})
    if not detail:
        st.markdown(view.get("markdown", ""))
        return

    order_id = detail.get("order_id", "—")
    option = detail.get("option", "—")
    days_late = detail.get("days_late", 0)
    summary = detail.get("summary", "")
    due_date = detail.get("due_date", "—")
    delivery_date = detail.get("delivery_date", "—")

    if days_late and int(days_late) > 0:
        delay_badge = f'<span class="kpi-badge kpi-badge-red">{days_late} day(s) late</span>'
    else:
        delay_badge = '<span class="kpi-badge kpi-badge-green">On time</span>'

    st.markdown(
        f"""
<div class="kpi-card" style="margin-bottom:1rem">
  <div class="kpi-card-label">📦 Order {order_id} — under {option}</div>
  {delay_badge}
  <div style="margin-top:0.75rem;font-size:0.88rem;color:#374151;line-height:1.6">
    <strong>Due:</strong> {due_date} &nbsp;·&nbsp; <strong>Delivery:</strong> {delivery_date}
  </div>
  {f'<div style="margin-top:0.6rem;font-size:0.88rem;color:#374151;line-height:1.6">{summary}</div>' if summary else ''}
</div>
""",
        unsafe_allow_html=True,
    )

    with st.expander("Full analysis", expanded=False):
        st.markdown(view.get("markdown", ""))


def _render_unsupported_view(view: dict) -> None:
    """Render an unsupported hypothetical view."""
    scope_note = view.get("scope_note", "")
    rows = view.get("rows", [])

    st.info(
        f"**Outside current scope**  \n{scope_note}"
        if scope_note
        else "**Outside current scope** — this scenario is not supported yet.",
        icon="ℹ️",
    )

    if rows:
        with st.expander("Current scenario data for reference", expanded=False):
            header = (
                "<table class='cmp-table'>"
                "<thead><tr>"
                "<th>Option</th><th>On-time</th><th>Days late</th><th>Extra cost</th>"
                "</tr></thead><tbody>"
            )
            body = ""
            for r in rows:
                code = r.get("code", "")
                name = r.get("name", code)
                on_t = r.get("on_time_orders")
                tot_o = r.get("total_orders")
                days_l = r.get("total_days_late")
                ec = r.get("extra_cost")
                on_time_str = f"{on_t}/{tot_o}" if (on_t is not None and tot_o is not None) else "—"
                days_str = str(days_l) if days_l is not None else "—"
                cost_str = _fmt_cost(ec) if ec is not None else "$0"
                body += (
                    f"<tr><td>{name}</td><td>{on_time_str}</td>"
                    f"<td>{days_str}</td><td>{cost_str}</td></tr>"
                )
            st.markdown(header + body + "</tbody></table>", unsafe_allow_html=True)

    with st.expander("Full analysis", expanded=False):
        st.markdown(view.get("markdown", ""))


def _render_option_view(view: dict) -> None:
    """Render a single option detail view."""
    row = view.get("row", {})
    if not row:
        st.markdown(view.get("markdown", ""))
        return

    code = row.get("code", "")
    name = row.get("name", code)
    on_time = row.get("on_time_orders")
    total = row.get("total_orders")
    days_late = row.get("total_days_late")
    ec = row.get("extra_cost")

    delivery_badge = _delivery_impact_badge(days_late, on_time, total)
    cost_str = _fmt_cost(ec) if ec is not None else "$0"

    st.markdown(
        f"""
<div class="result-summary-card">
  <div class="result-summary-icon">📋</div>
  <div>
    <div class="result-summary-title">{name}</div>
    <div class="result-summary-desc">Option: <strong>{code}</strong></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    kpi_col1, kpi_col2 = st.columns(2)
    with kpi_col1:
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">💰 Extra cost</div>
  <span class="kpi-badge kpi-badge-blue">{cost_str}</span>
</div>
""",
            unsafe_allow_html=True,
        )
    with kpi_col2:
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">🚚 Delivery impact</div>
  {delivery_badge}
</div>
""",
            unsafe_allow_html=True,
        )

    with st.expander("Full analysis", expanded=False):
        st.markdown(view.get("markdown", ""))


def _render_proposal_view(view: dict) -> None:
    """Render a proposal view."""
    proposal = view.get("proposal", {})
    code = view.get("code", "")
    if not proposal:
        st.markdown(view.get("markdown", ""))
        return

    metrics = proposal.get("metrics", {})
    status = proposal.get("status", "pending_approval")
    on_time = metrics.get("on_time_orders")
    total = metrics.get("total_orders")
    days_late = metrics.get("total_order_days_late")
    ec = metrics.get("total_extra_cost")

    st.markdown(
        f"""
<div class="result-summary-card">
  <div class="result-summary-icon">📝</div>
  <div>
    <div class="result-summary-title">Proposed action: {code}</div>
    <div class="result-summary-desc">Status: <strong>{status.replace("_", " ").title()}</strong></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    kpi_col1, kpi_col2 = st.columns(2)
    with kpi_col1:
        cost_str = _fmt_cost(ec)
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">💰 Extra cost</div>
  <span class="kpi-badge kpi-badge-blue">{cost_str}</span>
</div>
""",
            unsafe_allow_html=True,
        )
    with kpi_col2:
        delivery_badge = _delivery_impact_badge(days_late, on_time, total)
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">🚚 Delivery impact</div>
  {delivery_badge}
</div>
""",
            unsafe_allow_html=True,
        )

    with st.expander("Proposed actions", expanded=False):
        actions = proposal.get("actions", [])
        for action in actions:
            st.markdown(f"- {action}")
        if not actions:
            st.caption("No action details available.")

    with st.expander("Full analysis", expanded=False):
        st.markdown(view.get("markdown", ""))


# ---------------------------------------------------------------------------
# world_risk helpers and renderer
# ---------------------------------------------------------------------------

def split_markdown_sections(markdown: str) -> dict[str, str]:
    """Split *markdown* on lines that start with '## ' and return a mapping
    of heading text to body text, preserving order.

    Text before the first heading is ignored.  A heading that appears more
    than once keeps the first body.  Empty input gives {}.
    """
    if not markdown:
        return {}
    sections: dict[str, str] = {}
    current_heading: str | None = None
    body_lines: list[str] = []

    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_heading is not None and current_heading not in sections:
                sections[current_heading] = "\n".join(body_lines).strip()
            current_heading = line[3:].strip()
            body_lines = []
        else:
            if current_heading is not None:
                body_lines.append(line)

    if current_heading is not None and current_heading not in sections:
        sections[current_heading] = "\n".join(body_lines).strip()

    return sections


def _render_world_risk_view(view: dict) -> None:
    """Render a world_risk view with summary table, charts, and expanders."""
    rows = view.get("rows", [])
    settings = view.get("settings") or {}
    budget = settings.get("budget")
    focus_date = view.get("focus_date")
    reading = view.get("reading") or []
    assumptions = view.get("assumptions") or []
    explanation_status = view.get("explanation_status")
    explanation = view.get("explanation")
    suggested_questions = view.get("suggested_questions") or []
    markdown_text = view.get("markdown", "")
    sections = split_markdown_sections(markdown_text)

    # 1. Situation and scope note
    situation = view.get("situation", "")
    if situation:
        st.markdown(situation)
    scope_note = view.get("scope_note", "")
    if scope_note:
        st.caption(scope_note)

    # 2. Reading lines (date mode) — always visible, never in an expander
    for line in reading:
        st.info(line)

    # 3. Summary table
    if rows:
        # Build column list
        col_headers = ["Option", "Extra cost", "Expected late orders",
                       "Chance of no late order"]
        if focus_date is not None:
            # Format focus date as "Mon D" e.g. "Nov 14"
            try:
                fd = datetime.date.fromisoformat(focus_date)
                month_abbr = fd.strftime("%b")
                day_str = str(fd.day)
                focus_col_label = f"Late if it arrives {month_abbr} {day_str}"
            except (ValueError, TypeError):
                focus_col_label = f"Late if it arrives {focus_date}"
            col_headers.append(focus_col_label)
        if budget is not None:
            col_headers.append(f"Within ${_fmt_cost(budget).lstrip('$')}")

        header_html = (
            "<table class='cmp-table'><thead><tr>"
            + "".join(f"<th>{h}</th>" for h in col_headers)
            + "</tr></thead><tbody>"
        )
        body_html = ""
        for r in rows:
            code = r.get("code", "")
            name = r.get("name", code)
            ec = r.get("extra_cost")
            exp_late = r.get("expected_late_orders")
            p_no_late = r.get("p_no_late_pct")

            ec_str = _fmt_cost(ec) if ec is not None else "—"
            exp_late_str = f"{exp_late:.2f}" if exp_late is not None else "—"
            p_no_late_str = f"{p_no_late:.1f}%" if p_no_late is not None else "—"
            option_str = f"{name} ({code})"

            cells = [option_str, ec_str, exp_late_str, p_no_late_str]
            if focus_date is not None:
                late_at = r.get("late_at_focus")
                cells.append(str(late_at) if late_at is not None else "—")
            if budget is not None:
                within = r.get("within_budget")
                cells.append("Yes" if within else "No")

            body_html += (
                "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
            )

        st.markdown(header_html + body_html + "</tbody></table>",
                    unsafe_allow_html=True)

    # 4. Two bar charts side by side
    if rows:
        codes = [r.get("code", "") for r in rows]
        late_values = [r.get("expected_late_orders", 0) for r in rows]
        cost_values = [r.get("extra_cost", 0) for r in rows]

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.caption("Expected late orders")
            chart_data_late = {
                "Option": codes,
                "Expected late orders": late_values,
            }
            # Render as a simple bar chart using st.bar_chart
            df_late = pd.DataFrame(chart_data_late).set_index("Option")
            st.bar_chart(df_late)
        with chart_col2:
            st.caption("Extra cost (USD)")
            chart_data_cost = {
                "Option": codes,
                "Extra cost (USD)": cost_values,
            }
            df_cost = pd.DataFrame(chart_data_cost).set_index("Option")  # noqa: PD013
            st.bar_chart(df_cost)

    # 5. AI explanation paragraph
    if explanation_status == "ok" and explanation:
        st.caption("AI explanation")
        st.markdown(explanation)
    elif explanation_status in ("dropped", "unavailable"):
        # Show the fixed "What this means" section from the markdown
        what_this_means = sections.get("What this means", "")
        if what_this_means:
            st.markdown(what_this_means)

    # 6. Collapsed expanders for markdown sections
    n_assumptions = len(assumptions)
    if n_assumptions > 0:
        st.caption(
            f"{n_assumptions} assumption{'s' if n_assumptions != 1 else ''} apply "
            f"to these numbers. Open Assumptions to read them."
        )

    expander_defs = [
        ("How sure is this", "How sure is this"),
        ("Shared causes", "Shared causes"),
        ("Late orders by receipt date", "Late orders by receipt date"),
        ("Trade-offs", "Trade-offs"),
        (f"Assumptions ({n_assumptions})", "Assumptions"),
        ("Notes", "Notes"),
    ]
    for expander_label, section_key in expander_defs:
        # For the assumptions expander, only show when assumptions is non-empty
        if section_key == "Assumptions" and n_assumptions == 0:
            continue
        body = sections.get(section_key, "")
        if not body:
            continue
        with st.expander(expander_label, expanded=False):
            st.markdown(body)

    # 7. Full analysis expander
    with st.expander("Full analysis", expanded=False):
        st.markdown(markdown_text)

    # 8. Suggested questions as a bulleted list
    if suggested_questions:
        st.caption("Questions you can ask")
        for q in suggested_questions:
            st.markdown(f"- {q}")


# ---------------------------------------------------------------------------
# Single result renderer (public API)
# ---------------------------------------------------------------------------

def render_result(result: dict, label: str = "assistant") -> None:
    """Render one agent result inside an st.chat_message block.

    - If the result contains an ``error`` key, show a warning banner and the
      safe answer text. No structured view is shown for errors.
    - Otherwise, dispatch to the appropriate view renderer based on view type.
    - Falls back to markdown if no view is present or type is unrecognised.
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
            return

        view = result.get("view")
        if view is None:
            # No structured view — show markdown answer only.
            st.markdown(answer)
            return

        vtype = view.get("type")
        if vtype in ("recommendation", "comparison"):
            _render_recommendation_view(view)
        elif vtype == "order":
            _render_order_view(view)
        elif vtype == "unsupported":
            _render_unsupported_view(view)
        elif vtype == "option":
            _render_option_view(view)
        elif vtype == "proposal":
            _render_proposal_view(view)
        elif vtype == "world_risk":
            _render_world_risk_view(view)
        else:
            # Unknown type — show markdown
            st.markdown(answer)


def render_error_retry_banner(on_retry, *, msg_key: str = "0") -> None:
    """Show an inline banner with a Try again button for a failed request.

    *on_retry* is a zero-argument callable invoked when the user clicks.
    *msg_key* must be unique per rendered banner.
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
        st.button("Try again", key=f"retry_{msg_key}", on_click=on_retry, type="secondary")


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


# ---------------------------------------------------------------------------
# Find-a-plan budget result renderer
# ---------------------------------------------------------------------------

def render_find_plan_result(
    status: str,
    budget: int | None = None,
    result: dict | None = None,
) -> None:
    """Render the outcome of a Find-a-recovery-plan budget query.

    Parameters
    ----------
    status:
        One of "ok" | "over_budget" | "unsupported" | "unverifiable"
              | "api_error" | "key_missing".
    budget:
        The budget value submitted by the user (USD integer). Used for display.
    result:
        The raw dict returned by run_agent.
        Required for "ok" (recommendation card).
        Optional for "unsupported" (scope_note from view).

    Status display rules
    --------------------
    "key_missing"  — WX_API_KEY not configured; show setup guidance (info).
    "api_error"    — API key present but call failed; show connection error.
    "unsupported"  — backend scope note; show the scope_note text from view.
    "over_budget"  — recommendation exists but extra_cost > budget.
    "unverifiable" — response lacks structured data to verify.
    "ok"           — show recommendation card.

    "no_match" is not a valid status; use "unsupported" or "unverifiable".
    """
    if status == "key_missing":
        render_api_key_missing()
        return

    if status == "api_error":
        st.error(
            "**Connection error** — the AI service could not be reached.  \n"
            "The API key is configured but the call failed. "
            "Please try again in a moment.",
            icon="🚫",
        )
        return

    if status == "unsupported":
        # Show the backend's scope note so the user knows why the question
        # cannot be answered, without implying there is no budget option.
        scope_note = ""
        if result is not None:
            view = result.get("view") or {}
            scope_note = view.get("scope_note", "")
        st.info(
            "**Outside current scope**  \n"
            + (scope_note if scope_note else
               "This scenario is not modelled yet. "
               "Only the recorded disruption D01 is supported."),
            icon="ℹ️",
        )
        return

    if status == "over_budget":
        st.warning(
            "**The returned recommendation exceeds your budget**  \n"
            f"The agent recommended an option with an extra cost above "
            f"{_fmt_cost(budget) if budget is not None else 'your budget'}.  \n"
            "Try a higher budget, or use **Compare options** to review all scenarios.",
            icon="💡",
        )
        return

    if status == "unverifiable":
        st.warning(
            "**Result could not be verified**  \n"
            "The agent\'s response does not contain structured recovery data for "
            "the requested budget. Try rephrasing your question or adjusting the budget.",
            icon="⚠️",
        )
        return

    if status != "ok" or result is None:
        return

    view = result.get("view") or {}
    rows = view.get("rows", [])
    recommended_code = view.get("recommended")
    settings = view.get("settings") or {}
    response_budget = settings.get("budget")

    # Find the recommended row
    rec_row = next((r for r in rows if r.get("code") == recommended_code), None)
    if rec_row is None:
        st.warning(
            "**Result could not be verified**  \n"
            "No recommended option was found in the agent response.",
            icon="⚠️",
        )
        return

    extra_cost = rec_row.get("extra_cost")
    on_time = rec_row.get("on_time_orders")
    total_orders = rec_row.get("total_orders")
    name = rec_row.get("name", recommended_code)

    # --- Summary card ---
    st.markdown(
        f"""
<div class="result-summary-card">
  <div class="result-summary-icon">✓</div>
  <div>
    <div class="result-summary-title">{name}</div>
    <div class="result-summary-desc">Recommended option: <strong>{recommended_code}</strong></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # --- KPI row: Budget | Extra cost | On-time orders ---
    kc1, kc2, kc3 = st.columns(3)

    with kc1:
        budget_display = _fmt_cost(budget) if budget is not None else "—"
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">🎯 Budget</div>
  <span class="kpi-badge kpi-badge-blue">{budget_display}</span>
</div>
""",
            unsafe_allow_html=True,
        )

    with kc2:
        cost_badge = _extra_cost_badge(extra_cost, budget)
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">💰 Extra cost</div>
  {cost_badge}
</div>
""",
            unsafe_allow_html=True,
        )

    with kc3:
        delivery_badge = _delivery_impact_badge(
            rec_row.get("total_days_late"), on_time, total_orders
        )
        st.markdown(
            f"""
<div class="kpi-card">
  <div class="kpi-card-label">🚚 On-time orders</div>
  {delivery_badge}
</div>
""",
            unsafe_allow_html=True,
        )

    # --- Full answer in expander ---
    with st.expander("Full analysis", expanded=False):
        st.markdown(result.get("answer", ""))


def render_api_key_missing() -> None:
    """Explain that a live API key is required for the budget form."""
    st.info(
        "**API connection required**  \n"
        "Enter a budget and click **Find a recovery plan** to get a recommendation.  \n\n"
        "A `WX_API_KEY` environment variable is needed to call the agent. "
        "Contact the team to configure the API connection.",
        icon="🔑",
    )
