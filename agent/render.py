"""Deterministic answer views.

The engine decides the numbers.  This module decides how they are shown, so
the manager sees the same layout every time.  The LLM only writes the short
reasoning inside a recommendation (see ``agent/loop.py``).

Views
-----
recommendation  situation, options table with a ★, recommendation, trade-offs, next step
order           why one order is late (engine summary + evidence)
proposal        what was proposed, its metrics and actions, pending approval
unsupported     scope note + the recorded options, no recommendation

Every view is returned as a dict with a ``markdown`` field and structured
fields that a UI can render directly.  Only ``engine/tools.py`` is used.
"""

import re
from datetime import date

import engine.tools as _t

# ── small helpers ─────────────────────────────────────────────────────────────

_NAMED = ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID")

_OBJECTIVE_TEXT = {
    "on_time_orders": "most on-time orders",
    "on_time_units": "most on-time units",
    "total_late_days": "fewest total days late",
    "max_delay": "shortest maximum delay",
    "cost": "lowest extra cost",
}


def _day(iso: str) -> str:
    """'2026-11-17' -> 'Nov 17'."""
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def _money(x) -> str:
    return f"${x:,}"


def _catalog() -> dict:
    return _t.get_catalog()


# ── option names ──────────────────────────────────────────────────────────────

def option_name(actions: list, cat: dict) -> str:
    """Plain-English name of an action list, e.g. 'Move stock + buy 45 from Beacon Circuits'."""
    buys = [a for a in actions if a["type"] == "purchase"]
    moves = [a for a in actions if a["type"] == "transfer"]
    if not buys and not moves:
        return "Wait for the delayed delivery"
    parts = []
    if moves:
        if buys:
            parts.append("Move stock")
        else:
            srcs = [cat["warehouses"][cat["lanes"][a["lane_id"]]["from"]] for a in moves]
            parts.append("Move stock from " + " and ".join(srcs))
    for b in buys:
        supplier = cat["suppliers"][cat["offers"][b["offer_id"]]["supplier_id"]]
        verb = "buy" if moves else "Buy"
        parts.append(f"{verb} {b['qty']} from {supplier}")
    return " + ".join(parts)


def option_code(scenario_id=None, offer_id=None, qty=None, include_transfers=False) -> str:
    """Short code the user can say back to the agent, e.g. 'TRANSFER' or 'OF02 x40 + transfers'."""
    if scenario_id:
        return scenario_id
    return f"{offer_id} x{qty}" + (" + transfers" if include_transfers else "")


# ── option rows ───────────────────────────────────────────────────────────────

def _row(cat, actions, *, scenario_id=None, offer_id=None, qty=None,
         include_transfers=False, found_by_search=False) -> dict:
    """Simulate one option and return a table row (all numbers from the engine)."""
    disruption_id = next(iter(cat.get("_disruptions", ["D01"])))
    sim = _t.run_scenario(actions, disruption_id)
    if scenario_id:
        prio = _t.get_priority_view(scenario_id=scenario_id)
    else:
        prio = _t.get_priority_view(offer_id=offer_id, qty=qty,
                                    include_transfers=include_transfers)
    late = [r for r in sim["order_results"] if r["days_late"] > 0]
    name = option_name(actions, cat)
    return {
        "code": option_code(scenario_id, offer_id, qty, include_transfers),
        "scenario_id": scenario_id,
        "offer_id": offer_id,
        "qty": qty,
        "include_transfers": include_transfers,
        "name": name,
        "found_by_search": found_by_search,
        "on_time_orders": sim["on_time_orders"],
        "total_orders": len(sim["order_results"]),
        "priority_on_time": prio["on_time_count"],
        "priority_total": prio["total_count"],
        "total_days_late": sim["total_order_days_late"],
        "extra_cost": sim["total_extra_cost"],
        "late_orders": [
            {"order_id": r["order_id"], "days_late": r["days_late"],
             "priority_rank": cat["orders"][r["order_id"]]["priority_rank"]}
            for r in late
        ],
    }


def _named_rows(cat) -> list[dict]:
    rows = []
    for sid in _NAMED:
        actions = _t.get_scenario_actions(sid)["actions"]
        rows.append(_row(cat, actions, scenario_id=sid))
    return rows


def _searched_rows(cat, named: list[dict], disruption_id: str) -> list[dict]:
    """Options found by search that beat at least one named option.

    An explored option is kept when no other option (named or explored) has
    at least as many on-time orders for no more money, and it is not the same
    as a named option.  This keeps the table short: only real improvements.
    """
    offers = [o for o in _t.get_offers(disruption_id)["offers"]
              if not o["is_disrupted_supplier"]]
    cands = []
    for o in offers:
        for flag in (True, False):
            for r in _t.explore_purchase_qty(o["offer_id"], include_transfers=flag)["ranked"]:
                cands.append((o["offer_id"], r["purchase_qty"], flag,
                              r["on_time_orders"], r["total_extra_cost"], r["actions"]))
    pool = [(n["on_time_orders"], n["extra_cost"]) for n in named] + [(c[3], c[4]) for c in cands]

    def dominated(ot, cost):
        return any((o2 >= ot and c2 <= cost) and (o2 > ot or c2 < cost) for o2, c2 in pool)

    named_points = {(n["on_time_orders"], n["extra_cost"]) for n in named}
    keep, seen = [], set()
    for off, qty, flag, ot, cost, actions in sorted(cands, key=lambda c: (c[4], -c[3])):
        if dominated(ot, cost) or (ot, cost) in named_points or (ot, cost) in seen:
            continue
        seen.add((ot, cost))
        keep.append(_row(cat, actions, offer_id=off, qty=qty,
                         include_transfers=flag, found_by_search=True))
    return keep


# ── choosing the ★ ────────────────────────────────────────────────────────────

