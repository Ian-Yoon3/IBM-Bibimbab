"""Enumerate valid action candidates without running a simulation."""


def transferable_qty(component_id: str, db: dict) -> list:
    """Return transferable qty per lane for a given component into the production warehouse.

    For each transfer lane, computes:
        transferable = min(on_hand - reserved - protected at source, lane max_qty)

    Only lanes whose destination is a PRODUCTION warehouse are returned.

    Parameters
    ----------
    component_id:
        The component to transfer (e.g. ``"C01"``).
    db:
        Database dict from ``loader.load_all()``.

    Returns
    -------
    List of dicts, one per lane:
        lane_id, from_warehouse_id, to_warehouse_id, component_id,
        available_at_source, lane_max_qty, transferable_qty
    """
    if component_id not in db["components"]:
        raise ValueError(f"Unknown component_id: {component_id!r}")

    results = []
    for lane_id, lane in db["lanes"].items():
        from_wid = lane["from_warehouse_id"]
        to_wid = lane["to_warehouse_id"]

        # Only include lanes that deliver to a PRODUCTION warehouse
        if db["warehouses"][to_wid]["role"] != "PRODUCTION":
            continue

        inv = db["inventory"][(from_wid, component_id)]
        available = inv["on_hand_qty"] - inv["reserved_qty"] - inv["protected_qty"]
        max_q = lane["max_qty"]
        transferable = min(available, max_q)

        results.append({
            "lane_id": lane_id,
            "from_warehouse_id": from_wid,
            "to_warehouse_id": to_wid,
            "component_id": component_id,
            "available_at_source": available,
            "lane_max_qty": max_q,
            "transferable_qty": transferable,
        })

    return results


def purchase_qty_options(offer_id: str, db: dict) -> dict:
    """Return all valid order quantities for a supplier offer.

    Valid quantities are every integer from ``min_qty`` to ``max_qty``
    (inclusive) that is a multiple of ``multiple_qty``.

    Parameters
    ----------
    offer_id:
        Offer identifier (e.g. ``"OF02"``).
    db:
        Database dict from ``loader.load_all()``.

    Returns
    -------
    dict with keys:
        offer_id, supplier_id, component_id, lead_days,
        unit_cost_usd, fixed_fee_usd, min_qty, multiple_qty, max_qty,
        valid_quantities (list of int)
    """
    if offer_id not in db["offers"]:
        raise ValueError(f"Unknown offer_id: {offer_id!r}")

    offer = db["offers"][offer_id]
    min_q = offer["min_qty"]
    max_q = offer["max_qty"]
    mul_q = offer["multiple_qty"]

    valid = list(range(min_q, max_q + 1, mul_q))

    return {
        "offer_id": offer_id,
        "supplier_id": offer["supplier_id"],
        "component_id": offer["component_id"],
        "lead_days": offer["lead_days"],
        "unit_cost_usd": offer["unit_cost_usd"],
        "fixed_fee_usd": offer["fixed_fee_usd"],
        "min_qty": min_q,
        "multiple_qty": mul_q,
        "max_qty": max_q,
        "valid_quantities": valid,
    }
