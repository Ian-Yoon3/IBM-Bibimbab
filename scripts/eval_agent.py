"""
scripts/eval_agent.py — Golden-question evaluation for the NovaTech agent.

Run manually (requires a filled .env):
    python -m scripts.eval_agent
    python -m scripts.eval_agent ibm/granite-4-h-small
    python -m scripts.eval_agent meta-llama/llama-3-3-70b-instruct
    python -m scripts.eval_agent --full          # also print full answers

Usage:
    python -m scripts.eval_agent                     # default model, 1 run
    python -m scripts.eval_agent --runs 3            # stability check
    python -m scripts.eval_agent ibm/granite-4-h-small --runs 1

Prints a pass/fail table per run and, with --runs > 1, a stability summary.
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
    # ── added after eval run 5 (definition of done) ──────────────────────────
    {
        "id": "Q7",
        "q": "Our budget is 1,000 dollars. Which option should we choose?",
        "expected_tool": "compare_scenarios",
        "expected_tool_args": {"compare_scenarios": {"budget": 1000}},
        "recommend": "TRANSFER",
        "format_headings": _RECOMMENDATION_HEADINGS,
        "no_proposal": True,
    },
    {
        "id": "Q8",
        "q": "Among the four named scenarios, which one minimises the total days late across all orders?",
        "expected_tool": "compare_scenarios",
        "expected_tool_args": {"compare_scenarios": {"objective": "total_late_days"}},
        "recommend": "HYBRID",
        "no_proposal": True,
    },
    {
        "id": "Q9",
        "q": "Why is SO08 late under HYBRID?",
        "expected_tool": "get_order_detail",
        "expected_tool_args": {"get_order_detail": {"order_id": "SO08", "scenario_id": "HYBRID"}},
        "extra_facts": ["C01", "18", "2026-11-15"],
        "no_proposal": True,
    },
    {
        "id": "Q10",
        "q": "If we do nothing, why is SO03 late?",
        "expected_tool": "get_order_detail",
        "expected_tool_args": {"get_order_detail": {"order_id": "SO03"}},
        "extra_facts": ["SO02"],
        "no_proposal": True,
    },
    {
        "id": "Q11",
        "q": "For the cheapest option that keeps 11 orders on time, how many priority-1 orders are on time?",
        "expected_tool": "get_priority_view",
        "expected_tool_args": {"get_priority_view": {"offer_id": "OF02", "qty": 40}},
        "expected_fact_patterns": ["5 of 6", "5/6", "five of six", "5 out of 6", "5 of the 6"],
        "accept_bare_count": 5,
        "no_proposal": True,
    },
    {
        "id": "Q12",
        "turns": [
            "Is there a cheaper way than HYBRID to keep 11 orders on time?",
            "Propose that option.",
        ],
        "expected_tool": "propose_action",
        "proposal_metrics": {"on_time_orders": 11, "total_extra_cost": 1216},
        "q6_checks": True,
    },
    {
        "id": "Q13",
        "turns": [
            "Is there a cheaper way than HYBRID to keep 11 orders on time?",
            "With that option, why is SO08 still late?",
        ],
        "expected_tool": "get_order_detail",
        "expected_tool_args": {"get_order_detail": {"order_id": "SO08", "offer_id": "OF02", "qty": 40}},
        "extra_facts": ["C01", "23"],
        "no_proposal": True,
    },
]

# Default model per ADR 0001.  Pass a model id on the command line to
# evaluate another one, e.g. ibm/granite-4-h-small.
_MODELS = [
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
    # IDs the agent is told about in the system prompt (e.g. D01) count as known
    try:
        from engine import tools as _t
        parts.append(" ".join(_t._get_db()["disruptions"].keys()))
    except Exception:
        pass
    for entry in result.get("earlier_tools", []) + result.get("tool_trace", []):
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


# ── table check against engine ground truth ───────────────────────────────────

_TRUTH_CACHE: dict = {}


def _ground_truth() -> dict:
    """Ground truth per option, computed from the deterministic engine.

    Returns {"scenarios": {id: (on_time, prio_on_time, cost)},
             "explored": {(qty, include_transfers): (on_time, prio_on_time, cost)}}.
    Priority-1 counts for explored options come from get_priority_view with
    the same offer_id, qty and include_transfers.
    """
    if _TRUTH_CACHE:
        return _TRUTH_CACHE
    from engine import tools as _t
    scen = {}
    for r in _t.compare_scenarios()["ranked"]:
        sid = r["scenario_id"]
        prio = _t.get_priority_view(scenario_id=sid)["on_time_count"]
        scen[sid] = (r["on_time_orders"], prio, r["total_extra_cost"])
    explored = {}
    for flag in (True, False):
        for r in _t.explore_purchase_qty("OF02", include_transfers=flag)["ranked"]:
            prio = _t.get_priority_view(
                offer_id="OF02", qty=r["purchase_qty"], include_transfers=flag
            )["on_time_count"]
            explored[(r["purchase_qty"], flag)] = (
                r["on_time_orders"], prio, r["total_extra_cost"]
            )
    _TRUTH_CACHE.update({"scenarios": scen, "explored": explored})
    return _TRUTH_CACHE


def _cell_number(cell: str):
    """Return the leading int of a table cell, or None for n/a, empty or text."""
    c = cell.replace("*", "").replace("$", "").replace("USD", "")
    for ch in ",\u2009\u202f\u00a0 ":
        c = c.replace(ch, "")
    c = c.strip().lower()
    if c in ("", "n/a", "na", "-", "\u2013", "\u2014"):
        return None
    # Use the leading number ("8", "8of12", "1216usd").  A cell that does not
    # start with a number (e.g. "not viable") is treated as non-numeric.
    m = re.match(r"(\d+)", c)
    return int(m.group(1)) if m else None


def _identify_option(cell: str):
    """Map an option cell to ("explored", (qty, transfers)) or ("scenario", id)."""
    low = cell.lower()
    m = re.search(r"buy\s*(\d+)", low)
    if m:
        return "explored", (int(m.group(1)), "transfer" in low)
    for sid in ("ALT_BUY", "HYBRID", "TRANSFER", "WAIT"):
        if sid.lower().replace("_", "") in low.replace("_", "").replace(" ", "").replace("-", ""):
            return "scenario", sid
    return None, None


def check_table(answer: str) -> list[str]:
    """Compare the "Options compared" table with the engine ground truth.

    Returns a list of mismatch descriptions; empty means the table is
    consistent (or there is no table).  Columns are assumed in the order
    Option | On-time orders | Priority-1 on time | Extra cost USD.
    """
    truth = _ground_truth()
    lines = answer.splitlines()
    try:
        start = next(i for i, l in enumerate(lines)
                     if "options compared" in l.lower())
    except StopIteration:
        return []
    mismatches = []
    labels = ("on-time orders", "priority-1 on time", "extra cost")
    for line in lines[start + 1:]:
        if line.strip().startswith("#"):
            break
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue
        kind, key = _identify_option(cells[0])
        if kind == "scenario":
            expected = truth["scenarios"].get(key)
        elif kind == "explored":
            expected = truth["explored"].get(key)
        else:
            continue
        if expected is None:
            mismatches.append(f"{cells[0]}: unknown option")
            continue
        for label, cell, exp in zip(labels, cells[1:4], expected):
            got = _cell_number(cell)
            if got is None:
                continue
            if exp is None or got != exp:
                mismatches.append(f"{cells[0]} {label} {got!r} != {exp!r}")
    return mismatches


def _check_question(q: dict, result: dict) -> tuple[bool, str]:
    """Return (passed, reason)."""
    answer_norm = normalise(result["answer"])
    tool_names = [t["name"] for t in result["tool_trace"]]

    # Tool errors are recorded (see tool_errors in the saved JSON) but do not
    # fail a question on their own.  A blocked call means the guard worked.
    # Correctness is judged from the answer: facts, table values, grounding.

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
        found = any(normalise(p) in answer_norm for p in patterns)
        # Q3 alternative: "not all" plus the on-time count 5 stated separately
        if not found and q.get("q3_checks"):
            found = "not all" in answer_norm and re.search(r"\b5\b", answer_norm)
        # Count questions: the bare count next to "priority" is enough
        if not found and q.get("accept_bare_count"):
            n = q["accept_bare_count"]
            found = ("priority" in answer_norm
                     and re.search(rf"\b{n}\b[^.\n]*on.time|on.time[^.\n]*\b{n}\b", answer_norm))
        if not found:
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
        if result.get("proposal") is not None:
            return False, "a proposal was created during a recommendation question"

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
        if not any(p in answer_norm for p in ("not supported", "cannot be simulated", "only d01")):
            return False, "answer does not say hypothetical delays are not supported"

    # Q6 special: proposal status AND answer mentions pending/approval
    if q.get("q6_checks"):
        p = result.get("proposal")
        if not p or p.get("status") != "pending_approval":
            return False, "proposal status is not pending_approval"
        if "pending" not in answer_norm and "approval" not in answer_norm:
            return False, "answer does not mention pending or approval"

    # Tool arguments: at least one call of the tool must match every given arg
    for tool, want in q.get("expected_tool_args", {}).items():
        calls = [t["args"] or {} for t in result["tool_trace"] if t["name"] == tool]
        def _match(a):
            return all(str(a.get(k)).strip().lower() == str(v).lower() for k, v in want.items())
        if not any(_match(a) for a in calls):
            return False, f"{tool} not called with {want} (got {calls})"

    # Recommendation section must name the expected option
    if q.get("recommend"):
        m = re.search(r"recommendation(.*?)(?:\n#|$)", answer_norm, re.S)
        section = m.group(1) if m else answer_norm
        if q["recommend"].lower() not in section:
            return False, f"recommendation does not name {q['recommend']}"

    # Questions that must not create a proposal
    if q.get("no_proposal") and result.get("proposal") is not None:
        return False, "a proposal was created although the user did not ask to act"

    # Proposal metrics (multi-turn follow-up)
    for k, v in q.get("proposal_metrics", {}).items():
        p = result.get("proposal") or {}
        got = (p.get("metrics") or {}).get(k)
        if got != v:
            return False, f"proposal {k} is {got!r}, expected {v!r}"

    # Table check: every number in the "Options compared" table must match the
    # engine's ground truth for that option and column ("n/a" is allowed).
    mismatches = check_table(result["answer"])
    if mismatches:
        return False, f"table mismatch: {mismatches[:3]}"

    # Grounding check: fail if any answer token is not in tool results/question
    ungrounded = check_grounding(result)
    if ungrounded:
        return False, f"ungrounded tokens in answer: {ungrounded[:8]}"

    return True, "ok"


def _run_question(q: dict, llm) -> dict:
    """Run one golden question in a fresh conversation.

    Multi-turn questions ("turns") run in order with shared history.  The
    checks apply to the final turn.  Earlier turns' tool calls are kept in
    ``earlier_tools`` for the record, and the grounding corpus includes them
    because the final answer may cite numbers from earlier turns.
    """
    from agent.loop import run_agent

    turns = q.get("turns") or [q["q"]]
    history, earlier, result = None, [], None
    for i, text in enumerate(turns):
        result = run_agent(text, history=history, llm=llm)
        history = result["history"]
        if i < len(turns) - 1:
            earlier.extend(result["tool_trace"])
    result["question"] = " / ".join(turns)
    result["earlier_tools"] = earlier
    return result


def eval_model(model_id: str, run_index: int = 1) -> list[dict]:
    """Run all golden questions against one model. Returns full result rows.

    Each question runs in a fresh conversation (history=None).
    """
    from agent.llm import WatsonxLLM

    llm = WatsonxLLM(model_id=model_id)
    rows = []
    for q in GOLDEN_QUESTIONS:
        if _ONLY and q["id"] not in _ONLY:
            continue
        result = _run_question(q, llm)
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
            "run":          run_index,
            "question":     result["question"],
            "model":        model_id,
            "passed":       passed,
            "reason":       reason,
            "answer":       result["answer"],
            "ungrounded":   ungrounded,
            "tool_errors":  [
                {"name": t["name"], "error": t["result"]["error"]}
                for t in result["tool_trace"]
                if isinstance(t["result"], dict) and "error" in t["result"]
            ],
            "table_mismatches": check_table(result["answer"]),
            "tools":        tools_with_results,
            "earlier_tools": [
                {"name": t["name"], "args": t["args"]} for t in result["earlier_tools"]
            ],
            "error":        result.get("error"),
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


_ONLY: set[str] = set()   # question ids selected with --only (empty = all)


def _parse_args(argv: list[str]) -> tuple[list[str], int, bool]:
    """Return (models, runs, full).

    Usage: [model_id ...] [--runs N] [--only Q5,Q13] [--full].
    --only sets the module-level _ONLY filter used by eval_model.
    """
    full = "--full" in argv
    runs = 1
    models = []
    _ONLY.clear()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--runs", "--only") and i + 1 < len(argv):
            if a == "--runs":
                runs = int(argv[i + 1])
            else:
                _ONLY.update(x.strip().upper() for x in argv[i + 1].split(","))
            i += 2
            continue
        if a.startswith("--runs="):
            runs = int(a.split("=", 1)[1])
        elif a.startswith("--only="):
            _ONLY.update(x.strip().upper() for x in a.split("=", 1)[1].split(","))
        elif not a.startswith("--"):
            models.append(a)
        i += 1
    return (models or list(_MODELS)), max(1, runs), full


def _print_stability(all_rows: list[dict], runs: int) -> int:
    """Print per-question pass counts across runs.  Returns stable-pass count."""
    print(f"\nStability over {runs} run(s): a question is stable only if it passed every run")
    stable = 0
    keys = sorted({(r["model"], r["id"]) for r in all_rows},
                  key=lambda k: (k[0], int(k[1][1:])))
    for model, qid in keys:
        rs = [r for r in all_rows if r["model"] == model and r["id"] == qid]
        n = sum(r["passed"] for r in rs)
        ok = n == len(rs)
        stable += ok
        print(f"  {qid:<4} {model:<42} {n}/{len(rs)} {'STABLE' if ok else 'UNSTABLE'}")
    print(f"\n{stable}/{len(keys)} questions stable")
    return stable


def main() -> None:
    load_dotenv()
    models, runs, full = _parse_args(sys.argv[1:])

    all_rows = []
    for run in range(1, runs + 1):
        for model_id in models:
            print(f"\nRun {run}/{runs}: evaluating {model_id} ...")
            rows = eval_model(model_id, run_index=run)
            all_rows.extend(rows)
            _print_table(rows, full=full)
            passed = sum(1 for r in rows if r["passed"])
            print(f"\nRun {run}: {passed}/{len(rows)} passed")

    if runs > 1:
        _print_stability(all_rows, runs)

    save_path = _save_results(all_rows)
    print(f"Results saved → {save_path}")


if __name__ == "__main__":
    main()
