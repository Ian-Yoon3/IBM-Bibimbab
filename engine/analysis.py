"""Read-only analysis functions over disruption data and simulation results."""
from datetime import timedelta

from engine.simulate import simulate


def disruption_impact(disruption_id: str, db: dict) -> dict:
    """Analyse the impact of a disruption with no recovery actions (WAIT baseline).

    Runs ``simulate([], disruption_id, db)`` internally and reports:
    - Which order is first to be late
    - Full list of late orders
    - Per-day C01 shortage table at WH01

    The per-day shortage is the cumulative C01 needed by all orders whose
    *latest allowable start date* (``due_date - production_days``) is on or
    before that day, minus the C01 available at WH01 on that day (on_hand at
    opening, plus any receipts up to and including that day), floored at 0.

    Parameters
    ----------
    disruption_id:
        ID of the disruption to evaluate.
    db:
        Database dict from ``loader.load_all()``.

    Returns
    -------
    dict with keys:
        disruption_id, first_late_order_id, first_late_days,
        late_orders (list), c01_shortage_by_day (list of day dicts)
    """
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"Unknown disruption_id: {disruption_id!r}")

    sim = simulate([], disruption_id, db)

    # ── late order analysis ───────────────────────────────────────────────────
    late_orders = []
    first_late_order_id = None
    first_late_days = 0
    for row in sim["order_results"]:
        if row["days_late"] > 0:
            if first_late_order_id is None:
                first_late_order_id = row["order_id"]
                first_late_days = row["days_late"]
            late_orders.append({
                "order_id": row["order_id"],
                "due_date": row["due_date"],
                "delivery_date": row["delivery_date"],
                "days_late": row["days_late"],
            })

    # ── C01 shortage table at WH01 ────────────────────────────────────────────
    DAY0 = db["DAY0"]
    HORIZON = db["HORIZON"]
    products = db["products"]
    orders = db["orders"]
    queue = db["queue"]
    needs = db["needs"]
    disruption = db["disruptions"][disruption_id]

    # Reconstruct daily C01 available at WH01:
    # start with opening on_hand, add receipts day by day
    c01_wh01_daily: dict = {}
    running = db["opening"]["WH01"]["C01"]
    for offset in range((HORIZON - DAY0).days + 1):
        today = DAY0 + timedelta(days=offset)
        # Add any C01 receipts at WH01 on this day (from PO or disruption)
        for po_id, po in db["purchase_orders"].items():
            offer = db["offers"][po["offer_id"]]
            if offer["component_id"] != "C01" or po["warehouse_id"] != "WH01":
                continue
            affected = disruption["po_id"] == po_id
            receipt_date = (
                disruption["revised_receipt_date"] if affected
                else po["planned_receipt_date"]
            )
            if receipt_date == today:
                running += po["qty"]
        c01_wh01_daily[today] = running

    # Cumulative C01 needed by orders whose latest start ≤ today
    # latest_start = due_date - production_days
    cumulative_needed = 0
    c01_shortage_by_day = []
    for offset in range((HORIZON - DAY0).days + 1):
        today = DAY0 + timedelta(days=offset)
        for oid in queue:
            order = orders[oid]
            prod_days = products[order["product_id"]]["production_days"]
            latest_start = order["due_date"] - timedelta(days=prod_days)
            if latest_start == today:
                cumulative_needed += needs[oid].get("C01", 0)
        available = c01_wh01_daily[today]
        shortage = max(0, cumulative_needed - available)
        c01_shortage_by_day.append({
            "date": today.isoformat(),
            "c01_available_wh01": available,
            "c01_cumulative_needed": cumulative_needed,
            "shortage": shortage,
        })

    return {
        "disruption_id": disruption_id,
        "first_late_order_id": first_late_order_id,
        "first_late_days": first_late_days,
        "late_orders": late_orders,
        "c01_shortage_by_day": c01_shortage_by_day,
    }


def priority_view(sim_result: dict, db: dict) -> dict:
    """Summarise results for priority-rank 1 orders and per-customer impact.

    Parameters
    ----------
    sim_result:
        Dict returned by ``simulate()``.
    db:
        Database dict from ``loader.load_all()``.

    Returns
    -------
    dict with keys:
        priority_1_orders   – list of per-order dicts for rank-1 orders
        on_time_count       – int, number of on-time priority-1 orders
        total_count         – int, total priority-1 orders
        customer_impact     – {customer_id: {orders, late_orders, total_late_days}}
    """
    orders_db = db["orders"]

    priority_1_orders = []
    customer_impact: dict = {}

    for row in sim_result["order_results"]:
        oid = row["order_id"]
        order = orders_db[oid]
        if order["priority_rank"] != 1:
            continue

        priority_1_orders.append({
            "order_id": oid,
            "customer_id": order["customer_id"],
            "due_date": row["due_date"],
            "start_date": row["start_date"],
            "delivery_date": row["delivery_date"],
            "days_late": row["days_late"],
            "qty": row["qty"],
        })

        cid = order["customer_id"]
        if cid not in customer_impact:
            customer_impact[cid] = {"orders": 0, "late_orders": 0, "total_late_days": 0}
        customer_impact[cid]["orders"] += 1
        if row["days_late"] > 0:
            customer_impact[cid]["late_orders"] += 1
            customer_impact[cid]["total_late_days"] += row["days_late"]

    on_time_count = sum(1 for r in priority_1_orders if r["days_late"] == 0)

    return {
        "priority_1_orders": priority_1_orders,
        "on_time_count": on_time_count,
        "total_count": len(priority_1_orders),
        "customer_impact": customer_impact,
    }


def marginal_cost(results: list) -> dict:
    """Compute cost per incremental on-time order between adjacent options.

    Parameters
    ----------
    results:
        List of dicts, each with at minimum:
        ``label`` (str), ``on_time_orders`` (int), ``total_extra_cost`` (int).
        Typically the output of ``evaluate()`` with a ``"label"`` key added.

    Returns
    -------
    dict with key ``steps``, a list of step dicts:
        from_label, to_label, extra_on_time_orders, extra_cost_usd,
        cost_per_order_usd (float or None if no new on-time orders)
    """
    # Sort by total_extra_cost ascending, then on_time_orders ascending
    sorted_opts = sorted(results, key=lambda r: (r["total_extra_cost"], -r["on_time_orders"]))

    steps = []
    for i in range(1, len(sorted_opts)):
        prev = sorted_opts[i - 1]
        curr = sorted_opts[i]
        extra_orders = curr["on_time_orders"] - prev["on_time_orders"]
        extra_cost = curr["total_extra_cost"] - prev["total_extra_cost"]
        cost_per_order = (
            extra_cost / extra_orders if extra_orders > 0 else None
        )
        steps.append({
            "from_label": prev["label"],
            "to_label": curr["label"],
            "extra_on_time_orders": extra_orders,
            "extra_cost_usd": extra_cost,
            "cost_per_order_usd": cost_per_order,
        })

    return {"steps": steps}
