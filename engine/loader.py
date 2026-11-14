"""Load and validate all 14 CSV data files for the supply chain engine,
plus optional world and calendar files.

Key dates (all computed from the data, none hard-coded):
  db["DAY0"]    – reported_date of the disruption(s); all must share the same date.
  db["HORIZON"] – latest due_date in orders.csv; user-facing tables run to this day.
  db["SIM_END"] – DAY0..SIM_END is the simulation loop range; = max of all schedulable
                  dates (planned/revised receipts, recovery receipts, worlds.csv dates,
                  DAY0 + longest offer lead) plus the longest production_days.

worlds.csv (optional, wide format, ADR 0004):
  header: world_id, draw, weight, <variable_columns...>
  receipt_date values must be in [PO.planned_receipt_date, DAY0+365].

closed_days.csv (optional):
  header: date, closed  (closed = 1 or 0)
  Loads into db["calendar"] as a BusinessCalendar with overrides.
"""
import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# Default data directory: engine/../data resolved from this file
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Open kinds: the single place that maps (target_type, field) to a value parser.
# A kind not listed here raises ValueError - nothing is silently ignored.
# ---------------------------------------------------------------------------
_OPEN_KINDS = {
    ("purchase_order", "receipt_date"): lambda v, f: _date(v, f),
}


def _load_csv(name: str, data_dir: Path) -> list[dict]:
    path = data_dir / f"{name}.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _int(value: str, field: str) -> int:
    try:
        v = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field}' is not an integer: {value!r}")
    if v < 0:
        raise ValueError(f"Field '{field}' must be >= 0, got {v}")
    return v


def _date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field}' is not a valid ISO date: {value!r}")


def _require(row: dict, field: str, table: str) -> str:
    v = row.get(field)
    if v is None or v == "":
        raise ValueError(f"Table '{table}': field '{field}' is required but missing/empty in row {row}")
    return v