def choose_recommended(rows, objective="on_time_orders", budget=None, min_on_time=None):
    """Return the code of the best row for the objective, or None if nothing qualifies."""
    ok = [r for r in rows
          if (budget is None or r["extra_cost"] <= budget)
          and (min_on_time is None or r["on_time_orders"] >= min_on_time)]
    if not ok:
        return None
    keys = {
        "on_time_orders": lambda r: (-r["on_time_orders"], r["extra_cost"]),
        "on_time_units": lambda r: (-r["on_time_orders"], r["extra_cost"]),
        "cost": lambda r: (r["extra_cost"], -r["on_time_orders"]),
        "total_late_days": lambda r: (r["total_days_late"], r["extra_cost"]),
        "max_delay": lambda r: (max([o["days_late"] for o in r["late_orders"]] or [0]),
                                r["extra_cost"]),
    }
    return min(ok, key=keys.get(objective, keys["on_time_orders"]))["code"]


def criteria_text(objective, budget, min_on_time) -> str:
    parts = [_OBJECTIVE_TEXT.get(objective, "most on-time orders")]
    if min_on_time:
        parts.append(f"at least {min_on_time} on-time orders")
    if budget is not None:
        parts.append(f"within {_money(budget)}")
    return ", ".join(parts)


# ── request settings (budget, objective, target) ──────────────────────────────

def _to_int(v):
    try:
        return int(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def request_settings(user_message: str, tool_trace: list[dict]) -> dict:
    """Budget, objective and minimum on-time target for this turn.

    The user's own words decide.  The objective comes only from the wording:
    in the question sweep the model passed objective="cost" to the search
    tool for plain budget questions, which starred WAIT ($0) under a $1,000
    budget.  Budget and target fall back to the model's tool arguments when
    the wording has none.
    """
    msg = user_message.lower()
    budget = parse_budget(msg)
    min_on = parse_min_on_time(msg)
    objective = parse_objective(msg)
    for t in tool_trace:
        a = t.get("args") or {}
        if t["name"] in ("compare_scenarios", "explore_purchase_qty"):
            if budget is None and _to_int(a.get("budget")) is not None:
                budget = _to_int(a.get("budget"))
            if min_on is None and _to_int(a.get("min_on_time_orders")) is not None:
                min_on = _to_int(a.get("min_on_time_orders"))
    return {"budget": budget, "objective": objective, "min_on_time": min_on}


_BUDGET_WORDS = re.compile(
    r"\b(budget|spend|afford|up to|at most|no more than|limit|cap|maximum of|we have)\b")
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\b|(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:dollars|usd)\b")


def parse_budget(msg: str):
    """'$800', '1,200 dollars', '$2k' next to a budget word -> int, else None.

    A price without a budget word ("is it worth paying $1,306?") is not a budget.
    """
    if not _BUDGET_WORDS.search(msg):
        return None
    m = _MONEY.search(msg)
    if not m:
        return None
    num, k = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    value = float(num.replace(",", ""))
    return int(value * 1000) if k else int(value)


def parse_min_on_time(msg: str):
    m = re.search(r"keep\s+(?:at least\s+)?(\d+)\s+(?:of the\s+\d+\s+)?orders", msg)
    if m:
        return int(m.group(1))
    if re.search(r"\b(all|every)\s+(?:\d+\s+)?orders?\b.*\bon.time|\bevery order\b", msg):
        return len(_t.get_catalog()["orders"])
    return None


def parse_objective(msg: str) -> str:
    if re.search(r"max(imum)? delay|longest delay|worst delay", msg):
        return "max_delay"
    if "late days" in msg or "days late" in msg:
        return "total_late_days"
    if re.search(r"cheap|lowest cost|least money|minimi[sz]e (the )?cost", msg):
        return "cost"
    return "on_time_orders"


# ── view: recommendation ──────────────────────────────────────────────────────

def situation_text(disruption_id: str, cat: dict) -> str:
    d = _t.get_disruption(disruption_id)
    imp = _t.get_impact(disruption_id)
    total = len(cat["orders"])
    sup = next(o for o in _t.get_offers(disruption_id)["offers"] if o["is_disrupted_supplier"])
    supplier = cat["suppliers"][sup["supplier_id"]]
    comp = cat["components"][d["component_id"]]
    return (
        f"A {d['reason'].lower()} at {supplier} delays {d['qty']} units of {comp} "
        f"({d['component_id']}, order {d['po_id']}) from {_day(d['original_receipt_date'])} "
        f"to {_day(d['revised_receipt_date'])}, a delay of {d['delay_days']} days. "
        f"With no action, {imp['late_order_count']} of {total} customer orders will be late."
    )


def options_table(rows, star_code=None, budget=None) -> str:
    head = "| Option | On-time orders | Priority-1 on time | Total days late | Extra cost |"
    sep = "|---|---|---|---|---|"
    if budget is not None:
        head += f" Within {_money(budget)} |"
        sep += "---|"
    lines = [head, sep]
    for r in rows:
        star = " ★" if r["code"] == star_code else ""
        note = ", found by search" if r.get("found_by_search") else ""
        name = f"{r['name']} ({r['code']}{note}){star}"
        cells = [
            name,
            f"{r['on_time_orders']} of {r['total_orders']}",
            f"{r['priority_on_time']} of {r['priority_total']}",
            str(r["total_days_late"]),
            _money(r["extra_cost"]),
        ]
        if budget is not None:
            cells.append("yes" if r["extra_cost"] <= budget else "no")
        if star:
            cells = [f"**{c}**" for c in cells]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def late_line(row) -> str:
    if not row["late_orders"]:
        return "No orders are late with this option."
    parts = []
    for o in row["late_orders"]:
        p = ", priority 1" if o["priority_rank"] == 1 else ""
        unit = "day" if o["days_late"] == 1 else "days"
        parts.append(f"{o['order_id']} ({o['days_late']} {unit}{p})")
    return "Still late with this option: " + ", ".join(parts) + "."


def mentioned_codes(user_message: str) -> list[str]:
    """Named scenario codes the user mentions, in order of appearance."""
    found = re.findall(r"\b(WAIT|TRANSFER|ALT_BUY|HYBRID)\b", user_message.upper())
    return list(dict.fromkeys(found))


_COMPARE_WORDS = re.compile(r"\b(compare|comparison|versus|vs\.?|difference between)\b", re.I)


def is_comparison(user_message: str) -> bool:
    """A request to compare options without asking for a pick under a budget or target."""
    msg = user_message.lower()
    return bool(_COMPARE_WORDS.search(msg)) and parse_budget(msg) is None \
        and parse_min_on_time(msg) is None


def build_recommendation(user_message, tool_trace, disruption_id="D01",
                         compare=False) -> dict:
    """Engine-built data for a recommendation answer (no LLM text yet).

    With ``compare=True`` no option is starred, and when the user names two
    or more scenarios only those rows are shown.
    """
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]
    settings = request_settings(user_message, tool_trace)
    rows = _named_rows(cat)
    named = mentioned_codes(user_message)
    if compare and len(named) >= 2:
        rows = [r for r in rows if r["code"] in named]
    searched = any(t["name"] == "explore_purchase_qty" for t in tool_trace)
    if searched and not (compare and len(named) >= 2):
        rows += _searched_rows(cat, _named_rows(cat), disruption_id)
    star = None if compare else choose_recommended(
        rows, settings["objective"], settings["budget"], settings["min_on_time"])
    star_row = next((r for r in rows if r["code"] == star), None)
    return {
        "type": "comparison" if compare else "recommendation",
        "situation": situation_text(disruption_id, cat),
        "settings": settings,
        "criteria": criteria_text(settings["objective"], settings["budget"],
                                  settings["min_on_time"]),
        "rows": rows,
        "recommended": star,
        "recommended_row": star_row,
        "table_markdown": options_table(rows, star, settings["budget"]),
    }


