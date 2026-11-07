"""Replay Baseline V1 CSV inputs and check against fixed, hand-derived expectations."""
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from sys import argv

ROOT = Path(__file__).resolve().parent
DAY0 = date(2026, 11, 9)
HORIZON = DAY0 + timedelta(days=12)

def load(name, *keys):
    with (ROOT / "data" / f"{name}.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    result = {}
    for row in rows:
        assert None not in row and all(v not in (None, "") for k, v in row.items()
                                       if (name, k) != ("scenarios", "disruption_id")), (name, row)
        key = tuple(row[k] for k in keys)
        assert key not in result, (name, key)
        result[key[0] if len(key) == 1 else key] = row
    return result

def number(row, key):
    value = int(row[key])
    assert value >= 0, (key, row)
    return value

def day(row, key):
    return date.fromisoformat(row[key])

def offer_qty(offer, qty):
    assert 0 < number(offer, "min_qty") <= qty <= number(offer, "max_qty")
    assert qty % number(offer, "multiple_qty") == 0

products = load("products", "product_id")
components = load("components", "component_id")
suppliers = load("suppliers", "supplier_id")
warehouses = load("warehouses", "warehouse_id")
orders = load("orders", "order_id")
assert tuple(map(len, (products, components, suppliers, warehouses, orders))) == (3, 5, 4, 3, 12)
assert all(row["uom"] == "EA" for row in components.values())
bom = defaultdict(dict)
for (p, c), row in load("bom", "product_id", "component_id").items():
    assert p in products and c in components and number(row, "qty_per_unit") > 0
    bom[p][c] = number(row, "qty_per_unit")
assert set(bom) == products.keys()
assert [tuple(bom[p].get(c, 0) for c in sorted(components)) for p in sorted(products)] == [
    (1, 2, 1, 0, 1), (2, 0, 1, 1, 1), (1, 0, 2, 2, 1)]
inventory = load("inventory", "warehouse_id", "component_id")
assert inventory.keys() == {(w, c) for w in warehouses for c in components}
floor = {k: number(r, "reserved_qty") + number(r, "protected_qty") for k, r in inventory.items()}
opening = {k: number(r, "on_hand_qty") for k, r in inventory.items()}
assert all(opening[k] >= floor[k] for k in opening)
offers = load("supplier_offers", "offer_id")
for r in offers.values():
    assert r["supplier_id"] in suppliers and r["component_id"] in components
    assert number(r, "lead_days") > 0
    number(r, "unit_cost_usd")
    number(r, "fixed_fee_usd")
pos = load("purchase_orders", "po_id")
for r in pos.values():
    assert r["warehouse_id"] in warehouses
    offer = offers[r["offer_id"]]
    offer_qty(offer, number(r, "qty"))
    assert day(r, "order_date") < DAY0 <= day(r, "planned_receipt_date")
    assert day(r, "order_date") + timedelta(days=number(offer, "lead_days")) == day(r, "planned_receipt_date")
disruptions = load("disruptions", "disruption_id")
for r in disruptions.values():
    assert day(r, "reported_date") == DAY0
    assert day(r, "revised_receipt_date") > day(pos[r["po_id"]], "planned_receipt_date")
lanes = load("transfer_lanes", "lane_id")
for r in lanes.values():
    assert r["from_warehouse_id"] in warehouses and r["to_warehouse_id"] in warehouses
    assert r["from_warehouse_id"] != r["to_warehouse_id"] and number(r, "lead_days") > 0
scenarios = load("scenarios", "scenario_id")
purchases = load("recovery_purchases", "scenario_id", "offer_id")
transfers = load("recovery_transfers", "scenario_id", "lane_id", "component_id")
assert all(k[0] in scenarios for k in (*purchases, *transfers))
for r in orders.values():
    assert warehouses[r["warehouse_id"]]["role"] == "PRODUCTION"
    assert r["product_id"] in products and number(r, "qty") > 0
    assert DAY0 <= day(r, "due_date") <= HORIZON and number(r, "priority_rank") > 0
queue = sorted(orders, key=lambda k: (day(orders[k], "due_date"), number(orders[k], "priority_rank"), k))
needs = {k: {c: amount * number(orders[k], "qty")
             for c, amount in bom[orders[k]["product_id"]].items()} for k in queue}
gross = Counter()
for need in needs.values():
    gross.update(need)
assert dict(sorted(gross.items())) == dict(zip(sorted(components), (163, 92, 166, 120, 125)))

# Independent expectations: first cumulative C01 thresholds are 12, 32, 40,
# 55, 73, 87, 95. Other plant components cover the entire demand from DAY0.
# Each vector is the first day each threshold can be met in strict queue order.
expected_starts = {
    "NORMAL": [0] + [2] * 11,
    "WAIT": [0] + [8] * 11,
    "TRANSFER": [0, 2, 2, 4] + [8] * 8,
    "ALT_BUY": [0] + [3] * 5 + [8] * 6,
    "HYBRID": [0, 2, 2, 3, 3, 3, 4] + [8] * 5,
}
expected_costs = {"NORMAL": (0, 0), "WAIT": (0, 0), "TRANSFER": (0, 416),
                  "ALT_BUY": (1250, 0), "HYBRID": (890, 416)}
assert queue == [f"SO{i:02}" for i in range(1, 13)]
assert scenarios.keys() == expected_starts.keys()
detail, summaries, ledger, audits = [], [], [], []

def simulate(sid, scenario):
    stock = opening.copy()
    events = defaultdict(list)
    in_transit = Counter()
    external = Counter()
    used = Counter()
    purchase_cost = transfer_cost = 0
    disruption = disruptions[scenario["disruption_id"]] if scenario["disruption_id"] else None

    def schedule(when, kind, key, qty, ref):
        assert DAY0 <= when <= HORIZON
        events[when].append((kind, key, qty, ref))

    for po_id, r in pos.items():
        affected = disruption and disruption["po_id"] == po_id
        receipt = day(disruption, "revised_receipt_date") if affected else day(r, "planned_receipt_date")
        key = (r["warehouse_id"], offers[r["offer_id"]]["component_id"])
        schedule(receipt, "PO_RECEIPT", key, number(r, "qty"), po_id)
    for (s, offer_id), r in purchases.items():
        if s != sid:
            continue
        offer = offers[offer_id]
        qty = number(r, "qty")
        offer_qty(offer, qty)
        action_date = day(r, "action_date")
        assert action_date >= DAY0
        receipt = action_date + timedelta(days=number(offer, "lead_days"))
        schedule(receipt, "ALT_RECEIPT", (r["warehouse_id"], offer["component_id"]), qty, offer_id)
        purchase_cost += qty * number(offer, "unit_cost_usd") + number(offer, "fixed_fee_usd")
    moved_by_lane = Counter()
    for (s, lane_id, c), r in transfers.items():
        if s != sid:
            continue
        lane = lanes[lane_id]
        qty = number(r, "qty")
        moved_by_lane[lane_id] += qty
        assert 0 < qty and moved_by_lane[lane_id] <= number(lane, "max_qty")
        dispatch = day(r, "action_date")
        receipt = dispatch + timedelta(days=number(lane, "lead_days"))
        schedule(dispatch, "TRANSFER_OUT", (lane["from_warehouse_id"], c), -qty, lane_id)
        schedule(receipt, "TRANSFER_IN", (lane["to_warehouse_id"], c), qty, lane_id)
        transfer_cost += qty * number(lane, "unit_cost_usd") + number(lane, "fixed_fee_usd")

    def post(when, kind, key, qty, ref):
        stock[key] += qty
        assert stock[key] >= floor[key], (sid, when, key, stock[key])
        c = key[1]
        if kind in ("PO_RECEIPT", "ALT_RECEIPT"):
            external[c] += qty
        elif kind in ("TRANSFER_OUT", "TRANSFER_IN"):
            transit_key = (ref, c)
            in_transit[transit_key] -= qty
            assert in_transit[transit_key] >= 0
        else:
            used[c] -= qty
        ledger.append((sid, when, kind, ref, *key, qty, stock[key]))

    starts = {}
    next_order = 0
    for offset in range((HORIZON - DAY0).days + 1):
        today = DAY0 + timedelta(days=offset)
        for kind, key, qty, ref in sorted(events[today], key=lambda x: -x[2]):
            post(today, kind, key, qty, ref)
        while next_order < len(queue):
            oid = queue[next_order]
            w = orders[oid]["warehouse_id"]
            if any(stock[w, c] - floor[w, c] < qty for c, qty in needs[oid].items()):
                break
            for c, qty in needs[oid].items():
                post(today, "PRODUCTION_ISSUE", (w, c), -qty, oid)
            starts[oid] = today
            next_order += 1
    assert not any(in_transit.values())
    assert used == gross
    for c in components:
        assert sum(stock[w, c] for w in warehouses) == sum(opening[w, c] for w in warehouses) + external[c] - used[c]
    assert [(starts[k] - DAY0).days for k in queue] == expected_starts[sid]
    assert (purchase_cost, transfer_cost) == expected_costs[sid]
    late_days = []
    on_time_units = by_horizon = 0
    for oid in queue:
        r = orders[oid]
        start = starts[oid]
        end = start + timedelta(days=number(products[r["product_id"]], "production_days"))
        due = day(r, "due_date")
        late = max(0, (end - due).days)
        late_days.append(late)
        on_time_units += number(r, "qty") if late == 0 else 0
        by_horizon += end <= HORIZON
        detail.append((sid, oid, r["product_id"], r["qty"], due, needs[oid]["C01"], start, end, late))
    summaries.append((sid, len(queue) - sum(n > 0 for n in late_days), on_time_units, by_horizon,
                      sum(late_days), max(late_days), purchase_cost, transfer_cost,
                      purchase_cost + transfer_cost, *(stock[w, "C01"] for w in sorted(warehouses))))
    audits.append((sid, "PASS", "PASS", "PASS"))

for scenario_id, scenario_row in scenarios.items():
    simulate(scenario_id, scenario_row)

def write(name, header, rows):
    with (ROOT / "validation" / f"{name}.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header.split())
        writer.writerows(rows)

if "--write" in argv:
    write("scenario_summary", "scenario_id on_time_orders on_time_units orders_completed_by_horizon total_order_days_late max_order_days_late extra_purchase_usd transfer_usd total_extra_usd wh01_c01_end_qty wh02_c01_end_qty wh03_c01_end_qty", summaries)
    write("order_results", "scenario_id order_id product_id qty due_date c01_required start_date delivery_date days_late", detail)
    write("inventory_ledger", "scenario_id date event_type reference_id warehouse_id component_id signed_qty on_hand_after", ledger)
    write("checks", "scenario_id expected_start_dates expected_incremental_cost stock_floor_and_conservation", audits)
print("PASS: master data, BOM, 5 scenario replays, 60 order starts, costs and inventory conservation")
