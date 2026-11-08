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

from agent.prompts import build_messages, build_compose_message
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

    messages = build_messages(user_message, history)
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

    for step in range(1, max_steps + 1):
        response = llm.chat(messages, gather_tools)

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

    # ── Compose phase ─────────────────────────────────────────────────────────
    # Always make one final call with NO tools and the compose instruction.
    compose_msgs = messages + [build_compose_message(user_message)]
    compose_response = llm.chat(compose_msgs, [])
    answer = (compose_response.get("content") or "").strip()
    if not answer:
        answer = _CANNED_FALLBACK

    final_msg = {"role": "assistant", "content": answer}
    turn_messages.append(final_msg)
    updated_history = list(history or []) + turn_messages

    return {
        "answer":     answer,
        "tool_trace": tool_trace,
        "proposal":   proposal,
        "history":    updated_history,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _serialise(obj) -> str:
    """Serialise a dict to a JSON string for tool result messages."""
    return json.dumps(obj, default=str)
