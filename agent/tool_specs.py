"""Tool specs, dispatch table, and call_tool for the NovaTech agent.

TOOL_SPECS   – list of JSON-schema dicts for the 7 LLM-facing tools
DISPATCH     – maps tool name -> engine function
call_tool    – validates args, dispatches, returns result or {"error": ...}

Type coercion
-------------
Integers: int or a numeric string ("500" -> 500).  Anything else is an error.
Booleans: bool or "true"/"false" (case-insensitive).  Anything else is an error.
Coercion is applied to all integer/boolean fields before validation.

Disrupted-supplier guard
------------------------
explore_purchase_qty and propose_action (offer_id path) check whether
the given offer_id is the disrupted supplier.  If so, an error is returned
directing the LLM to choose an alternative from get_offers.

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


def _disrupted_offer_id(offer_id: str) -> bool:
    """Return True if offer_id is the disrupted supplier's offer."""
    try:
        result = _tools.get_offers("D01")
        for o in result.get("offers", []):
            if o["offer_id"] == offer_id and o.get("is_disrupted_supplier"):
                return True
        return False
    except Exception:
        return False


# ── type coercion helpers ─────────────────────────────────────────────────────

def _coerce_int(value, field: str):
    """Return (int_value, None) or (None, error_str)."""
    if isinstance(value, bool):
        return None, f"{field!r} must be an integer, got boolean"
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value), None
        except ValueError:
            pass
    return None, f"{field!r} must be an integer or numeric string, got {value!r}"


def _coerce_bool(value, field: str):
    """Return (bool_value, None) or (None, error_str)."""
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        if value.lower() == "true":
            return True, None
        if value.lower() == "false":
            return False, None
    return None, f"{field!r} must be true/false (boolean or string), got {value!r}"


_NULL_LIKE = {"null", "none", ""}


def _drop_null_like(args: dict) -> dict:
    """Return a copy of args without None values or null-like strings.

    Some models send "null", "None" or "" for optional arguments instead of
    leaving them out.  Treating them as absent lets required-argument checks
    report a clear error and lets optional arguments fall back to defaults.
    """
    return {
        k: v for k, v in args.items()
        if v is not None
        and not (isinstance(v, str) and v.strip().lower() in _NULL_LIKE)
    }