def recommendation_markdown(view: dict, rationale: str, tradeoffs: str) -> str:
    if view["type"] == "comparison":
        return comparison_markdown(view, rationale, tradeoffs)
    star_row = view["recommended_row"]
    out = [
        "## Situation", view["situation"], "",
        "## Options compared", view["table_markdown"], "",
        f"★ = recommended for: {view['criteria']}.", "",
        "## Recommendation",
    ]
    if star_row:
        out.append(f"**{star_row['name']} ({star_row['code']})**")
    else:
        out.append(f"**No option meets: {view['criteria']}.**")
    if rationale:
        out.append(rationale)
    out += ["", "## Trade-offs and risks"]
    if star_row:
        out.append(f"- {late_line(star_row)}")
    if tradeoffs:
        out.append(tradeoffs)
    out += ["", "## Next step"]
    if star_row:
        out.append(f'To act on this, say: *"Propose {star_row["code"]}"*. '
                   "Nothing is executed until it is approved in the UI.")
    else:
        out.append("Change the budget or the target and ask again.")
    return "\n".join(out)


def comparison_markdown(view: dict, comparison: str, tradeoffs: str) -> str:
    codes = [r["code"] for r in view["rows"]]
    example = codes[0] if codes else "TRANSFER"
    out = [
        "## Situation", view["situation"], "",
        "## Options compared", view["table_markdown"], "",
        "## Comparison",
    ]
    if comparison:
        out.append(comparison)
    if tradeoffs:
        out += ["", "## Trade-offs and risks", tradeoffs]
    for r in view["rows"]:
        out.append(f"- {r['code']}: {late_line(r)}")
    out += ["", "## Next step",
            f'To act on one of them, say for example: *"Propose {example}"*. '
            "To get a recommendation, add your budget or target."]
    return "\n".join(out)


def split_narrative(text: str) -> tuple[str, str]:
    """Split the model's text into (rationale, trade-off bullets)."""
    text = (text or "").strip()
    m = re.split(r"(?im)^\s*\**trade-?offs?\**\s*:\s*", text, maxsplit=1)
    rationale = re.sub(r"(?im)^\s*\**(recommendation|comparison)\**\s*:\s*", "", m[0]).strip()
    trade = m[1].strip() if len(m) > 1 else ""
    lines = [l.strip() for l in trade.splitlines() if l.strip()]
    trade = "\n".join(l if l.startswith("- ") else f"- {l.lstrip('-* ')}" for l in lines)
    return rationale, trade


# ── view: order ───────────────────────────────────────────────────────────────

def order_view(detail: dict) -> dict:
    cat = _catalog()
    o = cat["orders"][detail["order_id"]]
    c = detail["cause"]
    lines = [
        "## Answer", detail["summary"], "",
        "## Evidence",
        f"- Option: {detail['option']}",
        f"- Customer {o['customer_id']}, priority {o['priority_rank']}, "
        f"due {detail['due_date']}",
        f"- Latest on-time start: {detail['latest_start_date']}",
        f"- Starts {detail['start_date']}, delivered {detail['delivery_date']}, "
        f"{detail['days_late']} days late",
    ]
    if c["type"] == "queue_blocked":
        lines.append(f"- Cause: waiting in the production queue behind "
                     f"{c['waiting_order_id']}")
    elif c["type"] == "component_shortage":
        lines.append("- Cause: not enough components on the latest on-time start date")
    if c.get("shortfall"):
        short = ", ".join(f"{q} x {k} ({cat['components'][k]})" for k, q in c["shortfall"].items())
        lines.append(f"- Missing on {c['check_date']}: {short}")
    return {"type": "order", "detail": detail, "markdown": "\n".join(lines)}


# ── view: proposal ────────────────────────────────────────────────────────────

def proposal_view(proposal: dict, code: str) -> dict:
    cat = _catalog()
    m = proposal["metrics"]
    actions = proposal["actions"]
    lines = [
        "## Proposal created",
        f"**{option_name(actions, cat)} ({code})** is pending approval in the UI. "
        "Nothing has been executed.", "",
        f"- On-time orders: {m['on_time_orders']} of {m.get('total_orders', 12)}",
        f"- Total days late: {m['total_order_days_late']}",
        f"- Extra cost: {_money(m['total_extra_cost'])}", "",
        "### Actions in this proposal",
    ]
    if not actions:
        lines.append("- No recovery action: wait for the delayed delivery.")
    for a in actions:
        if a["type"] == "purchase":
            o = cat["offers"][a["offer_id"]]
            lines.append(f"- Buy {a['qty']} x {o['component_id']} "
                         f"({cat['components'][o['component_id']]}) from "
                         f"{cat['suppliers'][o['supplier_id']]} on {a['action_date']}")
        else:
            ln = cat["lanes"][a["lane_id"]]
            lines.append(f"- Move {a['qty']} x {a['component_id']} from "
                         f"{cat['warehouses'][ln['from']]} to {cat['warehouses'][ln['to']]} "
                         f"on {a['action_date']} ({ln['lead_days']} days in transit)")
    lines += ["", f"Proposal ID: {proposal['proposal_id']}",
              f"Reason given: {proposal.get('reason', '')}"]
    return {"type": "proposal", "proposal": proposal, "code": code,
            "markdown": "\n".join(lines)}


