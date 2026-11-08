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
    """True when the user asks about a delay length or disruption that is not modelled.

    A different duration counts only next to delay words and either a
    hypothetical marker ("what if", "suppose", "instead") or the word
    "delay", so "Why is SO08 2 days late?" stays a normal question.
    """
    msg = user_message.lower()
    recorded = _t.get_disruption(disruption_id)["delay_days"]
    if _DELAY_TERMS.search(msg) and (_HYPOTHETICAL.search(msg) or "delay" in msg):
        if any(d != recorded for d in _durations_in_days(msg)):
            return True
    known = {disruption_id.lower()}
    return any(d not in known for d in re.findall(r"\bd\d{2}\b", msg))


def unsupported_view(disruption_id="D01") -> dict:
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]
    d = _t.get_disruption(disruption_id)
    rows = _named_rows(cat)
    md = "\n".join([
        "## Answer", d["scope_note"], "",
        f"## Current {disruption_id} situation (recorded {d['delay_days']}-day delay)",
        situation_text(disruption_id, cat), "",
        options_table(rows), "",
        "## Next step",
        'Ask about the recorded case, for example *"What should we do?"*.',
    ])
    return {"type": "unsupported", "scope_note": d["scope_note"], "rows": rows,
            "markdown": md}
