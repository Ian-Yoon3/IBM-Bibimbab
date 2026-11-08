"""
scripts/eval_agent.py — Golden-question evaluation for the NovaTech agent.

Run manually (requires a filled .env):
    python scripts/eval_agent.py
    python scripts/eval_agent.py ibm/granite-4-h-small
    python scripts/eval_agent.py meta-llama/llama-3-3-70b-instruct

Prints a pass/fail table for all golden questions × both models.

# ── EVAL CRITERIA (step 8 implementation notes) ──────────────────────────────
#
# General normalisation before checking expected_fact:
#   - Strip commas from numbers before comparing  (e.g. "1,216" -> "1216")
#   - Strip "$" and "%" before comparing numeric facts
#
# Q1  "Our budget is 500 dollars. What should we do?"
#       expected_tool: compare_scenarios
#       expected_fact: "TRANSFER" (case-insensitive substring in answer)
#       pass: compare_scenarios was called AND answer mentions TRANSFER
#
# Q2  "How bad is this disruption?"
#       expected_tool: get_impact
#       expected_fact: "SO02" (first late order, case-insensitive)
#       pass: get_impact was called AND "SO02" in answer
#
# Q3  "With HYBRID, are all priority-1 orders on time?"
#       expected_tool: get_priority_view
#       expected_fact: one of "5 of 6", "5/6", "five of six" (case-insensitive)
#       pass: get_priority_view was called AND any of the three patterns found
#
# Q4  "Is there a cheaper way than HYBRID to keep 11 orders on time?"
#       expected_tool: explore_purchase_qty
#       expected_fact: "1216" (after stripping commas and "$")
#       pass: explore_purchase_qty was called AND "1216" in normalised answer
#
# Q5  "What if the delay becomes 8 days?"
#       expected_tool: None  (neither compare_scenarios nor explore_purchase_qty)
#       expected_fact: "not supported" OR "only D01" (case-insensitive)
#       pass: NEITHER compare_scenarios NOR explore_purchase_qty called,
#             AND at least one of the expected_fact patterns appears in answer
#
# Q6  "Approve HYBRID now."
#       expected_tool: propose_action
#       expected_fact: "pending" (status must be pending_approval, not approved)
#       pass: propose_action was called AND result["proposal"]["status"] == "pending_approval"
#             AND nothing in the answer implies approval was granted
#
# ── GOLDEN QUESTIONS ─────────────────────────────────────────────────────────
"""

import os
import re
import sys

from dotenv import load_dotenv


GOLDEN_QUESTIONS = [
    {
        "id": "Q1",
        "q": "Our budget is 500 dollars. What should we do?",
        "expected_tool": "compare_scenarios",
        "expected_fact": "TRANSFER",
        # check: tool called AND "TRANSFER" (case-insensitive) in answer
    },
    {
        "id": "Q2",
        "q": "How bad is this disruption?",
        "expected_tool": "get_impact",
        "expected_fact": "SO02",
        # check: tool called AND "SO02" in answer
    },
    {
        "id": "Q3",
        "q": "With HYBRID, are all priority-1 orders on time?",
        "expected_tool": "get_priority_view",
        # check: tool called AND any of: "5 of 6", "5/6", "five of six" in answer
        "expected_fact_patterns": ["5 of 6", "5/6", "five of six"],
    },
    {
        "id": "Q4",
        "q": "Is there a cheaper way than HYBRID to keep 11 orders on time?",
        "expected_tool": "explore_purchase_qty",
        "expected_fact": "1216",
        # check: tool called AND "1216" in answer (after stripping commas and $)
    },
    {
        "id": "Q5",
        "q": "What if the delay becomes 8 days?",
        "expected_tool": None,  # must NOT call compare_scenarios or explore_purchase_qty
        # check: neither compare_scenarios nor explore_purchase_qty called
        #        AND ("not supported" OR "only D01") in answer (case-insensitive)
        "expected_fact_patterns": ["not supported", "only d01"],
        "forbidden_tools": ["compare_scenarios", "explore_purchase_qty"],
    },
    {
        "id": "Q6",
        "q": "Approve HYBRID now.",
        "expected_tool": "propose_action",
        "expected_fact": "pending",
        # check: propose_action called AND proposal.status == "pending_approval"
        #        AND answer does not say approval was granted
    },
]

_MODELS = [
    "ibm/granite-4-h-small",
    "meta-llama/llama-3-3-70b-instruct",
]


def _normalise(text: str) -> str:
    """Strip commas and dollar signs from numbers for comparison."""
    text = re.sub(r"\$", "", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return text.lower()


def _check_question(q: dict, result: dict) -> tuple[bool, str]:
    """Return (passed, reason)."""
    answer_norm = _normalise(result["answer"])
    tool_names = [t["name"] for t in result["tool_trace"]]

    # forbidden tools
    for ft in q.get("forbidden_tools", []):
        if ft in tool_names:
            return False, f"forbidden tool {ft!r} was called"

    # required tool
    if q.get("expected_tool") and q["expected_tool"] not in tool_names:
        return False, f"expected tool {q['expected_tool']!r} not called"

    # Q6: proposal status
    if q.get("id") == "Q6":
        p = result.get("proposal")
        if not p or p.get("status") != "pending_approval":
            return False, "proposal status is not pending_approval"

    # fact check
    patterns = q.get("expected_fact_patterns")
    if patterns:
        if not any(_normalise(p) in answer_norm for p in patterns):
            return False, f"none of {patterns!r} found in answer"
    elif q.get("expected_fact"):
        if _normalise(q["expected_fact"]) not in answer_norm:
            return False, f"{q['expected_fact']!r} not found in answer"

    return True, "ok"


def eval_model(model_id: str) -> list[dict]:
    """Run all golden questions against one model."""
    from agent.llm import WatsonxLLM
    from agent.loop import run_agent

    llm = WatsonxLLM(model_id=model_id)
    rows = []
    history = None
    for q in GOLDEN_QUESTIONS:
        result = run_agent(q["q"], history=history, llm=llm)
        passed, reason = _check_question(q, result)
        rows.append({
            "id":       q["id"],
            "model":    model_id,
            "passed":   passed,
            "reason":   reason,
            "answer":   result["answer"][:120],
            "tools":    [t["name"] for t in result["tool_trace"]],
        })
        history = result["history"]  # accumulate history across questions
    return rows


def _print_table(rows: list[dict]) -> None:
    print(f"\n{'ID':<4} {'Model':<42} {'Pass':<5} {'Tools called':<40} Reason / Answer snippet")
    print("-" * 130)
    for r in rows:
        tools = ", ".join(r["tools"]) or "(none)"
        status = "✓" if r["passed"] else "✗"
        snippet = r["answer"].replace("\n", " ")
        print(f"{r['id']:<4} {r['model']:<42} {status:<5} {tools:<40} {r['reason']} | {snippet}")


def main() -> None:
    load_dotenv()
    models = sys.argv[1:] if len(sys.argv) > 1 else _MODELS
    all_rows = []
    for model_id in models:
        print(f"\nEvaluating {model_id} ...")
        rows = eval_model(model_id)
        all_rows.extend(rows)
    _print_table(all_rows)
    total = len(all_rows)
    passed = sum(1 for r in all_rows if r["passed"])
    print(f"\n{passed}/{total} passed")


if __name__ == "__main__":
    main()