# ── view: option description ──────────────────────────────────────────────────

_DESCRIBE_WORDS = re.compile(
    r"\b(involve|mean|include|consist|entail|explain|details?|what is|what's|"
    r"what does|how does|describe)\b", re.I)


def is_option_question(user_message: str) -> bool:
    """'What does HYBRID involve?' -> True.  Order questions are excluded."""
    return (len(mentioned_codes(user_message)) == 1
            and bool(_DESCRIBE_WORDS.search(user_message))
            and not re.search(r"\bSO\d{2}\b", user_message, re.I))


def option_view(scenario_id: str, disruption_id="D01") -> dict:
    """What a named option does, step by step, with its results."""
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]
    actions = _t.get_scenario_actions(scenario_id)["actions"]
    row = _row(cat, actions, scenario_id=scenario_id)
    lines = [
        f"## {row['name']} ({scenario_id})", "",
        "### What it involves",
    ]
    if not actions:
        lines.append("- No recovery action: wait for the delayed delivery.")
    for a in actions:
        if a["type"] == "purchase":
            o = cat["offers"][a["offer_id"]]
            lines.append(f"- Buy {a['qty']} x {o['component_id']} "
                         f"({cat['components'][o['component_id']]}) from "
                         f"{cat['suppliers'][o['supplier_id']]} on {a['action_date']}")
        else:
            ln = cat["lanes"][a["lane_id"]]
            lines.append(f"- Move {a['qty']} x {a['component_id']} from "
                         f"{cat['warehouses'][ln['from']]} to {cat['warehouses'][ln['to']]} "
                         f"on {a['action_date']} ({ln['lead_days']} days in transit)")
    lines += [
        "", "### Results",
        f"- On-time orders: {row['on_time_orders']} of {row['total_orders']}",
        f"- Priority-1 on time: {row['priority_on_time']} of {row['priority_total']}",
        f"- Total days late: {row['total_days_late']}",
        f"- Extra cost: {_money(row['extra_cost'])}",
        f"- {late_line(row)}",
        "", "## Next step",
        f'To act on this, say: *"Propose {scenario_id}"*. To see it next to the '
        'other options, ask *"What should we do?"*.',
    ]
    return {"type": "option", "row": row, "markdown": "\n".join(lines)}


# ── view: unsupported ─────────────────────────────────────────────────────────

_WORD_NUM = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_HYPOTHETICAL = re.compile(
    r"\b(what if|suppose|assum|instead|imagine|if the|if it|if we get|earlier|sooner|later than)")
_DELAY_TERMS = re.compile(
    r"\b(delay|late|slip|arriv|shipment|deliver|supplier|po01|longer|takes|lead time)")


def _durations_in_days(msg: str) -> list[int]:
    out = []
    for n, unit in re.findall(r"\b(\d+|one|a|an|two|three|four|five|six|seven|eight|nine|ten)"
                              r"\s*-?\s*(days?|weeks?)\b", msg):
        v = int(n) if n.isdigit() else _WORD_NUM[n]
        out.append(v * 7 if unit.startswith("week") else v)
    return out


def is_unsupported(user_message: str, disruption_id="D01") -> bool:
    """True when the message names a different disruption ID, or when
    resolve_receipt_date gives a status of after_window, before_original
    or other_variable.
    """
    # Different or unknown disruption ID
    known = {disruption_id.lower()}
    if any(d not in known for d in re.findall(r"\bd\d{2}\b", user_message.lower())):
        return True
    # Receipt-date resolution
    res = resolve_receipt_date(user_message, disruption_id)
    if res is not None and res.get("status") in (
            "after_window", "before_original", "other_variable"):
        return True
    return False


def unsupported_view(disruption_id="D01", user_message="") -> dict:
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]
    d = _t.get_disruption(disruption_id)
    rows = _named_rows(cat)
    # In after_window / before_original cases, show reading_lines after ## Answer
    reading = []
    if user_message:
        res = resolve_receipt_date(user_message, disruption_id)
        if res is not None and res.get("status") in ("after_window", "before_original"):
            reading = reading_lines(res)
    answer_lines = ["## Answer"]
    if reading:
        answer_lines.extend(reading)
        answer_lines.append("")
    answer_lines.append(d["scope_note"])
    md = "\n".join(answer_lines + [
        "",
        f"## Current {disruption_id} situation (recorded {d['delay_days']}-day delay)",
        situation_text(disruption_id, cat), "",
        options_table(rows), "",
        "## Next step",
        'Ask about the recorded case, for example *"What should we do?"*.',
    ])
    return {"type": "unsupported", "scope_note": d["scope_note"], "rows": rows,
            "markdown": md}


# ── receipt-date reading (stage 1) ────────────────────────────────────────────

# Order-id pattern: SO01..SO12
_ORDER_ID_RE = re.compile(r"\bSO(?:0[1-9]|1[0-2])\b")

# Target words for explicit-date and uncertainty gating
_TARGET_RE = re.compile(
    r"\b(arriv\w*|receipt|deliver\w*|dates?\b|PO01|supplier|shipment|wait\w*"
    r"|transfer|alt_buy|hybrid|options?)\b", re.I)

# Other-variable guard: changes to transfer/lane/offer lead times
_OTHER_VAR_RE = re.compile(
    r"\b(transfers?\s+(takes?|is|are)|lead[- ]times?|lanes?|alternat\w*\s+supplier|OF\d{2})\b",
    re.I)

