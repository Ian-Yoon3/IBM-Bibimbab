"""Tool specs, dispatch table, and call_tool for the NovaTech agent.

TOOL_SPECS   – list of JSON-schema dicts for the 7 LLM-facing tools
DISPATCH     – maps tool name -> engine function
call_tool    – validates args, dispatches, returns result or {"error": ...}

Note on propose_action:
    The LLM may propose either a named scenario (scenario_id) or a
    specific purchase quantity from explore_purchase_qty results
    (offer_id + qty + optional include_transfers).  call_tool resolves
    the explore-qty path into an actions list before forwarding to the
    engine.
"""

import engine.tools as _tools

# ── valid enum values (loaded lazily so tests don't need a .env) ──────────────

_VALID_SCENARIOS = {"NORMAL", "WAIT", "TRANSFER", "ALT_BUY", "HYBRID"}
_VALID_OBJECTIVES = {
    "on_time_orders", "on_time_units", "total_late_days", "max_delay", "cost"
}


def _valid_disruption_ids() -> set[str]:
    """Return the set of disruption IDs present in the data."""
    db = _tools._get_db()
    return set(db["disruptions"].keys())


# ── tool specs ────────────────────────────────────────────────────────────────

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_disruption",
            "description": (
                "Use this FIRST to look up details of a disruption: affected PO, "
                "component, original and revised receipt dates, delay in days, and "
                "reason.  Call this when the user asks what the disruption is or "
                "what happened."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disruption_id": {
                        "type": "string",
                        "description": "The disruption ID, e.g. 'D01'.",
                    },
                },
                "required": ["disruption_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_offers",
            "description": (
                "Return all supplier offers for the component affected by a disruption. "
                "Call this BEFORE explore_purchase_qty to find the valid offer_id to use."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disruption_id": {
                        "type": "string",
                        "description": "The disruption ID, e.g. 'D01'.",
                    },
                },
                "required": ["disruption_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_impact",
            "description": (
                "Analyse the impact of a disruption assuming no recovery actions "
                "(WAIT baseline).  Returns the first late order, all late orders, "
                "and a day-by-day C01 shortage table.  Use when the user asks "
                "'how bad is the disruption?' or 'what happens if we do nothing?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "disruption_id": {
                        "type": "string",
                        "description": "The disruption ID, e.g. 'D01'.",
                    },
                },
                "required": ["disruption_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_scenarios",
            "description": (
                "Rank all four recovery scenarios (WAIT, TRANSFER, ALT_BUY, HYBRID) "
                "by on-time orders or another objective.  NORMAL is returned as a "
                "baseline.  Use when the user asks which option is best, or wants "
                "to compare options possibly within a budget."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "budget": {
                        "type": "integer",
                        "description": "Optional cost ceiling in USD.  Omit to see all options.",
                    },
                    "objective": {
                        "type": "string",
                        "enum": [
                            "on_time_orders", "on_time_units",
                            "total_late_days", "max_delay", "cost"
                        ],
                        "description": "Ranking objective.  Default: on_time_orders.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_priority_view",
            "description": (
                "Show which priority-1 orders are on time and which are late under "
                "a named scenario.  Use when the user asks about high-priority "
                "customers or top-priority orders for a specific scenario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {
                        "type": "string",
                        "enum": ["WAIT", "TRANSFER", "ALT_BUY", "HYBRID"],
                        "description": "The scenario to evaluate.",
                    },
                },
                "required": ["scenario_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explore_purchase_qty",
            "description": (
                "Sweep every valid purchase quantity for a supplier offer and rank "
                "results.  Call get_offers first to find the offer_id.  Use when the "
                "user asks whether a smaller or cheaper purchase could achieve the same "
                "on-time count as HYBRID, or to find the cheapest option that meets a "
                "target on-time count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {
                        "type": "string",
                        "description": "Supplier offer ID, e.g. 'OF02'.",
                    },
                    "include_transfers": {
                        "type": "boolean",
                        "description": (
                            "If true, combine each purchase quantity with all "
                            "available transfers.  Default: false."
                        ),
                    },
                    "budget": {
                        "type": "integer",
                        "description": "Optional cost ceiling in USD.",
                    },
                    "objective": {
                        "type": "string",
                        "enum": [
                            "on_time_orders", "on_time_units",
                            "total_late_days", "max_delay", "cost"
                        ],
                        "description": "Ranking objective.  Default: on_time_orders.",
                    },
                },
                "required": ["offer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_action",
            "description": (
                "Package a recovery plan as a pending proposal (never executes it). "
                "Use when the user asks to act, approve, or implement an option.  "
                "Accepts either a named scenario_id OR an (offer_id + qty) pair from "
                "explore_purchase_qty results.  Always tell the user the proposal is "
                "pending approval and that approval happens in the UI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scenario_id": {
                        "type": "string",
                        "enum": ["WAIT", "TRANSFER", "ALT_BUY", "HYBRID"],
                        "description": "Named scenario to propose.  Use instead of offer_id+qty.",
                    },
                    "offer_id": {
                        "type": "string",
                        "description": (
                            "Offer ID from explore_purchase_qty.  "
                            "Use with qty instead of scenario_id."
                        ),
                    },
                    "qty": {
                        "type": "integer",
                        "description": "Purchase quantity from explore_purchase_qty results.",
                    },
                    "include_transfers": {
                        "type": "boolean",
                        "description": (
                            "Whether to include all transfers alongside the purchase.  "
                            "Match the value used in explore_purchase_qty.  Default: false."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief rationale for the proposal.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

# ── dispatch table ────────────────────────────────────────────────────────────

DISPATCH: dict = {
    "get_disruption":      _tools.get_disruption,
    "get_offers":          _tools.get_offers,
    "get_impact":          _tools.get_impact,
    "compare_scenarios":   _tools.compare_scenarios,
    "get_priority_view":   _tools.get_priority_view,
    "explore_purchase_qty": _tools.explore_purchase_qty,
    "propose_action":      None,  # handled specially in call_tool
}


# ── call_tool ─────────────────────────────────────────────────────────────────

def call_tool(name: str, args: dict) -> dict:
    """Validate args and dispatch a tool call to the engine.

    Parameters
    ----------
    name:
        Tool name string from the LLM.
    args:
        Normalised argument dict (already converted from JSON string if needed).

    Returns
    -------
    Engine result dict, or ``{"error": "<message>"}`` for LLM-facing errors
    (invalid args, unknown IDs, engine ValueError).

    Notes
    -----
    Unknown tool *names* return ``{"error": "unknown tool: <name>"}`` so the
    loop can forward the error back to the LLM instead of crashing.
    """
    if name not in DISPATCH:
        return {"error": f"unknown tool: {name}"}

    # ── argument validation ───────────────────────────────────────────────────

    if name in ("get_disruption", "get_impact", "get_offers"):
        dis_id = args.get("disruption_id")
        if not dis_id:
            return {"error": "disruption_id is required"}
        valid_ids = _valid_disruption_ids()
        if dis_id not in valid_ids:
            return {
                "error": (
                    f"Unknown disruption_id {dis_id!r}. "
                    f"Known IDs: {sorted(valid_ids)}"
                )
            }

    if name == "compare_scenarios":
        obj = args.get("objective", "on_time_orders")
        if obj not in _VALID_OBJECTIVES:
            return {"error": f"Unknown objective {obj!r}. Choose from: {sorted(_VALID_OBJECTIVES)}"}
        budget = args.get("budget")
        if budget is not None and (not isinstance(budget, int) or budget < 0):
            return {"error": "budget must be a non-negative integer"}

    if name == "get_priority_view":
        sid = args.get("scenario_id")
        if not sid:
            return {"error": "scenario_id is required"}
        if sid not in _VALID_SCENARIOS:
            return {"error": f"Unknown scenario_id {sid!r}. Choose from: {sorted(_VALID_SCENARIOS)}"}

    if name == "explore_purchase_qty":
        if not args.get("offer_id"):
            return {"error": "offer_id is required"}
        obj = args.get("objective", "on_time_orders")
        if obj not in _VALID_OBJECTIVES:
            return {"error": f"Unknown objective {obj!r}"}

    if name == "propose_action":
        reason = args.get("reason", "")
        if not reason:
            return {"error": "reason is required for propose_action"}
        return _dispatch_propose_action(args)

    # ── dispatch non-propose calls ────────────────────────────────────────────
    fn = DISPATCH[name]
    safe_args = {k: v for k, v in args.items() if k != "data_dir"}
    try:
        return fn(**safe_args)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}


def _dispatch_propose_action(args: dict) -> dict:
    """Resolve propose_action args and call the engine."""
    reason     = args.get("reason", "")
    scenario_id = args.get("scenario_id")
    offer_id   = args.get("offer_id")
    qty        = args.get("qty")

    if scenario_id:
        # Named-scenario path
        if scenario_id not in _VALID_SCENARIOS:
            return {"error": f"Unknown scenario_id {scenario_id!r}"}
        try:
            return _tools.propose_action(scenario_id, reason)
        except (ValueError, TypeError) as exc:
            return {"error": str(exc)}

    if offer_id and qty is not None:
        # explore-qty path: rebuild actions via explore_purchase_qty
        include_transfers = bool(args.get("include_transfers", False))
        try:
            explore_result = _tools.explore_purchase_qty(
                offer_id=offer_id,
                include_transfers=include_transfers,
            )
        except (ValueError, TypeError) as exc:
            return {"error": str(exc)}

        # Find the matching ranked option
        match = next(
            (r for r in explore_result["ranked"] if r.get("purchase_qty") == qty),
            None,
        )
        if match is None:
            return {"error": f"qty={qty} not found in explore results for offer {offer_id!r}"}

        action_list = match["actions"]
        try:
            return _tools.propose_action(action_list, reason)
        except (ValueError, TypeError) as exc:
            return {"error": str(exc)}

    return {
        "error": (
            "propose_action requires either scenario_id or both offer_id and qty"
        )
    }
