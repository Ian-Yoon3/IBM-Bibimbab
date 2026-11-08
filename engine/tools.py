"""Agent-facing API layer.  All public functions return JSON-serialisable dicts.

The database is loaded once per ``data_dir`` and cached in ``_DB_CACHE``.
Pass ``data_dir=None`` to use the default ``engine/../data`` folder.

No function here approves or executes any action.
"""
import uuid
from pathlib import Path

from engine.loader import load_all
from engine.simulate import simulate, build_scenario_actions
from engine.evaluate import evaluate
from engine.candidates import transferable_qty, purchase_qty_options
from engine.analysis import disruption_impact, priority_view, marginal_cost
from engine.compare import rank_options

# ── db cache ──────────────────────────────────────────────────────────────────
_DB_CACHE: dict = {}


def _get_db(data_dir=None) -> dict:
    key = str(Path(data_dir).resolve()) if data_dir is not None else "__default__"
    if key not in _DB_CACHE:
        _DB_CACHE[key] = load_all(data_dir)
    return _DB_CACHE[key]


# ── public tool functions ─────────────────────────────────────────────────────

def get_disruption(disruption_id: str, data_dir=None) -> dict:
    """Return full details of a disruption including the affected PO and component.

    Parameters
    ----------
    disruption_id:
        ID of the disruption (e.g. ``"D01"``).
    data_dir:
        Optional path to the data directory. Defaults to the repo ``data/``.

    Returns
    -------
    dict with keys:
        disruption_id, po_id, reported_date, revised_receipt_date, reason,
        original_receipt_date, component_id, qty, delay_days
    """
    db = _get_db(data_dir)
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"Unknown disruption_id: {disruption_id!r}")

    dis = db["disruptions"][disruption_id]
    po = db["purchase_orders"][dis["po_id"]]
    offer = db["offers"][po["offer_id"]]

    delay_days = (dis["revised_receipt_date"] - po["planned_receipt_date"]).days

    return {
        "disruption_id": disruption_id,
        "po_id": dis["po_id"],
        "reported_date": dis["reported_date"].isoformat(),
        "original_receipt_date": po["planned_receipt_date"].isoformat(),
        "revised_receipt_date": dis["revised_receipt_date"].isoformat(),
        "delay_days": delay_days,
        "reason": dis["reason"],
        "component_id": offer["component_id"],
        "qty": po["qty"],
    }


def run_scenario(
    actions: list,
    disruption_id: str | None,
    data_dir=None,
) -> dict:
    """Simulate a set of recovery actions and return KPIs and order results.

    Parameters
    ----------
    actions:
        List of action dicts (``type: "purchase"`` or ``type: "transfer"``).
    disruption_id:
        Disruption to apply, or ``None`` for undisrupted baseline.
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    Merged dict of ``simulate()`` and ``evaluate()`` outputs, plus ``order_results``.
    """
    db = _get_db(data_dir)
    sim = simulate(actions, disruption_id, db)
    kpi = evaluate(sim)
    return {**kpi, "order_results": sim["order_results"],
            "end_inventory": sim["end_inventory"]}


def compare_scenarios(
    budget: int | None = None,
    objective: str = "on_time_orders",
    data_dir=None,
) -> dict:
    """Evaluate all five named scenarios and rank them.

    NORMAL (undisrupted baseline) is excluded from the ranking because it
    trivially dominates every disrupted option.  It is returned separately
    as ``"baseline"`` so the agent can report the undisrupted reference.

    Parameters
    ----------
    budget:
        Optional cost ceiling in USD.  Options exceeding it are excluded.
    objective:
        Ranking objective.  One of ``on_time_orders``, ``on_time_units``,
        ``total_late_days``, ``max_delay``, ``cost``.
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    ``rank_options()`` result dict (objective, budget, ranked list, best
    scenario_id) plus a ``"baseline"`` key containing NORMAL's KPI metrics.
    """
    db = _get_db(data_dir)
    options = []
    baseline = None
    for sid, scenario in db["scenarios"].items():
        actions, disruption_id = build_scenario_actions(sid, db)
        sim = simulate(actions, disruption_id, db)
        kpi = evaluate(sim)
        kpi["label"] = scenario["label"]
        kpi["scenario_id"] = sid
        if scenario["disruption_id"] is None:
            # Undisrupted baseline — return separately, not in ranking
            baseline = {k: v for k, v in kpi.items()}
            continue
        options.append(kpi)
    result = rank_options(options, objective=objective, budget=budget)
    result["baseline"] = baseline
    return result


