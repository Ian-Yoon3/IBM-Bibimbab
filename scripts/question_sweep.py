"""
scripts/question_sweep.py — run realistic manager questions through the real agent.

Unlike eval_agent.py, there is no pass/fail per question.  The script records
every answer so a person can read them before a demo.  It still flags two
things automatically: table values that do not match the engine, and numbers
that appear in no tool result (grounding).

Usage (needs a filled .env):
    python -m scripts.question_sweep
    python -m scripts.question_sweep ibm/granite-4-h-small

Saves eval_results/sweep_<timestamp>.json.
"""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Each entry is a list of turns in one conversation.
SWEEP = [
    ["Our budget is 500 dollars. What should we do?"],
    ["We can spend up to $800. Which option?"],
    ["What's the best option if we have $1,200 to spend?"],
    ["What is the cheapest way to keep 10 orders on time?"],
    ["How can we keep all 12 orders on time, and what does it cost?"],
    ["Which option has the shortest maximum delay?"],
    ["How bad is this disruption?"],
    ["Which customers are hurt the most if we wait?"],
    ["Is it worth paying $1,306 for HYBRID?"],
    ["Why is SO05 late if we only move stock?"],
    ["What happens to SO11 under HYBRID?"],
    ["What if the supplier is 3 days late instead?"],
    ["The supplier says it will arrive 2 days earlier. What changes?"],
    ["Compare TRANSFER and ALT_BUY for priority customers."],
    ["I'd like to approve nothing yet, just compare options."],
    ["What does HYBRID actually involve?"],
    ["Let's go with TRANSFER."],
    ["What should we do if money is no object?", "Propose that."],
    ["Our budget is 1,000 dollars. What should we do?",
     "Why is SO06 still late with that?",
     "Go with it."],
]

_DEFAULT_MODEL = "meta-llama/llama-3-3-70b-instruct"


def run_conversation(turns: list[str], llm) -> list[dict]:
    from agent.loop import run_agent
    from scripts.eval_agent import check_grounding, check_table

    history, out = None, []
    for text in turns:
        r = run_agent(text, history=history, llm=llm)
        history = r["history"]
        r["question"] = text
        out.append({
            "question": text,
            "view_type": (r.get("view") or {}).get("type"),
            "tools": [{"name": t["name"], "args": t["args"],
                       "error": (t["result"] or {}).get("error")
                       if isinstance(t["result"], dict) else None}
                      for t in r["tool_trace"]],
            "proposal_created": r["proposal"] is not None,
            "table_mismatches": check_table(r["answer"]),
            "ungrounded": check_grounding({**r, "earlier_tools": []}),
            "error": r.get("error"),
            "answer": r["answer"],
        })
    return out


def main() -> None:
    load_dotenv()
    model_id = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_MODEL
    from agent.llm import WatsonxLLM
    llm = WatsonxLLM(model_id=model_id)

    results = []
    for i, turns in enumerate(SWEEP, 1):
        print(f"[{i}/{len(SWEEP)}] {' / '.join(turns)}")
        for t in run_conversation(turns, llm):
            flags = []
            if t["table_mismatches"]:
                flags.append(f"TABLE {t['table_mismatches'][:2]}")
            if t["ungrounded"]:
                flags.append(f"UNGROUNDED {t['ungrounded'][:5]}")
            if t["error"]:
                flags.append("LLM ERROR")
            tools = ", ".join(x["name"] for x in t["tools"]) or "(none)"
            print(f"    -> view={t['view_type']}  proposal={t['proposal_created']}  "
                  f"tools={tools}  {' '.join(flags) or 'ok'}")
            results.append({"conversation": i, "model": model_id, **t})

    os.makedirs("eval_results", exist_ok=True)
    path = os.path.join("eval_results",
                        f"sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    flagged = sum(1 for r in results if r["table_mismatches"] or r["ungrounded"] or r["error"])
    print(f"\n{len(results)} answers, {flagged} flagged. Saved -> {path}")


if __name__ == "__main__":
    main()