# Uncertainty words for world-risk routing
_UNCERTAINTY_RE = re.compile(
    r"\b(uncertain\w*|unsure|not\s+sure|probabilit\w*|chances?\b|likel\w*|odds\b|percentile\w*)\b",
    re.I)

# Risk words for world-risk routing
_RISK_RE = re.compile(r"\b(risk\w*|worst[- ]case)\b", re.I)

# Explicit date formats.
# Numeric MD forms have \b anchors; the ISO form is matched before them via
# alternation order so "2026-11-19" is captured as <iso>, not as <md_dash>.
_DATE_RE = re.compile(
    r"(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|\b(?P<md_slash>\d{1,2}/\d{1,2})\b"
    r"|\b(?P<md_dash>\d{1,2}-\d{1,2})\b"
    r"|(?P<month>(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?\s+\d{1,2}(?:st|nd|rd|th)?)"
    r")",
    re.I)

# Words that disqualify a numeric MM-DD match (range / fraction / unit contexts)
_MD_DISQUALIFY_RE = re.compile(r"\s*(?:days?|weeks?|units?|orders?|%)", re.I)

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Extended duration pattern: also catches "N more/extra days" and "N days earlier/later"
_DUR_EXT_RE = re.compile(
    r"\b(\d+|one|a\b|an\b|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*-?\s*"
    r"(?:more\s+|extra\s+)?"
    r"(days?|weeks?)"
    r"(?:\s+(?:more|extra|earlier|later|sooner|longer))?",
    re.I)


def _durations_in_days_ext(msg: str) -> list[int]:
    """Like _durations_in_days but also captures 'N more/extra days' and weeks."""
    out = []
    for m in _DUR_EXT_RE.finditer(msg):
        n_str = m.group(1).lower()
        unit = m.group(2).lower()
        v = int(n_str) if n_str.isdigit() else _WORD_NUM.get(n_str, 0)
        if v == 0:
            continue
        out.append(v * 7 if unit.startswith("week") else v)
    return out


def _receipt_window(disruption_id: str = "D01") -> dict:
    """Return key dates for the receipt window of a disruption.

    Reads from engine.tools only.  Returns a dict with:
        po_id       – str
        original    – date: PO's original planned receipt date
        announced   – date: disruption's revised receipt date
        first       – date: first date in the what_if window
        last        – date: last date in the what_if window
    """
    dis = _t.get_disruption(disruption_id)
    wr = _t.get_world_risk(disruption_id)
    return {
        "po_id": dis["po_id"],
        "original": date.fromisoformat(dis["original_receipt_date"]),
        "announced": date.fromisoformat(dis["revised_receipt_date"]),
        "first": date.fromisoformat(wr["what_if"]["dates"][0]),
        "last": date.fromisoformat(wr["what_if"]["dates"][-1]),
    }


def _parse_explicit_date(msg: str, announced: date) -> "list[date] | None":
    """Extract all explicit date references from msg.

    Returns a list of dates, or None when a numeric MM-DD token is found that
    is disqualified by a following word (days/weeks/units/orders/%) — signalling
    that the string contains a numeric range or fraction, not a date.

    Numeric MM-DD forms (11-19, 11/19) are accepted only when:
      - the month equals the month of *announced*, and
      - the match is not immediately followed by days/weeks/units/orders/%.
    ISO dates and month-name dates are accepted as-is.
    """
    results = []
    for m in _DATE_RE.finditer(msg):
        if m.group("iso"):
            try:
                results.append(date.fromisoformat(m.group("iso")))
            except ValueError:
                pass
        elif m.group("md_dash"):
            tail = msg[m.end():]
            if _MD_DISQUALIFY_RE.match(tail):
                # Numeric range like "3-4 days" — bail out entirely so the
                # day-count path does not produce a spurious single date.
                return None
            parts = m.group("md_dash").split("-")
            try:
                mo, dy = int(parts[0]), int(parts[1])
                if mo != announced.month:
                    continue
                results.append(announced.replace(month=mo, day=dy))
            except ValueError:
                pass
        elif m.group("md_slash"):
            tail = msg[m.end():]
            if _MD_DISQUALIFY_RE.match(tail):
                return None
            parts = m.group("md_slash").split("/")
            try:
                mo, dy = int(parts[0]), int(parts[1])
                if mo != announced.month:
                    continue
                results.append(announced.replace(month=mo, day=dy))
            except ValueError:
                pass
        elif m.group("month"):
            text = m.group("month")
            # extract month name and day number
            mo_m = re.match(r"([a-z]+)\.?\s+(\d+)", text, re.I)
            if mo_m:
                mo_name = mo_m.group(1)[:3].lower()
                dy = int(re.sub(r"\D", "", mo_m.group(2)))
                mo_num = _MONTH_NAMES.get(mo_name)
                if mo_num:
                    try:
                        results.append(announced.replace(month=mo_num, day=dy))
                    except ValueError:
                        pass
    return results