def get_impact(disruption_id: str, data_dir=None) -> dict:
    """Analyse the impact of a disruption assuming no recovery actions.

    Parameters
    ----------
    disruption_id:
        ID of the disruption (e.g. ``"D01"``).
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    ``disruption_impact()`` result dict.
    """
    db = _get_db(data_dir)
    return disruption_impact(disruption_id, db)


def get_priority_view(
    actions: list | None = None,
    disruption_id: str | None = None,
    scenario_id: str | None = None,
    data_dir=None,
) -> dict:
    """Run a simulation and return the priority-1 order view.

    Parameters
    ----------
    actions:
        Recovery action list.  Ignored when ``scenario_id`` is provided.
    disruption_id:
        Disruption to apply, or ``None``.  Ignored when ``scenario_id`` is
        provided.
    scenario_id:
        Named scenario (e.g. ``"HYBRID"``).  When given, ``actions`` and
        ``disruption_id`` are resolved from the scenario data and the
        explicit parameters are ignored.
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    ``priority_view()`` result dict.
    """
    db = _get_db(data_dir)
    if scenario_id is not None:
        if scenario_id not in db["scenarios"]:
            raise ValueError(f"Unknown scenario_id: {scenario_id!r}")
        actions, disruption_id = build_scenario_actions(scenario_id, db)
    elif actions is None:
        actions = []
    sim = simulate(actions, disruption_id, db)
    return priority_view(sim, db)


def explore_purchase_qty(
    offer_id: str,
    include_transfers: bool = False,
    budget: int | None = None,
    objective: str = "on_time_orders",
    min_on_time_orders: int | None = None,
    data_dir=None,
) -> dict:
    """Sweep every valid purchase quantity for an offer and rank results.

    For each valid quantity (``min_qty`` to ``max_qty`` in steps of
    ``multiple_qty``), runs a simulation with that purchase action (using
    ``DAY0`` as the action date) and optionally combines it with all
    available transfers from ``candidates.transferable_qty()``.

    Parameters
    ----------
    offer_id:
        Supplier offer to explore (e.g. ``"OF02"``).
    include_transfers:
        If ``True``, add all transferable stock actions alongside each
        purchase quantity.
    budget:
        If set, options exceeding this cost are excluded from ranking.
    objective:
        Ranking objective.
    min_on_time_orders:
        If set, options with fewer on-time orders than this threshold are
        excluded before ranking.  Use to find the cheapest option that
        meets a target on-time count.
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    ``rank_options()`` result dict, with options labelled by purchase qty.
    """
    db = _get_db(data_dir)
    if offer_id not in db["offers"]:
        raise ValueError(f"Unknown offer_id: {offer_id!r}")

    offer = db["offers"][offer_id]
    qty_opts = purchase_qty_options(offer_id, db)
    DAY0_iso = db["DAY0"].isoformat()

    # Build transfer actions once (same for all purchase quantities)
    transfer_actions = []
    if include_transfers:
        for lane_info in transferable_qty(offer["component_id"], db):
            if lane_info["transferable_qty"] > 0:
                transfer_actions.append({
                    "type": "transfer",
                    "lane_id": lane_info["lane_id"],
                    "component_id": offer["component_id"],
                    "action_date": DAY0_iso,
                    "qty": lane_info["transferable_qty"],
                })

    # Find the disruption that affects the component (use first disruption found)
    # The offer's component should correspond to a known disruption
    disruption_id = None
    for did, dis in db["disruptions"].items():
        po = db["purchase_orders"][dis["po_id"]]
        po_offer = db["offers"][po["offer_id"]]
        if po_offer["component_id"] == offer["component_id"]:
            disruption_id = did
            break

    # Default to the first disruption if no component match found
    if disruption_id is None and db["disruptions"]:
        disruption_id = next(iter(db["disruptions"]))

    options = []
    for qty in qty_opts["valid_quantities"]:
        purchase_action = {
            "type": "purchase",
            "offer_id": offer_id,
            "warehouse_id": "WH01",  # production warehouse receives purchased goods
            "action_date": DAY0_iso,
            "qty": qty,
        }
        actions = [purchase_action] + transfer_actions
        sim = simulate(actions, disruption_id, db)
        kpi = evaluate(sim)
        if include_transfers and transfer_actions:
            kpi["label"] = f"Transfers + buy {qty} x {offer_id}"
        else:
            kpi["label"] = f"Buy {qty} x {offer_id}"
        kpi["option_type"] = "explored"
        kpi["scenario_id"] = None  # not a named scenario
        kpi["purchase_qty"] = qty
        kpi["actions"] = actions  # allow agent to pass to propose_action
        options.append(kpi)

    if min_on_time_orders is not None:
        options = [
            o for o in options
            if o.get("on_time_orders", 0) >= min_on_time_orders
        ]

    return rank_options(options, objective=objective, budget=budget)


