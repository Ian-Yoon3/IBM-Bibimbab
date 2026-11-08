"""Agent loop — run_agent orchestrates the tool-calling conversation.

Public API
----------
run_agent(user_message, history=None, llm=None, max_steps=6) -> dict
"""

import json

from agent.prompts import build_messages
from agent.tool_specs import TOOL_SPECS, call_tool


_MAX_STEPS_ANSWER = (
    "I reached the maximum number of reasoning steps without a final answer. "
    "Please try rephrasing your question or asking something more specific."
)


def run_agent(
    user_message: str,
    history: list[dict] | None = None,
    llm=None,
    max_steps: int = 6,
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
        Maximum number of LLM calls before giving up.

    Returns
    -------
    dict with keys:
        answer      – str, the final text reply to the user
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

    # Track the messages added during this turn (everything after system+history)
    # so we can return them as the updated history.
    turn_messages: list[dict] = []
    user_msg = {"role": "user", "content": user_message}
    turn_messages.append(user_msg)

    for step in range(1, max_steps + 1):
        response = llm.chat(messages, TOOL_SPECS)

        if not response.get("tool_calls"):
            # Model produced a text answer
            answer = response.get("content") or ""
            final_msg = {"role": "assistant", "content": answer}
            turn_messages.append(final_msg)
            updated_history = list(history or []) + turn_messages
            return {
                "answer":     answer,
                "tool_trace": tool_trace,
                "proposal":   proposal,
                "history":    updated_history,
            }

        # ── one or more tool calls ────────────────────────────────────────────
        # Step A: build and append the assistant message with tool_calls.
        # arguments must be a JSON string (watsonx chat API expectation).
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

        # Step B: execute each tool and append a matching "tool" role message.
        for tc in response["tool_calls"]:
            result = call_tool(tc["name"], tc["args"])
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

    # max_steps exhausted without a text answer
    final_msg = {"role": "assistant", "content": _MAX_STEPS_ANSWER}
    turn_messages.append(final_msg)
    updated_history = list(history or []) + turn_messages
    return {
        "answer":     _MAX_STEPS_ANSWER,
        "tool_trace": tool_trace,
        "proposal":   proposal,
        "history":    updated_history,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _serialise(obj) -> str:
    """Serialise a dict to a JSON string for tool result messages."""
    return json.dumps(obj, default=str)
