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
from engine.worlds import evaluate_worlds

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
        "scope_note": (
            f"Only disruption {disruption_id} with its recorded delay of "
            f"{delay_days} days is modelled. Hypothetical delays or new "
            f"disruptions are not supported yet and cannot be simulated."
        ),
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
    offer_id: str | None = None,
    qty: int | None = None,
    include_transfers: bool = False,
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
    offer_id, qty, include_transfers:
        An explored option, as returned by ``explore_purchase_qty``.  Used
        when ``scenario_id`` is not given and ``offer_id`` and ``qty`` are.

    Returns
    -------
    ``priority_view()`` result dict.
    """
    db = _get_db(data_dir)
    if scenario_id is not None or offer_id is not None:
        actions, disruption_id, _ = _resolve_option(
            db, scenario_id, offer_id, qty, include_transfers
        )
    elif actions is None:
        actions = []
    sim = simulate(actions, disruption_id, db)
    return priority_view(sim, db)


def _disruption_for_offer(db: dict, offer_id: str):
    """Return the disruption that affects the offer's component (or the first one)."""
    component = db["offers"][offer_id]["component_id"]
    for did, dis in db["disruptions"].items():
        po = db["purchase_orders"][dis["po_id"]]
        if db["offers"][po["offer_id"]]["component_id"] == component:
            return did
    return next(iter(db["disruptions"]), None)


def _explored_actions(db: dict, offer_id: str, qty: int, include_transfers: bool) -> list:
    """Build the action list for one explored option.

    Mirrors ``explore_purchase_qty``: a purchase on DAY0 into WH01 and, when
    requested, every transferable quantity for the offer's component.
    """
    if offer_id not in db["offers"]:
        raise ValueError(f"Unknown offer_id: {offer_id!r}")
    valid = purchase_qty_options(offer_id, db)["valid_quantities"]
    if qty not in valid:
        raise ValueError(
            f"qty {qty!r} is not a valid quantity for {offer_id}; valid: {valid}"
        )
    day0 = db["DAY0"].isoformat()
    component = db["offers"][offer_id]["component_id"]
    actions = [{
        "type": "purchase",
        "offer_id": offer_id,
        "warehouse_id": "WH01",
        "action_date": day0,
        "qty": qty,
    }]
    if include_transfers:
        for lane in transferable_qty(component, db):
            if lane["transferable_qty"] > 0:
                actions.append({
                    "type": "transfer",
                    "lane_id": lane["lane_id"],
                    "component_id": component,
                    "action_date": day0,
                    "qty": lane["transferable_qty"],
                })
    return actions


def _resolve_option(db, scenario_id=None, offer_id=None, qty=None, include_transfers=False):
    """Return (actions, disruption_id, option_label) for a named or explored option.

    With neither ``scenario_id`` nor ``offer_id`` the option is WAIT.
    """
    if scenario_id is None and offer_id is None:
        scenario_id = "WAIT"
    if scenario_id is not None:
        if scenario_id not in db["scenarios"]:
            raise ValueError(f"Unknown scenario_id: {scenario_id!r}")
        actions, disruption_id = build_scenario_actions(scenario_id, db)
        return actions, disruption_id, scenario_id
    if qty is None:
        raise ValueError("qty is required with offer_id")
    actions = _explored_actions(db, offer_id, qty, include_transfers)
    label = f"{'Transfers + buy' if include_transfers else 'Buy'} {qty} x {offer_id}"
    return actions, _disruption_for_offer(db, offer_id), label


def get_order_detail(
    order_id: str,
    scenario_id: str | None = None,
    offer_id: str | None = None,
    qty: int | None = None,
    include_transfers: bool = False,
    data_dir=None,
) -> dict:
    """Explain when an order starts and, if it is late, why.

    The option is a named scenario, an explored option (offer_id + qty +
    include_transfers), or WAIT when neither is given.

    Production is queue-ordered and all-or-nothing: on each day orders start
    in queue order until one lacks a component, and every later order waits.
    So a late order is either blocked by an earlier order in the queue, or
    is itself short of a component on its latest on-time start date.

    Returns
    -------
    dict with keys:
        option, order_id, customer_id, product_id, qty, priority_rank,
        due_date, latest_start_date, start_date, delivery_date, days_late,
        components_needed, cause, summary (one plain-English sentence built
        from the other fields, so the LLM can quote it instead of paraphrasing)
    ``cause`` is ``{"type": "on_time"}``, or for late orders
    ``{"type": "queue_blocked" | "component_shortage", "check_date",
    "waiting_order_id", "shortfall": {component_id: missing_qty}}`` where
    ``waiting_order_id`` is the order at the head of the queue on
    ``check_date`` and ``shortfall`` is what that order lacked that day.
    """
    from datetime import date, timedelta

    db = _get_db(data_dir)
    if order_id not in db["orders"]:
        raise ValueError(f"Unknown order_id: {order_id!r}")
    actions, disruption_id, label = _resolve_option(
        db, scenario_id, offer_id, qty, include_transfers
    )
    sim = simulate(actions, disruption_id, db)

    order = db["orders"][order_id]
    result = next(r for r in sim["order_results"] if r["order_id"] == order_id)
    prod_days = db["products"][order["product_id"]]["production_days"]
    latest_start = max(db["DAY0"], order["due_date"] - timedelta(days=prod_days))

    detail = {
        "option": label,
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "product_id": order["product_id"],
        "qty": order["qty"],
        "priority_rank": order["priority_rank"],
        "due_date": order["due_date"].isoformat(),
        "latest_start_date": latest_start.isoformat(),
        "start_date": result["start_date"],
        "delivery_date": result["delivery_date"],
        "days_late": result["days_late"],
        "components_needed": dict(db["needs"][order_id]),
    }
    if result["days_late"] == 0:
        detail["cause"] = {"type": "on_time"}
        detail["summary"] = (
            f"{order_id} is on time under {label}: it starts on "
            f"{result['start_date']} and is delivered on {result['delivery_date']} "
            f"(due {detail['due_date']})."
        )
        return detail

    # Head of the queue on the latest on-time start date: the first order in
    # queue order that had not started by the end of that day.
    starts = {r["order_id"]: date.fromisoformat(r["start_date"])
              for r in sim["order_results"] if r["start_date"]}
    head = next(
        (oid for oid in db["queue"]
         if oid not in starts or starts[oid] > latest_start),
        order_id,
    )

    # Usable stock at the order's warehouse at the end of that day.
    wid = db["orders"][head]["warehouse_id"]
    on_hand = dict(db["opening"][wid])
    for ev in sim["ledger"]:
        if ev["warehouse_id"] == wid and ev["date"] <= latest_start.isoformat():
            on_hand[ev["component_id"]] = ev["on_hand_after"]
    shortfall = {}
    for cid, need in db["needs"][head].items():
        usable = on_hand[cid] - db["floor"][wid][cid]
        if usable < need:
            shortfall[cid] = need - usable

    detail["cause"] = {
        "type": "component_shortage" if head == order_id else "queue_blocked",
        "check_date": latest_start.isoformat(),
        "waiting_order_id": head,
        "shortfall": shortfall,
    }
    lacked = ", ".join(f"{q} x {c}" for c, q in shortfall.items()) or "nothing"
    n = result["days_late"]
    days = f"{n} day{'s' if n != 1 else ''} late"
    if head == order_id:
        why = f"it lacked {lacked}"
    else:
        why = (f"it was waiting in the production queue behind {head}, "
               f"which lacked {lacked}")
    detail["summary"] = (
        f"{order_id} is {days} under {label}. On {latest_start.isoformat()}, "
        f"its latest on-time start date, {why}. It starts on "
        f"{result['start_date']} and is delivered on {result['delivery_date']} "
        f"(due {detail['due_date']})."
    )
    return detail


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