def get_offers(disruption_id: str, data_dir=None) -> dict:
    """Return all supplier offers for the component affected by a disruption.

    Use this before ``explore_purchase_qty`` to discover valid offer IDs.

    Parameters
    ----------
    disruption_id:
        ID of the disruption (e.g. ``"D01"``).
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    dict with keys:
        disruption_id, component_id,
        offers (list of offer dicts with offer_id, supplier_id, lead_days,
        unit_cost_usd, fixed_fee_usd, min_qty, multiple_qty, max_qty)
    """
    db = _get_db(data_dir)
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"Unknown disruption_id: {disruption_id!r}")

    dis = db["disruptions"][disruption_id]
    po = db["purchase_orders"][dis["po_id"]]
    disrupted_offer_id = po["offer_id"]
    po_offer = db["offers"][disrupted_offer_id]
    component_id = po_offer["component_id"]

    offers = [
        {
            "offer_id": oid,
            "supplier_id": o["supplier_id"],
            "component_id": o["component_id"],
            "lead_days": o["lead_days"],
            "unit_cost_usd": o["unit_cost_usd"],
            "fixed_fee_usd": o["fixed_fee_usd"],
            "min_qty": o["min_qty"],
            "multiple_qty": o["multiple_qty"],
            "max_qty": o["max_qty"],
            "is_disrupted_supplier": oid == disrupted_offer_id,
        }
        for oid, o in db["offers"].items()
        if o["component_id"] == component_id
    ]

    return {
        "disruption_id": disruption_id,
        "component_id": component_id,
        "offers": offers,
    }


def propose_action(
    scenario_id_or_actions,
    reason: str,
    data_dir=None,
) -> dict:
    """Create a proposal dict for a recovery action plan.

    This function never executes or approves anything.  It evaluates the
    proposed actions, attaches metrics, and returns a proposal with
    ``status: "pending_approval"``.

    Parameters
    ----------
    scenario_id_or_actions:
        Either a named scenario ID string (e.g. ``"HYBRID"``) or an explicit
        list of action dicts.
    reason:
        Human-readable rationale for the proposal.
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    dict with keys:
        proposal_id, actions, disruption_id, metrics, reason,
        status ("pending_approval")
    """
    db = _get_db(data_dir)

    if isinstance(scenario_id_or_actions, str):
        scenario_id = scenario_id_or_actions
        if scenario_id not in db["scenarios"]:
            raise ValueError(f"Unknown scenario_id: {scenario_id!r}")
        actions, disruption_id = build_scenario_actions(scenario_id, db)
    else:
        actions = list(scenario_id_or_actions)
        # Use first disruption by default when raw actions are provided
        disruption_id = next(iter(db["disruptions"]), None)

    sim = simulate(actions, disruption_id, db)
    kpi = evaluate(sim)

    return {
        "proposal_id": str(uuid.uuid4()),
        "actions": actions,
        "disruption_id": disruption_id,
        "metrics": kpi,
        "reason": reason,
        "status": "pending_approval",
    }
