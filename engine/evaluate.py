"""Compute KPI summary from a simulate() result."""

HORIZON_ISO = "2026-11-21"


def evaluate(sim_result: dict) -> dict:
    """Compute KPI summary metrics from a ``simulate()`` return value.

    Parameters
    ----------
    sim_result:
        Dict returned by ``simulate()``.

    Returns
    -------
    dict with keys:
        on_time_orders              – count of orders with days_late == 0
        late_orders                 – count of orders with days_late > 0
        total_orders                – count of orders in the simulation
        on_time_units               – sum of qty for on-time orders
        orders_completed_by_horizon – count of orders delivered by 2026-11-21
        total_order_days_late       – sum of days_late (no qty weighting)
        max_order_days_late         – max days_late
        purchase_cost               – int USD (from simulate)
        transfer_cost               – int USD (from simulate)
        total_extra_cost            – int USD (from simulate)
        end_c01                     – {warehouse_id: qty} for C01 only
    """
    order_results = sim_result["order_results"]

    on_time_orders = sum(1 for r in order_results if r["days_late"] == 0)
    late_orders = sum(1 for r in order_results if r["days_late"] > 0)
    total_orders = len(order_results)
    on_time_units = sum(r["qty"] for r in order_results if r["days_late"] == 0)
    orders_completed_by_horizon = sum(
        1 for r in order_results if r["delivery_date"] <= HORIZON_ISO
    )
    late_days = [r["days_late"] for r in order_results]
    total_order_days_late = sum(late_days)
    max_order_days_late = max(late_days) if late_days else 0

    end_inv = sim_result["end_inventory"]
    end_c01 = {wid: end_inv[wid]["C01"] for wid in sorted(end_inv)}

    return {
        "on_time_orders": on_time_orders,
        "late_orders": late_orders,
        "total_orders": total_orders,
        "on_time_units": on_time_units,
        "orders_completed_by_horizon": orders_completed_by_horizon,
        "total_order_days_late": total_order_days_late,
        "max_order_days_late": max_order_days_late,
        "purchase_cost": sim_result["purchase_cost"],
        "transfer_cost": sim_result["transfer_cost"],
        "total_extra_cost": sim_result["total_extra_cost"],
        "end_c01": end_c01,
    }
