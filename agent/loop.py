"""Agent loop — run_agent orchestrates the tool-calling conversation.

Two-phase design
----------------
Gather phase  – tool-calling loop (max_steps=10).  Runs until the model
                replies with no tool calls or max_steps is reached.
Compose phase – one final LLM call with NO tools and a compose
                instruction appended.  Always runs.  Its content is the
                final answer.  Canned fallback only when content is empty.

Duplicate-call guard
--------------------
Within one turn, if the same (tool name, normalised args) pair is called
again, the engine is not invoked.  The result is::

    {"note": "already called with these args; use the earlier result"}

Public API
----------
run_agent(user_message, history=None, llm=None, max_steps=10) -> dict
"""

import json

from agent import render
from agent.prompts import (build_messages, build_compose_message,
                           build_narrative_message, build_world_risk_message)
from agent.render import parse_world_risk_answer
from agent.tool_specs import call_tool, tool_specs_for


_CANNED_FALLBACK = (
    "I was unable to compose a final answer after gathering the evidence. "
    "Please try rephrasing your question."
)


def run_agent(
    user_message: str,
    history: list[dict] | None = None,
    llm=None,
    max_steps: int = 10,
) -> dict:
    """Run the tool-calling agent loop for one user turn.

    Parameters
    ----------
    user_message:
        The current user input.
    history:
        Prior conversation message dicts from a previous ``run_agent`` call.
        Pass ``None`` or ``[]`` for a fresh conversation.
    llm:
        An object with a ``.chat(messages, tools) -> dict`` method.  When
        ``None``, a ``WatsonxLLM`` instance is built from environment
        variables (requires a live .env).
    max_steps:
        Maximum number of gather-phase LLM calls before moving to compose.

    Returns
    -------
    dict with keys:
        answer      – str, the final text reply to the user (compose output)
        tool_trace  – list of {"step", "name", "args", "result"} dicts
        proposal    – the last propose_action result dict, or None
        history     – updated history list to pass into the next turn
    """
    if llm is None:
        from agent.llm import WatsonxLLM
        llm = WatsonxLLM()

    tool_trace: list[dict] = []
    proposal = None

    # Track messages added this turn for history (everything after system+history).
    turn_messages: list[dict] = []
    turn_messages.append({"role": "user", "content": user_message})

    # seen_calls: set of (name, normalised-args-json) seen this turn
    seen_calls: set[tuple] = set()

    # ── Gather phase ──────────────────────────────────────────────────────────
    gather_text: str | None = None   # text produced during gather (kept as context)

    # Determine tool list once per turn based on action-intent heuristic.
    # propose_action is omitted unless the user explicitly asks to act.
    gather_tools = tool_specs_for(user_message)
    allow_propose = any(t["function"]["name"] == "propose_action" for t in gather_tools)
    messages = build_messages(user_message, history, allow_propose=allow_propose)

    for step in range(1, max_steps + 1):
        try:
            response = llm.chat(messages, gather_tools)
        except Exception as exc:
            return _unavailable(exc, history, turn_messages, tool_trace, proposal)

        if not response.get("tool_calls"):
            # Model produced a text answer in the gather phase — keep it as
            # context for the compose prompt but do NOT use it as final answer.
            gather_text = response.get("content") or ""
            gather_msg = {"role": "assistant", "content": gather_text}
            messages.append(gather_msg)
            turn_messages.append(gather_msg)
            break

        # ── one or more tool calls ────────────────────────────────────────────
        assistant_msg: dict = {
            "role":       "assistant",
            "content":    "",
            "tool_calls": [],
        }
        for tc in response["tool_calls"]:
            assistant_msg["tool_calls"].append({
                "id":       tc["id"],
                "type":     "function",
                "function": {
                    "name":      tc["name"],
                    "arguments": json.dumps(tc["args"]),
                },
            })
        messages.append(assistant_msg)
        turn_messages.append(assistant_msg)

        offered_names = {s["function"]["name"] for s in gather_tools}
        for tc in response["tool_calls"]:
            call_key = (tc["name"], json.dumps(tc["args"], sort_keys=True))
            if call_key in seen_calls:
                result = {
                    "note": "already called with these args; use the earlier result"
                }
            else:
                seen_calls.add(call_key)
                result = call_tool(tc["name"], tc["args"],
                                   offered_names=offered_names)

            tool_trace.append({
                "step":   step,
                "name":   tc["name"],
                "args":   tc["args"],
                "result": result,
            })
            if tc["name"] == "propose_action" and "proposal_id" in result:
                proposal = result

            tool_msg = {
                "role":         "tool",
                "tool_call_id": tc["id"],
                "content":      _serialise(result),
            }
            messages.append(tool_msg)
            turn_messages.append(tool_msg)

    # ── Answer phase ──────────────────────────────────────────────────────────
    # The engine data is laid out by code (agent/render.py) so the manager sees
    # the same layout every time.  The model writes free text only where no
    # fixed view applies, and a short rationale inside recommendations.
    view = None
    try:
        view = _choose_view(user_message, tool_trace, proposal)
    except Exception:
        view = None   # rendering must never break the answer; fall back below

    if view is not None and view["type"] == "world_risk":
        # For world_risk views, ask the LLM for a short explanation paragraph.
        explanation = None
        try:
            wr_resp = llm.chat(
                messages + [build_world_risk_message(user_message, view)], []
            )
            content = (wr_resp.get("content") or "").strip()
            explanation = parse_world_risk_answer(content) or None
        except Exception:
            explanation = None
        view = render.world_risk_view(view["mode"], user_message,
                                      explanation=explanation)
        answer = view["markdown"]
    elif view is not None and view["type"] not in ("recommendation", "comparison"):
        answer = view["markdown"]                     # fully deterministic
    elif view is not None:
        narrative = ""
        try:
            resp = llm.chat(messages + [build_narrative_message(user_message, view)], [])
            narrative = (resp.get("content") or "").strip()
        except Exception:
            narrative = ""
        rationale, tradeoffs = render.split_narrative(narrative)
        if not rationale:
            rationale = ("(The AI explanation is unavailable. The table and the "
                         "recommendation above come from the engine.)")
        answer = render.recommendation_markdown(view, rationale, tradeoffs)
        view["markdown"] = answer
    else:
        compose_msgs = messages + [build_compose_message(user_message, proposal is not None)]
        try:
            compose_response = llm.chat(compose_msgs, [])
        except Exception as exc:
            return _unavailable(exc, history, turn_messages, tool_trace, proposal)
        answer = (compose_response.get("content") or "").strip()
        if not answer:
            answer = _CANNED_FALLBACK
        if proposal is not None:
            # Fallback only (normally the proposal view is used).  Written by
            # code so the user always learns that a proposal exists.
            answer += "\n\n" + proposal_notice(proposal)

    final_msg = {"role": "assistant", "content": answer}
    turn_messages.append(final_msg)
    updated_history = list(history or []) + turn_messages

    return {
        "answer":     answer,
        "tool_trace": tool_trace,
        "proposal":   proposal,
        "history":    updated_history,
        "view":       view,
    }