def load_all(data_dir=None) -> dict:
    """Load and validate all CSVs and optional world/calendar files.  Returns a single db dict."""
    dd = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    # ── products ──────────────────────────────────────────────────────────────
    products = {}
    for r in _load_csv("products", dd):
        pid = _require(r, "product_id", "products")
        if pid in products:
            raise ValueError(f"Duplicate product_id: {pid}")
        products[pid] = {
            "product_id": pid,
            "product_name": _require(r, "product_name", "products"),
            "production_days": _int(_require(r, "production_days", "products"), "production_days"),
        }
    if len(products) != 3:
        raise ValueError(f"Expected 3 products, got {len(products)}")

    # ── components ────────────────────────────────────────────────────────────
    components = {}
    for r in _load_csv("components", dd):
        cid = _require(r, "component_id", "components")
        if cid in components:
            raise ValueError(f"Duplicate component_id: {cid}")
        uom = _require(r, "uom", "components")
        if uom != "EA":
            raise ValueError(f"component uom must be EA, got {uom!r}")
        components[cid] = {
            "component_id": cid,
            "component_name": _require(r, "component_name", "components"),
            "uom": uom,
        }
    if len(components) != 5:
        raise ValueError(f"Expected 5 components, got {len(components)}")

    # ── suppliers ─────────────────────────────────────────────────────────────
    suppliers = {}
    for r in _load_csv("suppliers", dd):
        sid = _require(r, "supplier_id", "suppliers")
        if sid in suppliers:
            raise ValueError(f"Duplicate supplier_id: {sid}")
        suppliers[sid] = {
            "supplier_id": sid,
            "supplier_name": _require(r, "supplier_name", "suppliers"),
        }
    if len(suppliers) != 4:
        raise ValueError(f"Expected 4 suppliers, got {len(suppliers)}")

    # ── warehouses ────────────────────────────────────────────────────────────
    warehouses = {}
    for r in _load_csv("warehouses", dd):
        wid = _require(r, "warehouse_id", "warehouses")
        if wid in warehouses:
            raise ValueError(f"Duplicate warehouse_id: {wid}")
        role = _require(r, "role", "warehouses")
        if role not in ("PRODUCTION", "BUFFER"):
            raise ValueError(f"warehouse role must be PRODUCTION or BUFFER, got {role!r}")
        warehouses[wid] = {
            "warehouse_id": wid,
            "warehouse_name": _require(r, "warehouse_name", "warehouses"),
            "role": role,
        }
    if len(warehouses) != 3:
        raise ValueError(f"Expected 3 warehouses, got {len(warehouses)}")

    # ── bom ───────────────────────────────────────────────────────────────────
    bom: dict[str, dict[str, int]] = defaultdict(dict)
    for r in _load_csv("bom", dd):
        pid = _require(r, "product_id", "bom")
        cid = _require(r, "component_id", "bom")
        if pid not in products:
            raise ValueError(f"bom.product_id '{pid}' not in products")
        if cid not in components:
            raise ValueError(f"bom.component_id '{cid}' not in components")
        qty = _int(_require(r, "qty_per_unit", "bom"), "qty_per_unit")
        if qty <= 0:
            raise ValueError(f"bom.qty_per_unit must be > 0, got {qty}")
        if cid in bom[pid]:
            raise ValueError(f"Duplicate bom row ({pid}, {cid})")
        bom[pid][cid] = qty
    bom = dict(bom)
    if set(bom) != set(products):
        raise ValueError("bom must have an entry for every product")

    # ── inventory ─────────────────────────────────────────────────────────────
    inventory: dict[tuple[str, str], dict] = {}
    for r in _load_csv("inventory", dd):
        wid = _require(r, "warehouse_id", "inventory")
        cid = _require(r, "component_id", "inventory")
        if wid not in warehouses:
            raise ValueError(f"inventory.warehouse_id '{wid}' not in warehouses")
        if cid not in components:
            raise ValueError(f"inventory.component_id '{cid}' not in components")
        key = (wid, cid)
        if key in inventory:
            raise ValueError(f"Duplicate inventory row {key}")
        on_hand = _int(_require(r, "on_hand_qty", "inventory"), "on_hand_qty")
        reserved = _int(_require(r, "reserved_qty", "inventory"), "reserved_qty")
        protected = _int(_require(r, "protected_qty", "inventory"), "protected_qty")
        if on_hand < reserved + protected:
            raise ValueError(f"inventory on_hand {on_hand} < reserved+protected {reserved+protected} for {key}")
        inventory[key] = {
            "warehouse_id": wid,
            "component_id": cid,
            "on_hand_qty": on_hand,
            "reserved_qty": reserved,
            "protected_qty": protected,
        }
    expected_inv_keys = {(w, c) for w in warehouses for c in components}
    if set(inventory) != expected_inv_keys:
        raise ValueError("inventory must have one row for every (warehouse, component) pair")

    # ── supplier_offers ───────────────────────────────────────────────────────
    # Load offers before purchase_orders and disruptions; needed for DAY0 check.
    offers = {}
    for r in _load_csv("supplier_offers", dd):
        oid = _require(r, "offer_id", "supplier_offers")
        if oid in offers:
            raise ValueError(f"Duplicate offer_id: {oid}")
        sid = _require(r, "supplier_id", "supplier_offers")
        if sid not in suppliers:
            raise ValueError(f"supplier_offers.supplier_id '{sid}' not in suppliers")
        cid = _require(r, "component_id", "supplier_offers")
        if cid not in components:
            raise ValueError(f"supplier_offers.component_id '{cid}' not in components")
        lead = _int(_require(r, "lead_days", "supplier_offers"), "lead_days")
        if lead <= 0:
            raise ValueError(f"supplier_offers.lead_days must be > 0")
        offers[oid] = {
            "offer_id": oid,
            "supplier_id": sid,
            "component_id": cid,
            "lead_days": lead,
            "unit_cost_usd": _int(_require(r, "unit_cost_usd", "supplier_offers"), "unit_cost_usd"),
            "fixed_fee_usd": _int(_require(r, "fixed_fee_usd", "supplier_offers"), "fixed_fee_usd"),
            "min_qty": _int(_require(r, "min_qty", "supplier_offers"), "min_qty"),
            "multiple_qty": _int(_require(r, "multiple_qty", "supplier_offers"), "multiple_qty"),
            "max_qty": _int(_require(r, "max_qty", "supplier_offers"), "max_qty"),
        }

    # ── disruptions – raw pass to extract DAY0 ───────────────────────────────
    # Must be before purchase_orders (we need DAY0 to validate order_date < DAY0).
    # Full cross-reference validation happens after purchase_orders are loaded.
    disruptions_raw = _load_csv("disruptions", dd)
    if not disruptions_raw:
        raise ValueError("disruptions.csv: at least one disruption is required")
    reported_dates = set()
    for r in disruptions_raw:
        rd = _date(_require(r, "reported_date", "disruptions"), "reported_date")
        reported_dates.add(rd)
    if len(reported_dates) > 1:
        raise ValueError(
            f"disruptions.reported_date must be the same for all rows; "
            f"got {sorted(reported_dates)}"
        )
    DAY0 = next(iter(reported_dates))

    # ── purchase_orders ───────────────────────────────────────────────────────
    purchase_orders = {}
    for r in _load_csv("purchase_orders", dd):
        po_id = _require(r, "po_id", "purchase_orders")
        if po_id in purchase_orders:
            raise ValueError(f"Duplicate po_id: {po_id}")
        wid = _require(r, "warehouse_id", "purchase_orders")
        if wid not in warehouses:
            raise ValueError(f"purchase_orders.warehouse_id '{wid}' not in warehouses")
        offer_id = _require(r, "offer_id", "purchase_orders")
        if offer_id not in offers:
            raise ValueError(f"purchase_orders.offer_id '{offer_id}' not in supplier_offers")
        offer = offers[offer_id]
        qty = _int(_require(r, "qty", "purchase_orders"), "qty")
        _validate_offer_qty(offer, qty)
        order_date = _date(_require(r, "order_date", "purchase_orders"), "order_date")
        planned = _date(_require(r, "planned_receipt_date", "purchase_orders"), "planned_receipt_date")
        if not (order_date < DAY0 <= planned):
            raise ValueError(f"purchase_orders date constraint violated: order_date={order_date}, planned={planned}")
        expected_planned = order_date + timedelta(days=offer["lead_days"])
        if planned != expected_planned:
            raise ValueError(f"purchase_orders planned_receipt_date {planned} != order_date+lead_days {expected_planned}")
        purchase_orders[po_id] = {
            "po_id": po_id,
            "offer_id": offer_id,
            "warehouse_id": wid,
            "order_date": order_date,
            "qty": qty,
            "planned_receipt_date": planned,
        }

    # ── disruptions – full validation ─────────────────────────────────────────
    disruptions = {}
    for r in disruptions_raw:
        did = _require(r, "disruption_id", "disruptions")
        if did in disruptions:
            raise ValueError(f"Duplicate disruption_id: {did}")
        po_id = _require(r, "po_id", "disruptions")
        if po_id not in purchase_orders:
            raise ValueError(f"disruptions.po_id '{po_id}' not in purchase_orders")
        reported = _date(_require(r, "reported_date", "disruptions"), "reported_date")
        # reported == DAY0 is guaranteed by the raw pass above
        revised = _date(_require(r, "revised_receipt_date", "disruptions"), "revised_receipt_date")
        if revised <= purchase_orders[po_id]["planned_receipt_date"]:
            raise ValueError("disruptions.revised_receipt_date must be after planned_receipt_date")
        disruptions[did] = {
            "disruption_id": did,
            "po_id": po_id,
            "reported_date": reported,
            "revised_receipt_date": revised,
            "reason": _require(r, "reason", "disruptions"),
        }

    # ── orders ────────────────────────────────────────────────────────────────
    orders = {}
    for r in _load_csv("orders", dd):
        oid = _require(r, "order_id", "orders")
        if oid in orders:
            raise ValueError(f"Duplicate order_id: {oid}")
        pid = _require(r, "product_id", "orders")
        if pid not in products:
            raise ValueError(f"orders.product_id '{pid}' not in products")
        wid = _require(r, "warehouse_id", "orders")
        if wid not in warehouses:
            raise ValueError(f"orders.warehouse_id '{wid}' not in warehouses")
        if warehouses[wid]["role"] != "PRODUCTION":
            raise ValueError(f"orders.warehouse_id '{wid}' must be a PRODUCTION warehouse")
        qty = _int(_require(r, "qty", "orders"), "qty")
        if qty <= 0:
            raise ValueError(f"orders.qty must be > 0, got {qty}")
        priority = _int(_require(r, "priority_rank", "orders"), "priority_rank")
        if priority <= 0:
            raise ValueError(f"orders.priority_rank must be > 0, got {priority}")
        due = _date(_require(r, "due_date", "orders"), "due_date")
        if due < DAY0:
            raise ValueError(f"orders.due_date {due} is before DAY0 {DAY0}")
        orders[oid] = {
            "order_id": oid,
            "customer_id": _require(r, "customer_id", "orders"),
            "product_id": pid,
            "qty": qty,
            "due_date": due,
            "priority_rank": priority,
            "warehouse_id": wid,
        }
    if len(orders) != 12:
        raise ValueError(f"Expected 12 orders, got {len(orders)}")

    # ── HORIZON = latest due_date in orders ───────────────────────────────────
    HORIZON = max(o["due_date"] for o in orders.values())

    # ── worlds (optional, wide format, ADR 0004) ──────────────────────────────
    worlds_path = dd / "worlds.csv"
    overrides_path = dd / "world_overrides.csv"

    # world_overrides.csv is retired; its existence is an error.
    if overrides_path.exists():
        raise ValueError(
            "worlds.csv: world_overrides.csv is no longer read; "
            "its content belongs in worlds.csv (see ADR 0004)"
        )

    # Sampling cap: DAY0 + 365 days
    SAMPLING_CAP = DAY0 + timedelta(days=365)

    if not worlds_path.exists():
        worlds_db = None
    else:
        # po_ids that appear in disruptions (supported target_ids for
        # the purchase_order kind)
        disrupted_po_ids = {d["po_id"] for d in disruptions.values()}

        # Rule 3: read raw header to detect duplicates before DictReader
        with worlds_path.open(encoding="utf-8", newline="") as fh:
            raw_header = next(csv.reader(fh))

        if len(raw_header) != len(set(raw_header)):
            seen = set()
            dups = []
            for col in raw_header:
                if col in seen:
                    dups.append(col)
                seen.add(col)
            raise ValueError(
                f"worlds.csv: duplicate column name(s): {dups}"
            )

        # Rule 3: first three columns must be world_id, draw, weight; at least
        # one variable column follows.
        if len(raw_header) < 4 or raw_header[:3] != ["world_id", "draw", "weight"]:
            raise ValueError(
                "worlds.csv: first three header names must be "
                "world_id, draw, weight followed by at least one variable column; "
                f"got {raw_header}"
            )

        var_cols = raw_header[3:]  # variable column names
        expected_ncols = len(raw_header)

        # Rule 4: validate each variable column name
        col_kinds = {}  # col_name -> (ttype, tid, field)
        for col in var_cols:
            parts = col.split(".")
            if len(parts) != 3 or any(p == "" for p in parts):
                raise ValueError(
                    f"worlds.csv: variable column {col!r} must split into "
                    "exactly 3 non-empty parts on '.'"
                )
            ttype, tid, field = parts
            kind_key = (ttype, field)
            if kind_key not in _OPEN_KINDS:
                raise ValueError(
                    f"worlds.csv: variable column {col!r}: "
                    f"kind ({ttype!r}, {field!r}) is not supported yet"
                )
            if ttype == "purchase_order":
                if tid not in disrupted_po_ids:
                    raise ValueError(
                        f"worlds.csv: variable column {col!r}: "
                        f"target_id {tid!r} is not a PO named in disruptions"
                    )
            col_kinds[col] = (ttype, tid, field)

        # Read all rows; check raw column count per row (Part B gaps check)
        # Read once into memory: list of (raw_row_list, dict_row)
        with worlds_path.open(encoding="utf-8", newline="") as fh:
            all_raw = list(csv.reader(fh))
        # all_raw[0] is the header; data rows start at index 1
        raw_data_rows = all_raw[1:]

        with worlds_path.open(encoding="utf-8", newline="") as fh:
            dict_rows = list(csv.DictReader(fh))

        worlds_db = []
        seen_world_ids = set()
        draw_totals = {}  # draw int -> total weight int

        for raw_row, row in zip(raw_data_rows, dict_rows):
                ncols = len(raw_row)

                # Rule B: row width checks
                wid = row.get("world_id", "") or ""
                if ncols > expected_ncols:
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: row has {ncols} cells "
                        f"but header has {expected_ncols} columns"
                    )
                if ncols < expected_ncols:
                    # Identify the first missing column
                    missing = raw_header[ncols] if ncols < len(raw_header) else "unknown"
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: row is missing column {missing!r} "
                        f"({ncols} cells, header has {expected_ncols})"
                    )

                # Rule 5: world_id non-empty and unique
                if not wid:
                    raise ValueError("worlds.csv: world_id must not be empty")
                if wid in seen_world_ids:
                    raise ValueError(
                        f"worlds.csv: duplicate world_id {wid!r}"
                    )
                seen_world_ids.add(wid)

                # Rule 5: draw is an integer >= 0
                raw_draw = row.get("draw", "")
                if raw_draw == "":
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: draw must not be empty"
                    )
                try:
                    draw = _int(raw_draw, "draw")
                except ValueError as exc:
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: {exc}"
                    ) from exc

                # Rule 5: weight is an integer >= 1
                raw_w = row.get("weight", "")
                if raw_w == "":
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: weight must not be empty"
                    )
                try:
                    weight = _int(raw_w, "weight")
                except ValueError as exc:
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: {exc}"
                    ) from exc
                if weight < 1:
                    raise ValueError(
                        f"worlds.csv: world {wid!r}: weight must be >= 1, got {weight}"
                    )

                # Rule 5: no empty cells — variable columns; Rule 6: parse values
                overrides = {}
                for col in var_cols:
                    raw_val = row.get(col, "")
                    if raw_val == "":
                        raise ValueError(
                            f"worlds.csv: world {wid!r}: "
                            f"column {col!r} must not be empty"
                        )
                    ttype, tid, field = col_kinds[col]
                    kind_key = (ttype, field)
                    try:
                        parsed = _OPEN_KINDS[kind_key](raw_val, field)
                    except ValueError as exc:
                        raise ValueError(
                            f"worlds.csv: world {wid!r}: {exc}"
                        ) from exc
                    # receipt_date bounds: >= PO's planned date, <= sampling cap
                    if kind_key == ("purchase_order", "receipt_date"):
                        po = purchase_orders[tid]
                        lo = po["planned_receipt_date"]
                        if parsed < lo:
                            raise ValueError(
                                f"worlds.csv: world {wid!r}: "
                                f"receipt_date {parsed} is before the PO's "
                                f"planned_receipt_date {lo}"
                            )
                        if parsed > SAMPLING_CAP:
                            raise ValueError(
                                f"worlds.csv: world {wid!r}: "
                                f"receipt_date {parsed} is after the sampling cap "
                                f"({SAMPLING_CAP}, one year after DAY0); "
                                f"dates after the cap need stage 2"
                            )
                    override_key = (ttype, tid, field)
                    overrides[override_key] = parsed

                # Accumulate draw totals for rule 7
                draw_totals[draw] = draw_totals.get(draw, 0) + weight

                worlds_db.append({
                    "world_id": wid,
                    "draw": draw,
                    "weight": weight,
                    "overrides": overrides,
                })

        if not worlds_db:
            raise ValueError("worlds.csv: must contain at least one world")

        # Rule 7: every draw must have the same total weight
        totals_set = set(draw_totals.values())
        if len(totals_set) > 1:
            draws_summary = ", ".join(
                f"draw {d} total {t}"
                for d, t in sorted(draw_totals.items())
            )
            raise ValueError(
                f"worlds.csv: draws have unequal total weights ({draws_summary})"
            )

    # ── transfer_lanes ────────────────────────────────────────────────────────
    lanes = {}
    for r in _load_csv("transfer_lanes", dd):
        lid = _require(r, "lane_id", "transfer_lanes")
        if lid in lanes:
            raise ValueError(f"Duplicate lane_id: {lid}")
        from_wid = _require(r, "from_warehouse_id", "transfer_lanes")
        to_wid = _require(r, "to_warehouse_id", "transfer_lanes")
        if from_wid not in warehouses:
            raise ValueError(f"transfer_lanes.from_warehouse_id '{from_wid}' not in warehouses")
        if to_wid not in warehouses:
            raise ValueError(f"transfer_lanes.to_warehouse_id '{to_wid}' not in warehouses")
        if from_wid == to_wid:
            raise ValueError(f"transfer_lanes from and to must differ for lane {lid}")
        lead = _int(_require(r, "lead_days", "transfer_lanes"), "lead_days")
        if lead <= 0:
            raise ValueError(f"transfer_lanes.lead_days must be > 0")
        lanes[lid] = {
            "lane_id": lid,
            "from_warehouse_id": from_wid,
            "to_warehouse_id": to_wid,
            "lead_days": lead,
            "max_qty": _int(_require(r, "max_qty", "transfer_lanes"), "max_qty"),
            "unit_cost_usd": _int(_require(r, "unit_cost_usd", "transfer_lanes"), "unit_cost_usd"),
            "fixed_fee_usd": _int(_require(r, "fixed_fee_usd", "transfer_lanes"), "fixed_fee_usd"),
        }

    # ── scenarios ─────────────────────────────────────────────────────────────
    scenarios = {}
    for r in _load_csv("scenarios", dd):
        sid = _require(r, "scenario_id", "scenarios")
        if sid in scenarios:
            raise ValueError(f"Duplicate scenario_id: {sid}")
        dis_id = r.get("disruption_id") or None  # empty string → None
        if dis_id is not None and dis_id not in disruptions:
            raise ValueError(f"scenarios.disruption_id '{dis_id}' not in disruptions")
        scenarios[sid] = {
            "scenario_id": sid,
            "disruption_id": dis_id,
            "label": _require(r, "label", "scenarios"),
        }

    # ── recovery_purchases ────────────────────────────────────────────────────
    recovery_purchases: dict[tuple[str, str], dict] = {}
    for r in _load_csv("recovery_purchases", dd):
        sid = _require(r, "scenario_id", "recovery_purchases")
        offer_id = _require(r, "offer_id", "recovery_purchases")
        if sid not in scenarios:
            raise ValueError(f"recovery_purchases.scenario_id '{sid}' not in scenarios")
        if offer_id not in offers:
            raise ValueError(f"recovery_purchases.offer_id '{offer_id}' not in supplier_offers")
        key = (sid, offer_id)
        if key in recovery_purchases:
            raise ValueError(f"Duplicate recovery_purchases row {key}")
        wid = _require(r, "warehouse_id", "recovery_purchases")
        if wid not in warehouses:
            raise ValueError(f"recovery_purchases.warehouse_id '{wid}' not in warehouses")
        qty = _int(_require(r, "qty", "recovery_purchases"), "qty")
        _validate_offer_qty(offers[offer_id], qty)
        action_date = _date(_require(r, "action_date", "recovery_purchases"), "action_date")
        recovery_purchases[key] = {
            "scenario_id": sid,
            "offer_id": offer_id,
            "warehouse_id": wid,
            "action_date": action_date,
            "qty": qty,
        }

    # ── recovery_transfers ────────────────────────────────────────────────────
    recovery_transfers: dict[tuple[str, str, str], dict] = {}
    lane_totals: dict[tuple[str, str], int] = defaultdict(int)
    for r in _load_csv("recovery_transfers", dd):
        sid = _require(r, "scenario_id", "recovery_transfers")
        lane_id = _require(r, "lane_id", "recovery_transfers")
        cid = _require(r, "component_id", "recovery_transfers")
        if sid not in scenarios:
            raise ValueError(f"recovery_transfers.scenario_id '{sid}' not in scenarios")
        if lane_id not in lanes:
            raise ValueError(f"recovery_transfers.lane_id '{lane_id}' not in transfer_lanes")
        if cid not in components:
            raise ValueError(f"recovery_transfers.component_id '{cid}' not in components")
        key = (sid, lane_id, cid)
        if key in recovery_transfers:
            raise ValueError(f"Duplicate recovery_transfers row {key}")
        qty = _int(_require(r, "qty", "recovery_transfers"), "qty")
        if qty <= 0:
            raise ValueError(f"recovery_transfers.qty must be > 0")
        lane_totals[(sid, lane_id)] += qty
        if lane_totals[(sid, lane_id)] > lanes[lane_id]["max_qty"]:
            raise ValueError(
                f"recovery_transfers total qty {lane_totals[(sid, lane_id)]} exceeds "
                f"lane {lane_id} max_qty {lanes[lane_id]['max_qty']} for scenario {sid}"
            )
        action_date = _date(_require(r, "action_date", "recovery_transfers"), "action_date")
        recovery_transfers[key] = {
            "scenario_id": sid,
            "lane_id": lane_id,
            "component_id": cid,
            "action_date": action_date,
            "qty": qty,
        }

    # ── SIM_END: latest schedulable date + max production_days ───────────────
    # Collect all dates the simulation may need to reach.
    sim_end_candidates = [HORIZON]

    # planned and revised receipts of purchase_orders / disruptions
    for po in purchase_orders.values():
        sim_end_candidates.append(po["planned_receipt_date"])
    for dis in disruptions.values():
        sim_end_candidates.append(dis["revised_receipt_date"])

    # recovery purchase receipts
    for rp in recovery_purchases.values():
        offer = offers[rp["offer_id"]]
        sim_end_candidates.append(rp["action_date"] + timedelta(days=offer["lead_days"]))

    # recovery transfer receipts
    for rt in recovery_transfers.values():
        lane = lanes[rt["lane_id"]]
        sim_end_candidates.append(rt["action_date"] + timedelta(days=lane["lead_days"]))

    # DAY0 + longest offer lead_days (purchase on the decision day)
    max_offer_lead = max(o["lead_days"] for o in offers.values())
    sim_end_candidates.append(DAY0 + timedelta(days=max_offer_lead))

    # Every receipt_date value in worlds.csv
    if worlds_db is not None:
        for w in worlds_db:
            for (ttype, tid, field), val in w["overrides"].items():
                if field == "receipt_date":
                    sim_end_candidates.append(val)

    max_sched = max(sim_end_candidates)
    max_prod_days = max(p["production_days"] for p in products.values())
    SIM_END = max_sched + timedelta(days=max_prod_days)

    # ── closed_days.csv (optional) ────────────────────────────────────────────
    from engine.business_calendar import BusinessCalendar
    closed_days_path = dd / "closed_days.csv"
    if closed_days_path.exists():
        overrides_cal = {}
        with closed_days_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if list(reader.fieldnames or []) != ["date", "closed"]:
                raise ValueError(
                    f"closed_days.csv: header must be exactly ['date', 'closed'], "
                    f"got {list(reader.fieldnames or [])}"
                )
            for row in reader:
                raw_d = row.get("date", "")
                raw_c = row.get("closed", "")
                if not raw_d or not raw_c:
                    raise ValueError(
                        f"closed_days.csv: empty cell in row {dict(row)}"
                    )
                try:
                    d = date.fromisoformat(raw_d)
                except ValueError:
                    raise ValueError(
                        f"closed_days.csv: invalid date {raw_d!r} in row {dict(row)}"
                    )
                if raw_c not in ("0", "1"):
                    raise ValueError(
                        f"closed_days.csv: closed must be 0 or 1, got {raw_c!r} "
                        f"in row {dict(row)}"
                    )
                if d in overrides_cal:
                    raise ValueError(
                        f"closed_days.csv: duplicate date {raw_d!r}"
                    )
                overrides_cal[d] = (raw_c == "1")
        calendar = BusinessCalendar(overrides=overrides_cal)
    else:
        calendar = BusinessCalendar()

    # ── derived structures ────────────────────────────────────────────────────
    # floor[warehouse_id][component_id] = reserved + protected
    floor: dict[str, dict[str, int]] = {}
    for wid in warehouses:
        floor[wid] = {}
        for cid in components:
            inv = inventory[(wid, cid)]
            floor[wid][cid] = inv["reserved_qty"] + inv["protected_qty"]

    # opening[warehouse_id][component_id] = on_hand_qty
    opening: dict[str, dict[str, int]] = {}
    for wid in warehouses:
        opening[wid] = {}
        for cid in components:
            opening[wid][cid] = inventory[(wid, cid)]["on_hand_qty"]

    # queue: order_ids sorted by (due_date, priority_rank, order_id)
    queue = sorted(
        orders,
        key=lambda k: (orders[k]["due_date"], orders[k]["priority_rank"], k),
    )

    # needs[order_id][component_id] = total qty required
    needs: dict[str, dict[str, int]] = {}
    for oid in queue:
        order = orders[oid]
        needs[oid] = {
            cid: bom[order["product_id"]][cid] * order["qty"]
            for cid in bom[order["product_id"]]
        }

    return {
        "products": products,
        "components": components,
        "suppliers": suppliers,
        "warehouses": warehouses,
        "bom": bom,
        "inventory": inventory,
        "orders": orders,
        "offers": offers,
        "purchase_orders": purchase_orders,
        "disruptions": disruptions,
        "lanes": lanes,
        "scenarios": scenarios,
        "recovery_purchases": recovery_purchases,
        "recovery_transfers": recovery_transfers,
        "worlds": worlds_db,
        # derived
        "floor": floor,
        "opening": opening,
        "queue": queue,
        "needs": needs,
        "DAY0": DAY0,
        "HORIZON": HORIZON,
        "SIM_END": SIM_END,
        "calendar": calendar,
    }


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
            f"Offer {offer['offer_id']}: qty {qty} is not a multiple of {mul_q}"
        )
