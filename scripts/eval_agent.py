"""
scripts/eval_agent.py — Golden-question evaluation for the NovaTech agent.

Run manually (requires a filled .env):
    python scripts/eval_agent.py
    python scripts/eval_agent.py ibm/granite-4-h-small
    python scripts/eval_agent.py meta-llama/llama-3-3-70b-instruct
    python scripts/eval_agent.py --full          # also print full answers

Prints a pass/fail table for all golden questions × both models.
Saves full results to eval_results/<timestamp>.json.

# ── EVAL CRITERIA ─────────────────────────────────────────────────────────────
#
# Normalisation (applied before all string comparisons):
#   - Lowercase
#   - Unicode hyphens/dashes (U+2010–U+2015, U+2212) → "-"
#   - Non-breaking spaces → space
#   - Strip "$" and strip "," between digits
#
# Q1  "Our budget is 500 dollars. What should we do?"
#       expected_tool: compare_scenarios
#       expected_fact: "TRANSFER"
#       format_check: all 5 recommendation headings present
#
# Q2  "How bad is this disruption?"
#       expected_tool: get_impact
#       expected_fact: "SO02"
#       format_check: "Evidence" heading present
#
# Q3  "With HYBRID, are all priority-1 orders on time?"
#       expected_tool: get_priority_view
#       expected_fact: one of "5 of 6", "5/6", "five of six", "5 out of 6"
#       fail also if answer says "all priority-1 ... on time" without "not"
#
# Q4  "Is there a cheaper way than HYBRID to keep 11 orders on time?"
#       expected_tool: explore_purchase_qty
#       expected_fact: "1216"
#       format_check: all 5 recommendation headings present
#
# Q5  "What if the delay becomes 8 days?"
#       allowed tools: get_disruption, compare_scenarios
#       forbidden tools: explore_purchase_qty, propose_action
#       pass: forbidden not called AND answer mentions 6-day delay AND
#             says hypothetical delays not supported AND no "contact"
#
# Q6  "Approve HYBRID now."
#       expected_tool: propose_action
#       pass: proposal.status == "pending_approval" AND answer mentions
#             "pending" or "approval"
#
# ── GOLDEN QUESTIONS ─────────────────────────────────────────────────────────
"""

import json
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv


_RECOMMENDATION_HEADINGS = [
    "situation",
    "options compared",
    "recommendation",
    "trade-offs and risks",
    "next step",
]

GOLDEN_QUESTIONS = [
    {
        "id": "Q1",
        "q": "Our budget is 500 dollars. What should we do?",
        "expected_tool": "compare_scenarios",
        "expected_fact": "TRANSFER",
        "format_headings": _RECOMMENDATION_HEADINGS,
    },
    {
        "id": "Q2",
        "q": "How bad is this disruption?",
        "expected_tool": "get_impact",
        "expected_fact": "SO02",
        "format_headings": ["evidence"],
    },
    {
        "id": "Q3",
        "q": "With HYBRID, are all priority-1 orders on time?",
        "expected_tool": "get_priority_view",
        "expected_fact_patterns": [
            "5 of 6", "5/6", "five of six", "5 out of 6", "5 of the 6",
        ],
        "q3_checks": True,
    },
    {
        "id": "Q4",
        "q": "Is there a cheaper way than HYBRID to keep 11 orders on time?",
        "expected_tool": "explore_purchase_qty",
        "expected_fact": "1216",
        "extra_facts": ["40"],   # must also contain the qty
        "format_headings": _RECOMMENDATION_HEADINGS,
    },
    {
        "id": "Q5",
        "q": "What if the delay becomes 8 days?",
        "expected_tool": None,
        "forbidden_tools": ["explore_purchase_qty", "propose_action"],
        "q5_checks": True,
    },
    {
        "id": "Q6",
        "q": "Approve HYBRID now.",
        "expected_tool": "propose_action",
        "q6_checks": True,
    },
]

_MODELS = [
    "ibm/granite-4-h-small",
    "meta-llama/llama-3-3-70b-instruct",
]

# Unicode hyphens/dashes: U+2010–U+2015 and U+2212 (minus sign)
_UNICODE_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

# Thin/narrow no-break spaces that may appear inside formatted numbers
_THIN_SPACES = "\u2009\u202f\u00a0"


# Known ID prefixes (case-insensitive; lowercased after normalise lowercases).
# Only use prefixes that are NEVER standalone English words (so, cu, wh, ln, po).
# Exclude: of ("of 12" is a valid phrase), d, c, s (single letters, too ambiguous).
# Require 2+ digits so "so 1" doesn't match, only "so 01", "so 02", etc.
_ID_PREFIXES = r"(?:so|cu|wh|ln|po)"

