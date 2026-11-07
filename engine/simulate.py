"""Core day-forward supply chain simulation engine."""
from collections import Counter, defaultdict
from datetime import timedelta


def simulate(actions: list, disruption_id: str | None, db: dict) -> dict:
    """Simulate the supply chain for a given set of recovery actions.

    Parameters
    ----------
    actions:
        List of action dicts, each with ``"type"`` equal to ``"purchase"`` or
        ``"transfer"``.

        Purchase action keys:
            type, offer_id, warehouse_id, action_date (ISO str), qty

        Transfer action keys:
            type, lane_id, component_id, action_date (ISO str), qty

    disruption_id:
        ID of the disruption to apply (delays the affected PO), or ``None``
        for the undisrupted baseline.

    db:
        Database dict returned by ``loader.load_all()``.

    Returns
    -------
    dict with keys:
        order_results   – list of 12 per-order dicts
        purchase_cost   – int USD
        transfer_cost   – int USD
        total_extra_cost – int USD
        end_inventory   – {warehouse_id: {component_id: on_hand_qty}}
        ledger          – list of stock-movement dicts
    """
    DAY0 = db["DAY0"]
    HORIZON = db["HORIZON"]
    products = db["products"]
    warehouses = db["warehouses"]
    offers = db["offers"]
    purchase_orders = db["purchase_orders"]
    disruptions = db["disruptions"]
    lanes = db["lanes"]
    floor = db["floor"]
    opening = db["opening"]
    queue = db["queue"]
    needs = db["needs"]
    orders = db["orders"]
    components = db["components"]

    # ── mutable working stock (warehouse_id -> component_id -> qty) ───────────
    stock: dict[str, dict[str, int]] = {
        wid: dict(opening[wid]) for wid in warehouses
    }

    # ── event queue: date -> list of (kind, wid, cid, signed_qty, ref_id) ────
    events: dict = defaultdict(list)
    purchase_cost = 0
    transfer_cost = 0

    def schedule(when, kind, wid, cid, qty, ref):
        if not (DAY0 <= when <= HORIZON):
            raise ValueError(
                f"Event date {when} outside simulation window [{DAY0}, {HORIZON}]"
            )
        events[when].append((kind, wid, cid, qty, ref))

    # ── resolve disruption ────────────────────────────────────────────────────
    disruption = disruptions[disruption_id] if disruption_id else None

    # ── schedule existing purchase orders ─────────────────────────────────────
    for po_id, po in purchase_orders.items():
        affected = disruption is not None and disruption["po_id"] == po_id
        receipt_date = (
            disruption["revised_receipt_date"] if affected
            else po["planned_receipt_date"]
        )
        offer = offers[po["offer_id"]]
        schedule(receipt_date, "PO_RECEIPT", po["warehouse_id"],
                 offer["component_id"], po["qty"], po_id)

    # ── schedule recovery actions ─────────────────────────────────────────────
    moved_by_lane: Counter = Counter()
    for action in actions:
        atype = action.get("type")
        if atype == "purchase":
            offer_id = action["offer_id"]
            if offer_id not in offers:
                raise ValueError(f"Unknown offer_id: {offer_id!r}")
            offer = offers[offer_id]
            wid = action["warehouse_id"]
            if wid not in warehouses:
                raise ValueError(f"Unknown warehouse_id: {wid!r}")
            qty = int(action["qty"])
            _validate_offer_qty(offer, qty)
            action_date = _parse_date(action["action_date"])
            receipt_date = action_date + timedelta(days=offer["lead_days"])
            schedule(receipt_date, "ALT_RECEIPT", wid, offer["component_id"], qty, offer_id)
            purchase_cost += qty * offer["unit_cost_usd"] + offer["fixed_fee_usd"]

        elif atype == "transfer":
            lane_id = action["lane_id"]
            if lane_id not in lanes:
                raise ValueError(f"Unknown lane_id: {lane_id!r}")
            lane = lanes[lane_id]
            cid = action["component_id"]
            if cid not in components:
                raise ValueError(f"Unknown component_id: {cid!r}")
            qty = int(action["qty"])
            if qty <= 0:
                raise ValueError(f"Transfer qty must be > 0, got {qty}")
            moved_by_lane[lane_id] += qty
            if moved_by_lane[lane_id] > lane["max_qty"]:
                raise ValueError(
                    f"Lane {lane_id} total qty {moved_by_lane[lane_id]} "
                    f"exceeds max_qty {lane['max_qty']}"
                )
            action_date = _parse_date(action["action_date"])
            receipt_date = action_date + timedelta(days=lane["lead_days"])
            schedule(action_date, "TRANSFER_OUT",
                     lane["from_warehouse_id"], cid, -qty, lane_id)
            schedule(receipt_date, "TRANSFER_IN",
                     lane["to_warehouse_id"], cid, qty, lane_id)
            transfer_cost += qty * lane["unit_cost_usd"] + lane["fixed_fee_usd"]

        else:
            raise ValueError(f"Unknown action type: {atype!r}")

    # ── tracking counters for conservation checks ─────────────────────────────
    # in_transit[(lane_id, component_id)]: starts 0; OUT decrements (we negate
    # the signed qty), IN decrements back; must be 0 at end
    in_transit: Counter = Counter()
    external: dict[str, int] = Counter()   # component_id -> total inbound qty
    used: dict[str, int] = Counter()       # component_id -> total consumed qty (positive)
    ledger: list = []

    def post(when, kind, wid, cid, qty, ref):
        """Apply a stock change and record it in the ledger."""
        stock[wid][cid] += qty
        if stock[wid][cid] < floor[wid][cid]:
            raise RuntimeError(
                f"Inventory floor violated: stock[{wid}][{cid}]="
                f"{stock[wid][cid]} < floor {floor[wid][cid]} "
                f"(event {kind} ref={ref} on {when})"
            )
        if kind in ("PO_RECEIPT", "ALT_RECEIPT"):
            external[cid] += qty
        elif kind in ("TRANSFER_OUT", "TRANSFER_IN"):
            transit_key = (ref, cid)
            in_transit[transit_key] -= qty  # OUT has negative qty → +, IN has positive qty → -
            if in_transit[transit_key] < 0:
                raise RuntimeError(
                    f"in_transit went negative for {transit_key}: {in_transit[transit_key]}"
                )
        else:  # PRODUCTION_ISSUE
            used[cid] -= qty   # qty is negative; this adds the absolute amount

        ledger.append({
            "date": when.isoformat(),
            "event_type": kind,
            "reference_id": ref,
            "warehouse_id": wid,
            "component_id": cid,
            "signed_qty": qty,
            "on_hand_after": stock[wid][cid],
        })

    # ── main simulation loop ──────────────────────────────────────────────────
    starts: dict[str, object] = {}  # order_id -> date
    next_order = 0

    for offset in range((HORIZON - DAY0).days + 1):
        today = DAY0 + timedelta(days=offset)
        # Process all events for today: sort by qty descending (largest first)
        for kind, wid, cid, qty, ref in sorted(
            events[today], key=lambda x: -x[3]
        ):
            post(today, kind, wid, cid, qty, ref)

        # Attempt to start as many queued orders as possible
        while next_order < len(queue):
            oid = queue[next_order]
            order = orders[oid]
            wid = order["warehouse_id"]
            # Check all components have enough available stock
            if any(
                stock[wid][c] - floor[wid][c] < req_qty
                for c, req_qty in needs[oid].items()
            ):
                break  # Cannot start this order today; stop trying
            # Deduct all components
            for c, req_qty in needs[oid].items():
                post(today, "PRODUCTION_ISSUE", wid, c, -req_qty, oid)
            starts[oid] = today
            next_order += 1

    # ── post-simulation invariant checks ─────────────────────────────────────
    if any(in_transit.values()):
        bad = {k: v for k, v in in_transit.items() if v != 0}
        raise RuntimeError(f"In-transit transfers not fully received: {bad}")

    # Gross demand (total component needs across all orders)
    gross: Counter = Counter()
    for order_needs in needs.values():
        gross.update(order_needs)
    if used != gross:
        raise RuntimeError(
            f"Consumption mismatch: used={dict(used)}, gross={dict(gross)}"
        )

    for cid in components:
        total_end = sum(stock[wid][cid] for wid in warehouses)
        total_open = sum(opening[wid][cid] for wid in warehouses)
        if total_end != total_open + external[cid] - used[cid]:
            raise RuntimeError(
                f"Inventory conservation violated for {cid}: "
                f"end={total_end}, open={total_open}, "
                f"external={external[cid]}, used={used[cid]}"
            )

    # ── compile order results ─────────────────────────────────────────────────
    order_results = []
    for oid in queue:
        order = orders[oid]
        start = starts[oid]
        prod_days = products[order["product_id"]]["production_days"]
        delivery = start + timedelta(days=prod_days)
        due = order["due_date"]
        days_late = max(0, (delivery - due).days)
        c01_required = needs[oid].get("C01", 0)
        order_results.append({
            "order_id": oid,
            "product_id": order["product_id"],
            "qty": order["qty"],
            "due_date": due.isoformat(),
            "c01_required": c01_required,
            "start_date": start.isoformat(),
            "delivery_date": delivery.isoformat(),
            "days_late": days_late,
        })

    # ── end inventory ─────────────────────────────────────────────────────────
    end_inventory = {
        wid: {cid: stock[wid][cid] for cid in components}
        for wid in warehouses
    }

    return {
        "order_results": order_results,
        "purchase_cost": purchase_cost,
        "transfer_cost": transfer_cost,
        "total_extra_cost": purchase_cost + transfer_cost,
        "end_inventory": end_inventory,
        "ledger": ledger,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_date(value: str):
    from datetime import date
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid ISO date string: {value!r}") from exc


def _validate_offer_qty(offer: dict, qty: int) -> None:
    min_q = offer["min_qty"]
    max_q = offer["max_qty"]
    mul_q = offer["multiple_qty"]
    if not (0 < min_q <= qty <= max_q):
        raise ValueError(
            f"Offer {offer['offer_id']}: qty {qty} outside [{min_q}, {max_q}]"
        )
    if qty % mul_q != 0:
        raise ValueError(
            f"Offer {offer['offer_id']}: qty {qty} not a multiple of {mul_q}"
        )


def build_scenario_actions(scenario_id: str, db: dict) -> tuple[list, str | None]:
    """Convert a named scenario from the CSV data into (actions, disruption_id).

    This is a convenience function used by tools.py and tests to reproduce
    the five named scenarios without hardcoding anything.
    """
    scenario = db["scenarios"][scenario_id]
    disruption_id = scenario["disruption_id"]  # may be None

    actions = []

    # Recovery purchases for this scenario
    for (sid, offer_id), rp in db["recovery_purchases"].items():
        if sid != scenario_id:
            continue
        actions.append({
            "type": "purchase",
            "offer_id": offer_id,
            "warehouse_id": rp["warehouse_id"],
            "action_date": rp["action_date"].isoformat(),
            "qty": rp["qty"],
        })

    # Recovery transfers for this scenario
    for (sid, lane_id, cid), rt in db["recovery_transfers"].items():
        if sid != scenario_id:
            continue
        actions.append({
            "type": "transfer",
            "lane_id": lane_id,
            "component_id": cid,
            "action_date": rt["action_date"].isoformat(),
            "qty": rt["qty"],
        })

    return actions, disruption_id