def resolve_receipt_date(user_message: str,
                         disruption_id: str = "D01") -> "dict | None":
    """Attempt to read a single receipt date from *user_message*.

    Returns None if the message names an order id (SO01-SO12) or contains no
    date wording.  Returns a status dict otherwise.

    The returned dict has:
        date        – ISO date string of the resolved date (when one date found)
        basis       – "explicit", "announced" or "original"
        days        – int offset used, or None for explicit dates
        status      – "announced", "after_window", "before_original" or "in_window"
        original    – ISO str of PO's planned receipt date
        announced   – ISO str of disruption's revised receipt date
        first       – ISO str of first simulated date
        last        – ISO str of last simulated date
        po_id       – str

    When more than one distinct date is found:
        {"status": "ambiguous"}
    When the change is to another variable (e.g. transfer lead time):
        {"status": "other_variable"}
    """
    msg = user_message.lower()

    # Block if an order id appears
    if _ORDER_ID_RE.search(user_message):
        return None

    win = _receipt_window(disruption_id)
    po_id = win["po_id"]
    original = win["original"]
    announced = win["announced"]
    first = win["first"]
    last = win["last"]

    def _status(d: date) -> str:
        if d == announced:
            return "announced"
        if d > last:
            return "after_window"
        if d < original:
            return "before_original"
        return "in_window"

    def _result(d: date, basis: str, days_val) -> dict:
        return {
            "date": d.isoformat(),
            "basis": basis,
            "days": days_val,
            "status": _status(d),
            "original": original.isoformat(),
            "announced": announced.isoformat(),
            "first": first.isoformat(),
            "last": last.isoformat(),
            "po_id": po_id,
        }

    # ── explicit date path ─────────────────────────────────────────────────────
    has_target = bool(_TARGET_RE.search(user_message))
    explicit_dates = _parse_explicit_date(user_message, announced)
    # None means a numeric range token was found — treat as no date wording.
    if explicit_dates is None:
        return None
    if explicit_dates and has_target:
        unique = list(dict.fromkeys(explicit_dates))
        if len(unique) > 1:
            return {"status": "ambiguous"}
        return _result(unique[0], "explicit", None)

    # ── day-count path ─────────────────────────────────────────────────────────
    delay_gate = (
        _DELAY_TERMS.search(msg)
        and (_HYPOTHETICAL.search(msg) or "delay" in msg)
    )
    if not delay_gate:
        return None

    # Other-variable guard
    if _OTHER_VAR_RE.search(user_message):
        return {"status": "other_variable"}

    durations = _durations_in_days_ext(msg)
    if not durations:
        return None

    # Determine direction
    _EARLIER_RE = re.compile(r"\b(earlier|sooner|early)\b")
    _MORE_RE = re.compile(r"\b(more|later|another|further|extra|longer)\b")

    from datetime import timedelta

    def _compute_date(n: int) -> tuple:
        if _EARLIER_RE.search(msg):
            return announced - timedelta(days=n), "announced"
        if _MORE_RE.search(msg):
            return announced + timedelta(days=n), "announced"
        return original + timedelta(days=n), "original"

    resolved = []
    for n in durations:
        d, basis = _compute_date(n)
        resolved.append((d, basis, n))

    unique_dates = list(dict.fromkeys(d for d, _, _ in resolved))
    if len(unique_dates) > 1:
        return {"status": "ambiguous"}

    d, basis, n = resolved[0]
    return _result(d, basis, n)


def reading_lines(resolution: dict) -> "list[str]":
    """Return the reading header lines for a resolved receipt date.

    Dates are formatted with the _day() helper (e.g. "Nov 14").
    Returns [] for status "other_variable" or "ambiguous".
    """
    status = resolution.get("status")
    if status in ("other_variable", "ambiguous"):
        return []

    po_id = resolution["po_id"]
    resolved_date = date.fromisoformat(resolution["date"])
    original = date.fromisoformat(resolution["original"])
    announced = date.fromisoformat(resolution["announced"])
    last = date.fromisoformat(resolution["last"])

    lines = [
        f"Read as: {po_id} arrives on {_day(resolved_date.isoformat())}.",
    ]

    if resolution["basis"] != "explicit":
        lines.append(
            '"N days late" counts from the original planned date'
            f" ({_day(original.isoformat())}). "
            '"N days earlier" or "N days later" counts from the announced'
            f" date ({_day(announced.isoformat())})."
        )

    if status == "after_window":
        lines.append(
            f"{_day(resolved_date.isoformat())} is after the last simulated day"
            f" ({_day(last.isoformat())})."
            " Dates after the window are planned for stage 2."
        )

    if status == "before_original":
        lines.append(
            f"{_day(resolved_date.isoformat())} is before the original planned date"
            f" ({_day(original.isoformat())})."
        )

    return lines


def is_world_risk_question(user_message: str,
                           disruption_id: str = "D01") -> bool:
    """True when the question is about uncertainty or risk across receipt dates.

    False if an order id or the word customer(s) appears.
    True when one of these holds:
      a) An uncertainty word (uncertain, chance, likely, probability, odds, ...).
      b) A risk word (risk, worst case) together with a target word.
      c) resolve_receipt_date gives status "in_window" or "ambiguous".
    """
    msg = user_message.lower()

    # Block on order ids or customer references
    if _ORDER_ID_RE.search(user_message):
        return False
    if re.search(r"\bcustomers?\b", msg):
        return False

    # (a) Uncertainty word
    if _UNCERTAINTY_RE.search(msg):
        return True

    # (b) Risk word + target word
    if _RISK_RE.search(msg) and _TARGET_RE.search(user_message):
        return True

    # (c) Resolves to a date in-window or ambiguous
    res = resolve_receipt_date(user_message, disruption_id)
    if res is not None and isinstance(res, dict) and res.get("status") in (
            "in_window", "ambiguous"):
        return True

    return False


# ── suggested questions (overview) ───────────────────────────────────────────

SUGGESTED_QUESTIONS: list[str] = [
    "How risky is each option if the arrival date of PO01 is uncertain?",
    "What is the chance of no late orders with TRANSFER?",
    "What if PO01 arrives on Nov 19?",
    "What if the supplier is 3 days late?",
]


# ── world_risk_view ────────────────────────────────────────────────────────────

def _world_risk_option_name(scenario_id: str, cat: dict) -> str:
    """Return the display name for a world-risk option row."""
    actions = _t.get_scenario_actions(scenario_id)["actions"]
    return option_name(actions, cat)


