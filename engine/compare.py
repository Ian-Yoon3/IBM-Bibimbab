"""Rank evaluated scenario options by a chosen objective."""

_HIGHER_BETTER = {"on_time_orders", "on_time_units"}
_LOWER_BETTER = {"total_late_days", "max_delay", "cost"}
_VALID_OBJECTIVES = _HIGHER_BETTER | _LOWER_BETTER

# Map objective names to the evaluate() dict key they correspond to
_OBJ_KEY = {
    "on_time_orders": "on_time_orders",
    "on_time_units": "on_time_units",
    "total_late_days": "total_order_days_late",
    "max_delay": "max_order_days_late",
    "cost": "total_extra_cost",
}


def rank_options(
    options: list,
    objective: str = "on_time_orders",
    budget: int | None = None,
) -> dict:
    """Rank evaluated options by a chosen objective.

    Parameters
    ----------
    options:
        List of dicts, each being an ``evaluate()`` return value with
        ``"label"`` (display string) and optional ``"scenario_id"`` keys.
        ``scenario_id`` is used as the identity key when present; otherwise
        ``label`` is used.
    objective:
        One of ``on_time_orders``, ``on_time_units`` (higher is better) or
        ``total_late_days``, ``max_delay``, ``cost`` (lower is better).
    budget:
        If set, options with ``total_extra_cost > budget`` are excluded.
        If no options survive the filter, ``"best"`` is ``null``/``None``.

    Returns
    -------
    dict with keys:
        objective, budget,
        ranked (list: rank, scenario_id, label, score, KPIs),
        best (scenario_id of rank-1 option, or label if no scenario_id)
    """
    if objective not in _VALID_OBJECTIVES:
        raise ValueError(
            f"Unknown objective {objective!r}. "
            f"Choose from: {sorted(_VALID_OBJECTIVES)}"
        )

    obj_key = _OBJ_KEY[objective]

    # Apply budget filter
    candidates = options
    if budget is not None:
        candidates = [o for o in options if o["total_extra_cost"] <= budget]

    if not candidates:
        return {
            "objective": objective,
            "budget": budget,
            "ranked": [],
            "best": None,
        }

    # Sort key: primary objective, tie-break by lower cost then fewer late days
    def sort_key(o):
        primary = o[obj_key]
        if objective in _HIGHER_BETTER:
            primary = -primary          # negate so higher = smaller = better
        tie_cost = o["total_extra_cost"]
        tie_late = o["total_order_days_late"]
        return (primary, tie_cost, tie_late)

    ranked_sorted = sorted(candidates, key=sort_key)

    ranked = []
    for rank, opt in enumerate(ranked_sorted, start=1):
        # Use scenario_id as the identity key when available; fall back to label
        identity = opt.get("scenario_id", opt["label"])
        entry = {
            "rank": rank,
            "scenario_id": identity,
            "label": opt["label"],
            "score": opt[obj_key],
            "on_time_orders": opt["on_time_orders"],
            "on_time_units": opt["on_time_units"],
            "total_order_days_late": opt["total_order_days_late"],
            "max_order_days_late": opt["max_order_days_late"],
            "total_extra_cost": opt["total_extra_cost"],
        }
        # Pass through extra keys when present (set by explore_purchase_qty)
        for extra_key in ("actions", "purchase_qty", "option_type"):
            if extra_key in opt:
                entry[extra_key] = opt[extra_key]
        ranked.append(entry)

    best_opt = ranked[0]
    # For explored options (scenario_id is None), return a usable identifier dict
    # so the LLM can construct a propose_action call without guessing.
    if best_opt.get("scenario_id") is None:
        best_val = {
            "label": best_opt["label"],
            "offer_id": _offer_id_from_label(best_opt["label"]),
            "qty": best_opt.get("purchase_qty"),
            "include_transfers": _has_transfers(best_opt["label"]),
        }
    else:
        best_val = best_opt["scenario_id"]

    return {
        "objective": objective,
        "budget": budget,
        "ranked": ranked,
        "best": best_val,
    }


def _offer_id_from_label(label: str) -> str | None:
    """Extract the offer ID from an explore label like 'Buy 40 x OF02'."""
    import re
    m = re.search(r"\b(OF\d+)\b", label, re.IGNORECASE)
    return m.group(1) if m else None


def _has_transfers(label: str) -> bool:
    """Return True if the label indicates transfers are included."""
    return "transfers" in label.lower()
