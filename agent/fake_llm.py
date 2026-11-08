"""ScriptedLLM — deterministic fake LLM for agent tests.

Usage::

    from agent.fake_llm import ScriptedLLM

    llm = ScriptedLLM([
        # turn 1: model calls a tool
        {"tool_calls": [{"id": "c1", "name": "get_disruption", "args": {"disruption_id": "D01"}}]},
        # turn 2: model returns a text answer
        {"content": "The disruption delays PO01 by 6 days."},
    ])

    msg = llm.chat(messages, tools)   # -> turn 1 (tool_calls)
    msg = llm.chat(messages, tools)   # -> turn 2 (content)

Each entry in ``script`` must be a dict with the same shape as the
normalised message returned by ``WatsonxLLM.chat()``:

    {"content": str | None, "tool_calls": [...]}

For convenience, entries may omit the ``content`` or ``tool_calls`` key;
missing keys are filled with ``None`` / ``[]`` respectively.
"""


class ScriptedLLM:
    """Replay a pre-scripted sequence of normalised responses.

    Parameters
    ----------
    script:
        Ordered list of response dicts.  Each dict may contain:
          - ``"content"`` (str | None)
          - ``"tool_calls"`` (list of {"id", "name", "args"} dicts)
        Missing keys default to ``None`` / ``[]``.

    Raises
    ------
    AssertionError
        If ``.chat()`` is called more times than there are scripted turns.
    """

    def __init__(self, script: list[dict]):
        self._script = script
        self._index = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return the next scripted response.

        Parameters
        ----------
        messages:
            Ignored — provided for interface compatibility with WatsonxLLM.
        tools:
            Ignored — provided for interface compatibility with WatsonxLLM.
        """
        assert self._index < len(self._script), (
            f"ScriptedLLM exhausted after {len(self._script)} turns "
            f"(called {self._index + 1} times)"
        )
        raw = self._script[self._index]
        self._index += 1
        return {
            "content": raw.get("content"),
            "tool_calls": raw.get("tool_calls", []),
        }

    @property
    def calls_remaining(self) -> int:
        """Number of scripted turns not yet consumed."""
        return len(self._script) - self._index