def normalise(text: str) -> str:
    """Normalise answer text for comparison.

    Steps:
    - Lowercase
    - Replace Unicode hyphens/dashes with ASCII "-"
    - Replace thin/narrow spaces (U+2009, U+202F) between digits with ""
      ("1 216" -> "1216" when the space is thin/narrow)
    - Replace U+00A0 non-breaking space with regular space
    - Strip "$" signs
    - Strip commas between digits (e.g. "1,216" -> "1216")
    - Rejoin split IDs ONLY for known prefixes: "SO 02" -> "so02",
      "PO 01" -> "po01".  Ordinary words like "of", "the", "is" are
      never joined to a following number.
    """
    text = text.lower()
    for ch in _UNICODE_DASHES:
        text = text.replace(ch, "-")
    # Remove thin/narrow spaces when they sit between digits (number formatting)
    text = re.sub(r"(?<=\d)[\u2009\u202f](?=\d)", "", text)
    # Replace remaining thin/narrow and non-breaking spaces with regular space
    for ch in _THIN_SPACES:
        text = text.replace(ch, " ")
    text = re.sub(r"\$", "", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    # Rejoin split IDs ONLY for known prefixes, and only when followed by 2+
    # digits (IDs like so02, po01, of02 always have 2+ digits; single digits
    # like "of 6" or "s 1" are regular words and must not be joined).
    text = re.sub(r"(?<!\w)(" + _ID_PREFIXES + r") (?=\d{2,}(?!\w))", r"\1", text)
    return text


# ── grounding check ───────────────────────────────────────────────────────────

# Tokens exempt from grounding (table denominators always known from schema)
_GROUNDING_EXEMPT = {"12", "6"}

# Pattern to extract candidate tokens: numbers (incl. decimals), dates, IDs
# ID pattern: word-boundary + known short prefix + digits (avoids matching "is9999")
_TOKEN_RE = re.compile(
    r"(?<!\w)(\d{4}-\d{2}-\d{2})(?!\w)"      # ISO date
    r"|(?<!\w)([a-z]{1,4}\d{2,})(?!\w)"       # IDs like so02, d01, po01, of02, wh01, ln01
    r"|(?<!\w)(\d+(?:\.\d+)?)(?!\w)"          # plain numbers (int or decimal)
)


# UUID pattern — remove before tokenising so UUID fragments aren't flagged
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _strip_uuids(text: str) -> str:
    """Remove UUID strings from text before token extraction."""
    return _UUID_RE.sub("", text)


def _extract_tokens(text: str) -> set[str]:
    """Extract candidate fact tokens from a (normalised, UUID-free) text string."""
    text = _strip_uuids(text)
    tokens = set()
    for m in _TOKEN_RE.finditer(text.lower()):
        tok = m.group(0)
        if tok:
            tokens.add(tok)
    return tokens


def _grounding_corpus(result: dict) -> str:
    """Build the full grounding corpus from tool results + question text."""
    parts = [result.get("question", "")]
    for entry in result.get("tool_trace", []):
        # result may be stored as a string (truncated) or dict
        r = entry.get("result", {})
        if isinstance(r, str):
            parts.append(r)
        elif isinstance(r, dict):
            parts.append(json.dumps(r, default=str))
    return normalise(" ".join(parts))


def check_grounding(result: dict) -> list[str]:
    """Return a list of tokens in the answer that are not grounded in tool results.

    Tokens from _GROUNDING_EXEMPT (12, 6) and tokens present in the question
    or tool results are considered grounded.  Everything else is ungrounded.
    """
    answer_norm = normalise(result["answer"])
    corpus = _grounding_corpus(result)
    answer_tokens = _extract_tokens(answer_norm)
    corpus_tokens = _extract_tokens(corpus)
    ungrounded = []
    for tok in sorted(answer_tokens):
        if tok in _GROUNDING_EXEMPT:
            continue
        if tok in corpus_tokens:
            continue
        ungrounded.append(tok)
    return ungrounded


def _check_question(q: dict, result: dict) -> tuple[bool, str]:
    """Return (passed, reason)."""
    answer_norm = normalise(result["answer"])
    tool_names = [t["name"] for t in result["tool_trace"]]

    # any tool result containing "error" is an automatic fail
    for entry in result["tool_trace"]:
        if "error" in entry.get("result", {}):
            return False, f"tool {entry['name']!r} returned error: {entry['result']['error'][:80]}"

    # forbidden tools
    for ft in q.get("forbidden_tools", []):
        if ft in tool_names:
            return False, f"forbidden tool {ft!r} was called"

    # required tool
    if q.get("expected_tool") and q["expected_tool"] not in tool_names:
        return False, f"expected tool {q['expected_tool']!r} not called"

    # fact check (plain string)
    if q.get("expected_fact"):
        if normalise(q["expected_fact"]) not in answer_norm:
            return False, f"{q['expected_fact']!r} not found in answer"

    # extra facts (all must be present)
    for ef in q.get("extra_facts", []):
        if normalise(ef) not in answer_norm:
            return False, f"extra fact {ef!r} not found in answer"

    # fact check (pattern list)
    patterns = q.get("expected_fact_patterns")
    if patterns:
        if not any(normalise(p) in answer_norm for p in patterns):
            return False, f"none of {patterns!r} found in answer"

    # format headings
    for heading in q.get("format_headings", []):
        if heading.lower() not in answer_norm:
            return False, f"required heading {heading!r} missing from answer"

    # Q1 special: compare_scenarios must use budget=500, TRANSFER in Recommendation,
    # and propose_action must NOT be called
    if q.get("id") == "Q1":
        # check compare_scenarios was called with budget=500 (after coercion)
        cs_calls = [t for t in result["tool_trace"] if t["name"] == "compare_scenarios"]
        if not cs_calls:
            return False, "compare_scenarios was not called for Q1"
        budgets = [t["args"].get("budget") for t in cs_calls]
        if not any(b in (500, "500") for b in budgets):
            return False, f"compare_scenarios not called with budget=500 (got {budgets})"
        if "propose_action" in tool_names:
            return False, "propose_action was called during recommendation question"

    # Q3 special: also fail if answer wrongly claims all priority-1 are on time
    if q.get("q3_checks"):
        if re.search(r"all priority.1.*on time", answer_norm):
            m = re.search(r"all priority.1.*on time", answer_norm)
            context = answer_norm[max(0, m.start() - 30): m.start()]
            if "not" not in context and "n't" not in context:
                return False, "answer incorrectly claims all priority-1 orders are on time"

    # Q5 special: mentions 6-day delay, says hypothetical not supported, no "contact"
    if q.get("q5_checks"):
        if "contact" in answer_norm:
            return False, "answer tells user to contact someone"
        if "6" not in answer_norm and "six" not in answer_norm:
            return False, "answer does not mention the 6-day D01 delay"
        if not any(p in answer_norm for p in ("not supported", "hypothetical", "only d01")):
            return False, "answer does not say hypothetical delays are not supported"

    # Q6 special: proposal status AND answer mentions pending/approval
    if q.get("q6_checks"):
        p = result.get("proposal")
        if not p or p.get("status") != "pending_approval":
            return False, "proposal status is not pending_approval"
        if "pending" not in answer_norm and "approval" not in answer_norm:
            return False, "answer does not mention pending or approval"

    # Grounding check: fail if any answer token is not in tool results/question
    ungrounded = check_grounding(result)
    if ungrounded:
        return False, f"ungrounded tokens in answer: {ungrounded[:8]}"

    return True, "ok"


def eval_model(model_id: str) -> list[dict]:
    """Run all golden questions against one model. Returns full result rows.

    Each question runs in a fresh conversation (history=None).
    """
    from agent.llm import WatsonxLLM
    from agent.loop import run_agent

    llm = WatsonxLLM(model_id=model_id)
    rows = []
    for q in GOLDEN_QUESTIONS:
        result = run_agent(q["q"], history=None, llm=llm)
        # Attach question to result so check_grounding can use it
        result["question"] = q["q"]
        passed, reason = _check_question(q, result)
        ungrounded = check_grounding(result)
        tools_with_results = []
        for t in result["tool_trace"]:
            result_str = json.dumps(t["result"], default=str)
            tools_with_results.append({
                "name":   t["name"],
                "args":   t["args"],
                "result": result_str[:2000],
            })
        rows.append({
            "id":           q["id"],
            "question":     q["q"],
            "model":        model_id,
            "passed":       passed,
            "reason":       reason,
            "answer":       result["answer"],
            "ungrounded":   ungrounded,
            "tools":        tools_with_results,
        })
    return rows


def _save_results(rows: list[dict]) -> str:
    """Save full results to eval_results/<timestamp>.json. Returns file path."""
    os.makedirs("eval_results", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("eval_results", f"{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path


def _print_table(rows: list[dict], full: bool = False) -> None:
    print(f"\n{'ID':<4} {'Model':<42} {'Pass':<5} {'Tools called':<45} Reason")
    print("-" * 140)
    for r in rows:
        tool_names = ", ".join(t["name"] for t in r["tools"]) or "(none)"
        status = "✓" if r["passed"] else "✗"
        print(f"{r['id']:<4} {r['model']:<42} {status:<5} {tool_names:<45} {r['reason']}")
        if full:
            print(f"     Answer:\n{r['answer']}\n")


def main() -> None:
    load_dotenv()
    args = sys.argv[1:]
    full = "--full" in args
    model_args = [a for a in args if not a.startswith("--")]
    models = model_args if model_args else _MODELS

    all_rows = []
    for model_id in models:
        print(f"\nEvaluating {model_id} ...")
        rows = eval_model(model_id)
        all_rows.extend(rows)

    _print_table(all_rows, full=full)
    total = len(all_rows)
    passed = sum(1 for r in all_rows if r["passed"])
    print(f"\n{passed}/{total} passed")

    save_path = _save_results(all_rows)
    print(f"Results saved → {save_path}")


if __name__ == "__main__":
    main()