def world_risk_view(
    mode: str,
    user_message: str = "",
    explanation=None,
    disruption_id: str = "D01",
) -> dict:
    """Build a world_risk view dict from engine.tools.get_world_risk.

    Parameters
    ----------
    mode : str
        "overview", "general" or "date".
    user_message : str
        The user's message (used for budget parsing and date resolution).
    explanation : str | None
        LLM-generated paragraph to place in the explanation slot.
        None -> status "unavailable" in general/date mode.
    disruption_id : str
        Disruption to evaluate.

    Returns
    -------
    dict with keys: type, mode, situation, reading, focus_date, rows,
    what_if, steps, explanation, explanation_status, scope_note,
    suggested_questions, settings, markdown.

    Raises ValueError if mode is "date" and no in-window date can be resolved.
    """
    if mode not in ("overview", "general", "date"):
        raise ValueError(f"world_risk_view: unknown mode {mode!r}")

    wr = _t.get_world_risk(disruption_id)
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]

    # ── focus date (date mode only) ───────────────────────────────────────────
    focus_date = None
    reading = []
    if mode == "date":
        res = resolve_receipt_date(user_message, disruption_id)
        if res is None or res.get("status") != "in_window":
            raise ValueError(
                f"world_risk_view: mode 'date' requires an in-window receipt date; "
                f"got {res!r}"
            )
        focus_date = res["date"]
        reading = reading_lines(res)

    # ── budget ────────────────────────────────────────────────────────────────
    budget = parse_budget(user_message) if user_message else None

    # ── what_if index for focus date ─────────────────────────────────────────
    wi_dates = wr["what_if"]["dates"]
    focus_idx = wi_dates.index(focus_date) if focus_date and focus_date in wi_dates else None

    # ── rows ──────────────────────────────────────────────────────────────────
    rows = []
    for opt in wr["options"]:
        sid = opt["scenario_id"]
        late_at_focus = (
            wr["what_if"]["late_orders"][sid][focus_idx]
            if focus_idx is not None else None
        )
        within_budget = (
            opt["extra_cost"] <= budget if budget is not None else None
        )
        rows.append({
            "code": sid,
            "name": _world_risk_option_name(sid, cat),
            "scenario_id": sid,
            "extra_cost": opt["extra_cost"],
            "expected_late_orders": opt["expected_late_orders"],
            "p90_late_orders": opt["p90_late_orders"],
            "worst_late_orders": opt["worst_late_orders"],
            "p_no_late_pct": opt["p_no_late_pct"],
            "late_at_focus": late_at_focus,
            "within_budget": within_budget,
        })

    # ── situation ─────────────────────────────────────────────────────────────
    sit = situation_text(disruption_id, cat)
    scope_note = wr["scope_note"]
    situation = sit

    # ── explanation slot ──────────────────────────────────────────────────────
    if mode == "overview":
        exp_status = None
        exp_text = None
    elif explanation is None:
        exp_status = "unavailable"
        exp_text = ("(The AI explanation is unavailable. "
                    "The tables above come from the engine.)")
    else:
        _view_md = _build_world_risk_md_no_exp(
            mode, sit, scope_note, reading, rows, wr, budget, focus_date,
            disruption_id
        )
        ok, _reason = check_explanation(explanation, _view_md + "\n" + user_message)
        if ok:
            exp_status = "ok"
            exp_text = explanation
        else:
            exp_status = "dropped"
            exp_text = ("(The AI explanation is not shown because it used a number "
                        "or an option that is not in the tables.)")

    # ── markdown ──────────────────────────────────────────────────────────────
    # _build_world_risk_md_no_exp returns sections up to and including Notes and
    # Next step.  We splice "What this means" between Trade-offs and Notes.
    body_md = _build_world_risk_md_no_exp(
        mode, sit, scope_note, reading, rows, wr, budget, focus_date,
        disruption_id
    )
    if mode != "overview" and exp_text:
        # Insert "## What this means" after Trade-offs, before Notes.
        notes_marker = "\n\n## Notes\n"
        if notes_marker in body_md:
            body_md = body_md.replace(
                notes_marker,
                f"\n\n## What this means\n{exp_text}{notes_marker}",
                1,
            )
        else:
            body_md += f"\n\n## What this means\n{exp_text}"
    md = body_md

    # ── suggested questions (overview only) ──────────────────────────────────
    sq = SUGGESTED_QUESTIONS if mode == "overview" else []

    return {
        "type": "world_risk",
        "mode": mode,
        "situation": situation,
        "reading": reading,
        "focus_date": focus_date,
        "rows": rows,
        "what_if": wr["what_if"],
        "steps": wr["tradeoff_steps"],
        "explanation": exp_text if mode != "overview" else None,
        "explanation_status": exp_status,
        "scope_note": scope_note,
        "suggested_questions": sq,
        "settings": {"budget": budget},
        "markdown": md,
    }