def _coerce_fields(args: dict, int_fields: list[str], bool_fields: list[str]):
    """In-place coerce integer and boolean fields. Returns error string or None."""
    for f in int_fields:
        if f in args and args[f] is not None:
            v, err = _coerce_int(args[f], f)
            if err:
                return err
            args[f] = v
    for f in bool_fields:
        if f in args and args[f] is not None:
            v, err = _coerce_bool(args[f], f)
            if err:
                return err
            args[f] = v
    return None


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
                "Call this BEFORE explore_purchase_qty to find the valid offer_id to use. "
                "The is_disrupted_supplier flag marks the offer behind the delay — "
                "always choose an ALTERNATIVE offer for recovery."
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
                "results.  Call get_offers first to find the offer_id.  "
                "Use min_on_time_orders to find the cheapest option that meets a "
                "target on-time count (e.g. 'cheaper way to keep 11 orders on time' "
                "-> min_on_time_orders=11, include_transfers=true, objective='cost')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offer_id": {
                        "type": "string",
                        "description": "Supplier offer ID from get_offers (not the disrupted supplier's offer).",
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
                    "min_on_time_orders": {
                        "type": "integer",
                        "description": (
                            "Exclude options with fewer on-time orders than this. "
                            "Use with objective='cost' to find the cheapest option "
                            "meeting a minimum on-time target."
                        ),
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
                "Use ONLY when the user explicitly says: approve, propose, implement, "
                "submit, go ahead, execute, or do it.  Do NOT call this for "
                "recommendation questions — suggest a proposal in the Next step instead.  "
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

# propose_action spec extracted for use in the loop (conditional inclusion)
_PROPOSE_ACTION_SPEC = TOOL_SPECS[-1]

# TOOL_SPECS_NO_PROPOSE: all tools except propose_action
TOOL_SPECS_NO_PROPOSE: list[dict] = [s for s in TOOL_SPECS if s["function"]["name"] != "propose_action"]

# Keywords that signal explicit action intent
_ACTION_KEYWORDS = frozenset([
    "approve", "propose", "implement", "submit", "go ahead",
    "execute", "do it",
])

# ── dispatch table ────────────────────────────────────────────────────────────

DISPATCH: dict = {
    "get_disruption":       _tools.get_disruption,
    "get_offers":           _tools.get_offers,
    "get_impact":           _tools.get_impact,
    "compare_scenarios":    _tools.compare_scenarios,
    "get_priority_view":    _tools.get_priority_view,
    "explore_purchase_qty": _tools.explore_purchase_qty,
    "propose_action":       None,  # handled specially in call_tool
}


def tool_specs_for(user_message: str) -> list[dict]:
    """Return TOOL_SPECS with propose_action included only when the user
    message contains an explicit action intent keyword.

    This is a heuristic to prevent the LLM from calling propose_action
    during recommendation questions.

    Parameters
    ----------
    user_message:
        The raw user input text.

    Returns
    -------
    List of tool spec dicts.
    """
    msg_lower = user_message.lower()
    has_action_intent = any(kw in msg_lower for kw in _ACTION_KEYWORDS)
    if has_action_intent:
        return TOOL_SPECS
    return TOOL_SPECS_NO_PROPOSE


# ── call_tool ─────────────────────────────────────────────────────────────────

def call_tool(name: str, args, offered_names: set[str] | None = None) -> dict:
    """Validate args and dispatch a tool call to the engine.

    Parameters
    ----------
    name:
        Tool name string from the LLM.
    args:
        Normalised argument dict, or ``None`` when ``normalize_tool_calls``
        could not parse the arguments (e.g. malformed JSON from the LLM).
    offered_names:
        Set of tool names that were offered to the LLM this turn.  When
        provided, any call to a tool NOT in this set is rejected without
        calling the engine, returning an informative error.  This enforces
        the propose_action gate even when the LLM ignores the tool list.

    Returns
    -------
    Engine result dict, or ``{"error": "<message>"}`` for LLM-facing errors
    (invalid args, unknown IDs, engine ValueError, parse failure).

    Notes
    -----
    Unknown tool *names* return ``{"error": "unknown tool: <name>"}`` so the
    loop can forward the error back to the LLM instead of crashing.
    Type coercion is applied to all integer/boolean fields before validation.
    """
    # Enforce the offered-tools guard before anything else
    if offered_names is not None and name not in offered_names:
        return {
            "error": (
                f"{name!r} is not available in this turn; "
                "the user has not asked to act"
            )
        }

    if name not in DISPATCH:
        return {"error": f"unknown tool: {name}"}

    # args is None when normalize_tool_calls could not decode the arguments
    if args is None:
        return {
            "error": (
                f"could not parse arguments for {name!r}, "
                "please retry with valid JSON"
            )
        }

    # Work on a mutable copy so callers' dicts are not modified
    args = dict(args)

    # Treat null-like values as "argument not given".  Some models send the
    # string "null" (or "none", "") for optional arguments they want to omit.
    args = _drop_null_like(args)

    # ── type coercion ─────────────────────────────────────────────────────────

    if name == "compare_scenarios":
        err = _coerce_fields(args, int_fields=["budget"], bool_fields=[])
        if err:
            return {"error": err}

    if name == "explore_purchase_qty":
        err = _coerce_fields(
            args,
            int_fields=["budget", "min_on_time_orders"],
            bool_fields=["include_transfers"],
        )
        if err:
            return {"error": err}

    if name == "propose_action":
        err = _coerce_fields(
            args,
            int_fields=["qty"],
            bool_fields=["include_transfers"],
        )
        if err:
            return {"error": err}

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
        if budget is not None and budget < 0:
            return {"error": "budget must be a non-negative integer"}

    if name == "get_priority_view":
        sid = args.get("scenario_id")
        if not sid:
            return {"error": "scenario_id is required"}
        if sid not in _VALID_SCENARIOS:
            return {"error": f"Unknown scenario_id {sid!r}. Choose from: {sorted(_VALID_SCENARIOS)}"}

    if name == "explore_purchase_qty":
        offer_id = args.get("offer_id")
        if not offer_id:
            return {"error": "offer_id is required"}
        obj = args.get("objective", "on_time_orders")
        if obj not in _VALID_OBJECTIVES:
            return {"error": f"Unknown objective {obj!r}"}
        # Disrupted-supplier guard
        if _disrupted_offer_id(offer_id):
            return {
                "error": (
                    f"{offer_id!r} is the disrupted supplier's offer; "
                    "choose an alternative from get_offers"
                )
            }

    if name == "propose_action":
        reason = args.get("reason", "")
        if not reason:
            return {"error": "reason is required for propose_action"}
        # Disrupted-supplier guard for offer_id path
        offer_id = args.get("offer_id")
        if offer_id and _disrupted_offer_id(offer_id):
            return {
                "error": (
                    f"{offer_id!r} is the disrupted supplier's offer; "
                    "choose an alternative from get_offers"
                )
            }
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
    reason      = args.get("reason", "")
    scenario_id = args.get("scenario_id")
    offer_id    = args.get("offer_id")
    qty         = args.get("qty")

    if scenario_id:
        # Named-scenario path
        if scenario_id not in _VALID_SCENARIOS:
            return {
                "error": (
                    f"Unknown scenario_id {scenario_id!r}. "
                    "Explored options (from explore_purchase_qty) must be proposed "
                    "with offer_id, qty and include_transfers — not a scenario_id."
                )
            }
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