def get_scenario_actions(scenario_id: str, data_dir=None) -> dict:
    """Return the action list and disruption of a named scenario.

    Read-only.  Used by the agent layer to describe and simulate named
    options without importing engine internals.
    """
    db = _get_db(data_dir)
    if scenario_id not in db["scenarios"]:
        raise ValueError(f"Unknown scenario_id: {scenario_id!r}")
    actions, disruption_id = build_scenario_actions(scenario_id, db)
    return {"scenario_id": scenario_id, "disruption_id": disruption_id,
            "actions": actions}


def get_catalog(data_dir=None) -> dict:
    """Return display names for suppliers, components, warehouses, products,
    and the supplier and component of each offer and lane.

    Read-only.  Lets the agent layer show "Beacon Circuits" instead of "S02".
    """
    db = _get_db(data_dir)
    return {
        "suppliers": {k: v["supplier_name"] for k, v in db["suppliers"].items()},
        "components": {k: v["component_name"] for k, v in db["components"].items()},
        "warehouses": {k: v["warehouse_name"] for k, v in db["warehouses"].items()},
        "products": {k: v["product_name"] for k, v in db["products"].items()},
        "offers": {k: {"supplier_id": v["supplier_id"],
                       "component_id": v["component_id"]}
                   for k, v in db["offers"].items()},
        "lanes": {k: {"from": v["from_warehouse_id"], "to": v["to_warehouse_id"],
                      "lead_days": v["lead_days"]}
                  for k, v in db["lanes"].items()},
        "orders": {k: {"customer_id": v["customer_id"],
                       "priority_rank": v["priority_rank"],
                       "due_date": v["due_date"].isoformat()}
                   for k, v in db["orders"].items()},
    }


def get_world_risk(disruption_id: str, data_dir=None) -> dict:
    """Evaluate all disrupted scenarios across possible worlds and return
    a summary of time-cost trade-offs under receipt-date uncertainty.

    Parameters
    ----------
    disruption_id:
        ID of the disruption to analyse (e.g. ``"D01"``).
    data_dir:
        Optional path override for the data directory.

    Returns
    -------
    dict with keys:
        disruption_id       – str, echoes the input
        po_id               – str, PO affected by the disruption
        announced_receipt_date – ISO date str, the disruption's revised date
        weights_source      – ``"file"`` when worlds.csv is present,
                              ``"announced_date"`` otherwise
        world_count         – int, number of worlds evaluated
        quantile_level      – float, 0.9 (90th percentile)
        options             – list of per-scenario dicts with:
                                scenario_id, label, extra_cost,
                                expected_late_orders, worst_late_orders,
                                p90_late_orders, p_no_late_pct
        what_if             – dict with keys:
                                dates (list of ISO date strs),
                                late_orders (scenario_id -> list of int)
        tradeoff_steps      – list of consecutive option-pair dicts with:
                                from, to, extra_cost_change,
                                expected_late_change, worst_late_change,
                                p90_late_change, p_no_late_pct_change
        scope_note          – str, note about the weights source and engine role

    Raises ValueError for an unknown disruption_id.
    """
    _SCOPE_NOTES = {
        "file": (
            "Weights come from data/worlds.csv. Each world is one possible receipt"
            " date of the delayed PO. Time and cost are shown side by side."
            " The engine does not pick an option."
        ),
        "announced_date": (
            "No world files. The announced receipt date has full weight."
            " Time and cost are shown side by side."
            " The engine does not pick an option."
        ),
    }
    result = evaluate_worlds(disruption_id, _get_db(data_dir))
    result["scope_note"] = _SCOPE_NOTES[result["weights_source"]]
    return result


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