def _build_world_risk_md_no_exp(
    mode: str,
    sit: str,
    scope_note: str,
    reading: list,
    rows: list,
    wr: dict,
    budget,
    focus_date,
    disruption_id: str = "D01",
) -> str:
    """Build the markdown for world_risk_view excluding the explanation section."""
    parts = []

    # ## Situation (with full scope_note)
    # Append "(if <po> arrives on the announced date, <Mon DD>)" to the late-orders
    # sentence.  Take PO and announced date from the engine.
    dis = _t.get_disruption(disruption_id)
    sit_annotated = sit.rstrip()
    # The sentence ends with "will be late." — append the announced-date clause.
    announced_label = _day(dis["revised_receipt_date"])
    _LATE_SENTENCE = "will be late."
    if sit_annotated.endswith(_LATE_SENTENCE):
        sit_annotated = (
            sit_annotated[: -len(_LATE_SENTENCE)]
            + f"will be late (if {dis['po_id']} arrives on the announced date, {announced_label})."
        )
    parts.append(f"## Situation\n{sit_annotated}\n{scope_note}")

    # ## Reading (date mode only)
    if mode == "date" and reading:
        parts.append("## Reading\n" + "\n".join(reading))

    # ## Time and cost by option
    focus_date_day = _day(focus_date) if focus_date else None
    header_cols = [
        "Option", "Extra cost", "Expected late orders",
        "90th percentile", "Worst case", "Chance of no late order",
    ]
    if focus_date:
        header_cols.append(f"Late if it arrives {focus_date_day}")
    if budget is not None:
        header_cols.append(f"Within {_money(budget)}")

    header = "| " + " | ".join(header_cols) + " |"
    sep = "| " + " | ".join(["---"] * len(header_cols)) + " |"
    table_rows = [header, sep]
    for r in rows:
        cells = [
            f"{r['name']} ({r['code']})",
            _money(r["extra_cost"]),
            f"{r['expected_late_orders']:.2f}",
            str(r["p90_late_orders"]),
            str(r["worst_late_orders"]),
            f"{r['p_no_late_pct']:.1f}%",
        ]
        if focus_date:
            cells.append(str(r["late_at_focus"]))
        if budget is not None:
            cells.append("Yes" if r["within_budget"] else "No")
        table_rows.append("| " + " | ".join(cells) + " |")
    parts.append("## Time and cost by option\n" + "\n".join(table_rows))

    # ## Late orders by receipt date
    dates = wr["what_if"]["dates"]
    wi_header = ["Option"] + [_day(d) for d in dates]
    if focus_date and focus_date in dates:
        fidx = dates.index(focus_date)
    else:
        fidx = None

    # Bold the focus column header
    if fidx is not None:
        wi_header[fidx + 1] = f"**{wi_header[fidx + 1]}**"

    wi_hdr = "| " + " | ".join(wi_header) + " |"
    wi_sep = "| " + " | ".join(["---"] * len(wi_header)) + " |"
    wi_rows_lines = [wi_hdr, wi_sep]
    for r in rows:
        sid = r["scenario_id"]
        late_vals = wr["what_if"]["late_orders"][sid]
        cells = [f"{r['name']} ({r['code']})"]
        for i, v in enumerate(late_vals):
            cell = str(v)
            if fidx is not None and i == fidx:
                cell = f"**{cell}**"
            cells.append(cell)
        wi_rows_lines.append("| " + " | ".join(cells) + " |")
    parts.append("## Late orders by receipt date\n" + "\n".join(wi_rows_lines))

    # ## Trade-offs
    bullets = []
    for step in wr["tradeoff_steps"]:
        frm = step["from"]
        to = step["to"]
        cost_chg = step["extra_cost_change"]
        exp_chg = step["expected_late_change"]
        p90_chg = step["p90_late_change"]
        worst_chg = step["worst_late_change"]
        p_no_chg = step["p_no_late_pct_change"]
        bullets.append(
            f"- {frm} to {to}: +{_money(cost_chg)}, "
            f"expected late orders {exp_chg:+.2f}, "
            f"90th percentile {p90_chg:+d}, "
            f"worst case {worst_chg:+d}, "
            f"chance of no late order {p_no_chg:+.1f} points"
        )
    parts.append("## Trade-offs\n" + "\n".join(bullets))

    # ## Notes
    notes = [
        "Time and cost are shown side by side and never combined into one score.",
        "90th percentile: in 9 of 10 weighted cases late orders are at or below this number.",
        "The weights are an assumption from the data file.",
    ]

    if mode == "overview":
        sq_lines = "\n".join(f"- *{q}*" for q in SUGGESTED_QUESTIONS)
        next_step = f"## Next step\n{sq_lines}"
    else:
        next_step = (
            '## Next step\n'
            'To act on an option, say *"Propose HYBRID"* or another option code.'
        )

    # Order: Trade-offs already appended. Now: Notes, Next step.
    # The "What this means" slot is inserted by world_risk_view between
    # Trade-offs and Notes so that the final heading order is:
    # Situation, [Reading,] Time and cost, Late orders, Trade-offs,
    # What this means, Notes, Next step.
    parts.append("## Notes\n" + "\n".join(notes))
    parts.append(next_step)

    return "\n\n".join(parts)


# ── check_explanation ─────────────────────────────────────────────────────────

def check_explanation(text: str, view_md_no_exp: str) -> tuple:
    """Validate an LLM explanation paragraph against the view.

    Parameters
    ----------
    text : str
        The LLM-generated paragraph.
    view_md_no_exp : str
        The view markdown WITHOUT the explanation section.

    Returns
    -------
    (ok: bool, reason: str)
      ok is True only when:
        a) Every digit sequence in text equals some number in view_md_no_exp.
        b) Every option code in text (WAIT, TRANSFER, ALT_BUY, HYBRID, NORMAL,
           OF\\d{2}) is in the view markdown.
        c) At most 4 sentences.
    """
    # (c) sentence count — split only on . ! ? followed by whitespace or end
    sentences = [s.strip() for s in re.split(r"[.!?]+(?=\s|$)", text) if s.strip()]
    if len(sentences) > 4:
        return False, f"too many sentences ({len(sentences)})"

    # Normalise view numbers: strip commas, collect all numbers as strings
    def _extract_numbers(s: str) -> set:
        # Match digit sequences with optional decimal, strip commas first
        s_clean = s.replace(",", "")
        return {m.group() for m in re.finditer(r"\d+(?:\.\d+)?", s_clean)}

    view_numbers = _extract_numbers(view_md_no_exp)

    # Normalise text numbers; accept integer N if view has N.0, and vice-versa.
    text_clean = text.replace(",", "")
    for m in re.finditer(r"\d+(?:\.\d+)?", text_clean):
        num = m.group()
        if num in view_numbers:
            continue
        # Try integer/decimal equivalence: "35" matches "35.0", "35.0" matches "35"
        if "." in num:
            base = num.rstrip("0").rstrip(".")
            if base in view_numbers:
                continue
        else:
            if (num + ".0") in view_numbers:
                continue
        return False, f"number {num!r} not in view"

    # (b) option codes
    valid_codes = set(re.findall(r"\b(WAIT|TRANSFER|ALT_BUY|HYBRID|NORMAL|OF\d{2})\b",
                                 view_md_no_exp))
    for code in re.findall(r"\b(WAIT|TRANSFER|ALT_BUY|HYBRID|NORMAL|OF\d{2})\b", text):
        if code not in valid_codes:
            return False, f"option code {code!r} not in view rows"

    return True, "ok"


# ── parse_world_risk_answer ───────────────────────────────────────────────────

def parse_world_risk_answer(text: str) -> str:
    """Strip the 'Answer:' label from a world-risk LLM response.

    'Answer: <paragraph>' -> '<paragraph>'
    """
    stripped = text.strip()
    if stripped.startswith("Answer:"):
        return stripped[len("Answer:"):].strip()
    return stripped
