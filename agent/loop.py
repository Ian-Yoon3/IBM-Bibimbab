"""Agent loop — run_agent orchestrates the tool-calling conversation.

Public API
----------
run_agent(user_message, history=None, llm=None, max_steps=6) -> dict
"""

from agent.prompts import build_messages, SYSTEM_PROMPT
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
        Prior conversation message dicts (role/content pairs, no tool_calls).
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

    for step in range(1, max_steps + 1):
        response = llm.chat(messages, TOOL_SPECS)

        if not response.get("tool_calls"):
            # Model produced a text answer
            answer = response.get("content") or ""
            updated_history = _build_history(history, user_message, tool_trace, answer)
            return {
                "answer":     answer,
                "tool_trace": tool_trace,
                "proposal":   proposal,
                "history":    updated_history,
            }

        # ── one or more tool calls ────────────────────────────────────────────
        # Step A: append the assistant message containing tool_calls
        assistant_msg: dict = {"role": "assistant", "tool_calls": []}
        for tc in response["tool_calls"]:
            assistant_msg["tool_calls"].append({
                "id":       tc["id"],
                "type":     "function",
                "function": {
                    "name":      tc["name"],
                    "arguments": tc["args"],
                },
            })
        messages.append(assistant_msg)

        # Step B: execute each tool and append a "tool" role message
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

            messages.append({
                "role":         "tool",
                "tool_call_id": tc["id"],
                "content":      _serialise_result(result),
            })

    # max_steps exhausted without a text answer
    updated_history = _build_history(history, user_message, tool_trace, _MAX_STEPS_ANSWER)
    return {
        "answer":     _MAX_STEPS_ANSWER,
        "tool_trace": tool_trace,
        "proposal":   proposal,
        "history":    updated_history,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _serialise_result(result: dict) -> str:
    """Convert a tool result dict to a JSON string for the tool message."""
    import json
    return json.dumps(result, default=str)


def _build_history(
    prior_history: list[dict] | None,
    user_message: str,
    tool_trace: list[dict],
    answer: str,
) -> list[dict]:
    """Assemble the updated history for the next turn.

    History contains only role/content messages (no tool_calls internals)
    so it can be safely stored and reused.
    """
    history = list(prior_history or [])
    history.append({"role": "user", "content": user_message})
    for entry in tool_trace:
        history.append({
            "role":    "assistant",
            "content": f"[tool call: {entry['name']}({entry['args']})]",
        })
        history.append({
            "role":    "tool",
            "content": _serialise_result(entry["result"]),
        })
    history.append({"role": "assistant", "content": answer})
    return history
