"""Build example run_agent() results for UI development without an API key.

The UI developer needs to see what ``run_agent()`` returns, but only the key
holder can call watsonx.ai.  This script replays a saved question sweep
(real Llama 3.3 runs in ``eval_results/sweep_*.json``) through the real agent
loop with a scripted LLM:

* the tool calls are the ones the real model made, so the engine results and
  the code-built ``view`` are exactly what the real run produced;
* the answer text is the real model's answer from the sweep file.

Each replayed turn is checked against the saved run (same view type, same
table, same deterministic markdown).  The script stops with an error if a
check fails, so the fixtures never drift silently from the code.

Run from the repository root (no .env needed):

    python -m scripts.make_ui_fixtures
    python -m scripts.make_ui_fixtures eval_results/sweep_20261112_020142.json

Output: ``ui_fixtures/agent_results.json``.  See ``docs/ui-contract.md``.
"""

from __future__ import annotations

import json
import re
import sys
from itertools import groupby
from pathlib import Path

from agent.fake_llm import ScriptedLLM
from agent.loop import run_agent

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SWEEP = ROOT / "eval_results" / "sweep_20261112_020142.json"
OUT = ROOT / "ui_fixtures" / "agent_results.json"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _FailingLLM:
    """Stands in for watsonx.ai being unreachable."""

    def chat(self, messages, tools):
        raise ConnectionError("watsonx.ai unreachable (fixture)")


def _script_for(entry: dict) -> list[dict]:
    script = []
    if entry["tools"]:
        script.append({"tool_calls": [
            {"id": f"c{i}", "name": t["name"], "args": t["args"]}
            for i, t in enumerate(entry["tools"], 1)
        ]})
    script.append({"content": ""})              # ends the gather phase
    # For world_risk entries the LLM narrative call uses the saved real text.
    script.append({"content": entry.get("llm_text", "(replayed)")})
    return script


def _check(entry: dict, result: dict) -> None:
    """Fail loudly if the replay differs from the saved real run."""
    q = entry["question"]
    view = result.get("view")
    got_type = view["type"] if view else None
    if got_type != entry["view_type"]:
        # Print so the message is visible in test output, then raise so
        # unittest records an error without calling SystemExit (which would
        # kill the entire test process).
        print(f"{q!r}: view type {got_type} != saved {entry['view_type']}")
        raise AssertionError(f"{q!r}: view type {got_type} != saved {entry['view_type']}")
    saved = entry["answer"]
    if got_type in ("recommendation", "comparison"):
        if view["table_markdown"] not in saved:
            raise AssertionError(f"{q!r}: options table differs from the saved run")
    elif got_type is not None:
        if _UUID.sub("<id>", view["markdown"]) != _UUID.sub("<id>", saved):
            raise AssertionError(f"{q!r}: {got_type} markdown differs from the saved run")
    if (result["proposal"] is not None) != entry["proposal_created"]:
        raise AssertionError(f"{q!r}: proposal created does not match the saved run")


def _public(result: dict) -> dict:
    """Keep what the UI uses.  ``history`` is left out to keep the file small."""
    return {k: v for k, v in result.items() if k != "history"}


def build(sweep_path: Path) -> list[dict]:
    entries = json.loads(sweep_path.read_text(encoding="utf-8"))
    fixtures = []
    for conv, turns in groupby(entries, key=lambda e: e["conversation"]):
        history = None
        for n, entry in enumerate(turns, 1):
            result = run_agent(entry["question"], history,
                               llm=ScriptedLLM(_script_for(entry)))
            _check(entry, result)
            view = result.get("view")
            if view is None or view["type"] in ("recommendation", "comparison"):
                # The prose comes from the real model run.
                result["answer"] = entry["answer"]
                if view is not None:
                    view["markdown"] = entry["answer"]
                result["history"][-1]["content"] = entry["answer"]
            history = result["history"]
            fixtures.append({
                "conversation": conv,
                "turn": n,
                "question": entry["question"],
                "model": entry["model"],
                "result": _public(result),
            })

    q = "Our budget is 500 dollars. What should we do?"
    fixtures.append({
        "conversation": "error",
        "turn": 1,
        "question": q,
        "model": "none (watsonx.ai unreachable)",
        "result": _public(run_agent(q, None, llm=_FailingLLM())),
    })
    return fixtures


def main() -> None:
    sweep = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SWEEP
    try:
        fixtures = build(sweep)
    except AssertionError as exc:
        raise SystemExit(str(exc)) from exc
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixtures, indent=1, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8")
    types = [f["result"].get("view", {}) or {} for f in fixtures]
    print(f"Wrote {len(fixtures)} results to {OUT.relative_to(ROOT)}")
    print("view types:", sorted({(t.get("type") or "none (free text)") for t in types}))


if __name__ == "__main__":
    main()