def _ok_results(tool_trace, name):
    return [t for t in tool_trace
            if t["name"] == name and isinstance(t["result"], dict)
            and "error" not in t["result"] and "note" not in t["result"]]


def _proposal_code(tool_trace) -> str:
    """Code of the option behind the proposal, e.g. 'HYBRID' or 'OF02 x40 + transfers'."""
    calls = _ok_results(tool_trace, "propose_action")
    a = (calls[-1]["args"] if calls else {}) or {}
    if a.get("scenario_id") and str(a["scenario_id"]).lower() != "null":
        return a["scenario_id"]
    flag = str(a.get("include_transfers", "")).lower() == "true"
    return render.option_code(None, a.get("offer_id"), a.get("qty"), flag)


def _choose_view(user_message, tool_trace, proposal):
    """Pick the fixed view for this turn, or None for a free-text answer.

    Priority: proposal > unsupported question > world_risk > order explanation >
    option description > comparison > recommendation > free text.
    """
    if proposal is not None:
        return render.proposal_view(proposal, _proposal_code(tool_trace))
    if render.is_unsupported(user_message):
        return render.unsupported_view(user_message=user_message)
    if render.is_world_risk_question(user_message):
        res = render.resolve_receipt_date(user_message)
        mode = "date" if res and res.get("status") == "in_window" else "general"
        return render.world_risk_view(mode, user_message)
    orders = _ok_results(tool_trace, "get_order_detail")
    if orders:
        return render.order_view(orders[-1]["result"])
    if render.is_option_question(user_message):
        return render.option_view(render.mentioned_codes(user_message)[0])
    ran_options = (_ok_results(tool_trace, "compare_scenarios")
                   or _ok_results(tool_trace, "explore_purchase_qty"))
    if render.is_comparison(user_message) and (
            ran_options or _ok_results(tool_trace, "get_priority_view")
            or len(render.mentioned_codes(user_message)) >= 2):
        return render.build_recommendation(user_message, tool_trace, compare=True)
    if ran_options:
        return render.build_recommendation(user_message, tool_trace)
    return None


# ── helpers ───────────────────────────────────────────────────────────────────

def proposal_notice(proposal: dict) -> str:
    """Deterministic confirmation line for a proposal created in this turn."""
    m = proposal.get("metrics") or {}
    return (
        f"**Proposal {proposal['proposal_id']} is pending approval in the UI. "
        f"Nothing has been executed.** "
        f"(on-time orders: {m.get('on_time_orders', 'n/a')} of "
        f"{m.get('total_orders', 'n/a')}, extra cost: "
        f"{m.get('total_extra_cost', 'n/a')} USD)"
    )


_UNAVAILABLE_ANSWER = (
    "The AI service could not be reached, so no analysis was produced. "
    "No numbers in this reply come from the engine. Please try again in a moment."
)


def _unavailable(exc, history, turn_messages, tool_trace, proposal) -> dict:
    """Return a safe result when the LLM call fails, instead of raising.

    The answer contains no numbers.  ``error`` carries the technical reason
    for logs or the UI.  A proposal created earlier in the turn is kept,
    because it already exists with status pending_approval.
    """
    final_msg = {"role": "assistant", "content": _UNAVAILABLE_ANSWER}
    return {
        "answer":     _UNAVAILABLE_ANSWER,
        "tool_trace": tool_trace,
        "proposal":   proposal,
        "history":    list(history or []) + turn_messages + [final_msg],
        "error":      f"{type(exc).__name__}: {str(exc)[:300]}",
    }


def _serialise(obj) -> str:
    """Serialise a dict to a JSON string for tool result messages."""
    return json.dumps(obj, default=str)
