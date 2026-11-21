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
import re
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
    ("offer",          "delay_business_days"): lambda v, f: _signed_int(v, f),
    ("lane",           "lead_days"):           lambda v, f: _pos_int(v, f),
    ("cause",          "active"):              lambda v, f: _cause_active(v, f),
}

# Legacy-kind field names (target_type, field) — present in legacy worlds files
_LEGACY_KINDS = {
    ("lane",  "lead_days"),
    ("cause", "active"),
}

# Regex for episode field names: ep<n>_start_date / ep<n>_end_date / ep<n>_delay_days
_EP_FIELD_RE = re.compile(r"^ep([1-9][0-9]*)_(start_date|end_date|delay_days)$")


def _is_new_episode_kind(ttype: str, field: str) -> bool:
    """Return True if (ttype, field) is a new-format episode column kind."""
    return ttype == "cause" and bool(_EP_FIELD_RE.match(field))


def _is_new_lane_delay_kind(ttype: str, field: str) -> bool:
    """Return True if (ttype, field) is the new lane delay_days kind."""
    return ttype == "lane" and field == "delay_days"


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


def _signed_int(value: str, field: str) -> int:
    """Parse an integer that may be negative (e.g. delay_business_days)."""
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field}' is not an integer: {value!r}")


def _pos_int(value: str, field: str) -> int:
    """Parse a positive integer (>= 1)."""
    try:
        v = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field}' is not an integer: {value!r}")
    if v < 1:
        raise ValueError(f"Field '{field}' must be >= 1, got {v}")
    return v


def _cause_active(value: str, field: str) -> int:
    """Parse a cause tag: must be 0 or 1."""
    try:
        v = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Field '{field}' is not an integer: {value!r}")
    if v not in (0, 1):
        raise ValueError(f"Field '{field}' must be 0 or 1, got {v!r}")
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

    # ── transfer_lanes ────────────────────────────────────────────────────────
    # Loaded before worlds so that lane target_ids can be validated.
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

    # ── causes (optional, data/causes.csv) ───────────────────────────────────
    from engine.causes import load_causes
    _causes = load_causes(dd, {
        "purchase_orders": purchase_orders,
        "offers": offers,
        "lanes": lanes,
    })


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
        if action_date < DAY0:
            raise ValueError(
                f"recovery_purchases: row ({sid!r}, {offer_id!r}): "
                f"action_date {action_date} is before DAY0 {DAY0}"
            )
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
        if action_date < DAY0:
            raise ValueError(
                f"recovery_transfers: row ({sid!r}, {lane_id!r}, {cid!r}): "
                f"action_date {action_date} is before DAY0 {DAY0}"
            )
        recovery_transfers[key] = {
            "scenario_id": sid,
            "lane_id": lane_id,
            "component_id": cid,
            "action_date": action_date,
            "qty": qty,
        }

    # ── data rule 6b: recovery purchase offer must be a target of same cause ──
    if _causes is not None:
        # cause_id -> set of offer_ids that are "offer" targets of that cause
        _cause_offer_targets: dict = {}
        # po_id -> cause_id  (for purchase_order targets)
        _po_cause: dict = {}
        # po_id -> offer_id (the offer backing that PO, from purchase_orders)
        _po_offer: dict = {}
        for _cr in _causes:
            if _cr["target_type"] == "offer":
                _cause_offer_targets.setdefault(_cr["cause_id"], set()).add(
                    _cr["target_id"]
                )
            elif _cr["target_type"] == "purchase_order":
                _po_cause[_cr["target_id"]] = _cr["cause_id"]
                _po_offer[_cr["target_id"]] = purchase_orders[_cr["target_id"]]["offer_id"]
        for (sid, offer_id), rp in recovery_purchases.items():
            # For every PO that (a) uses this offer and (b) is a cause target,
            # the offer must also be an offer target of that cause.
            for po_id, po_cause_k in _po_cause.items():
                if _po_offer[po_id] == offer_id:
                    if offer_id not in _cause_offer_targets.get(po_cause_k, set()):
                        raise ValueError(
                            f"recovery_purchases: offer {offer_id!r} is the offer "
                            f"of purchase order {po_id!r} which is a target of "
                            f"cause {po_cause_k!r}, but {offer_id!r} is not an "
                            f"offer target of {po_cause_k!r} in causes.csv"
                        )

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

    # ── cause_horizons (optional, computed after calendar is available) ───────
    if _causes is not None:
        from engine.causes import compute_cause_horizons
        _cause_horizons = compute_cause_horizons(
            _causes,
            {
                "DAY0": DAY0,
                "calendar": calendar,
                "purchase_orders": purchase_orders,
                "disruptions": disruptions,
                "offers": offers,
                "lanes": lanes,
                "recovery_purchases": recovery_purchases,
                "recovery_transfers": recovery_transfers,
            },
        )
    else:
        _cause_horizons = None

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
        worlds_format = None
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

        # Classify each variable column as legacy or new.
        # A file is "legacy" if it has a legacy-kind column; "new" otherwise.
        # A file with both is an error.
        _has_legacy = False
        _has_new = False
        for _col in var_cols:
            _parts = _col.split(".")
            if len(_parts) == 3:
                _tt, _ti, _ff = _parts
                if (_tt, _ff) in _LEGACY_KINDS:
                    _has_legacy = True
                elif _is_new_episode_kind(_tt, _ff) or _is_new_lane_delay_kind(_tt, _ff):
                    _has_new = True
        if _has_legacy and _has_new:
            raise ValueError(
                "worlds.csv: file mixes legacy-format columns "
                "(lane.*.lead_days, cause.*.active) with new-format columns "
                "(cause episode columns, lane.*.delay_days); "
                "use one format only"
            )
        worlds_format = "legacy" if _has_legacy else "new"

        # ── Validate variable column names ────────────────────────────────────
        col_kinds = {}  # col_name -> (ttype, tid, field)
        if worlds_format == "legacy":
            # Legacy path: existing validation rules (kind must be in _OPEN_KINDS)
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
                elif ttype == "offer":
                    if tid not in offers:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"target_id {tid!r} is not in supplier_offers"
                        )
                elif ttype == "lane":
                    if tid not in lanes:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"target_id {tid!r} is not in transfer_lanes"
                        )
                elif ttype == "cause":
                    if field != "active":
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"only field 'active' is allowed for target_type 'cause', "
                            f"got {field!r}"
                        )
                col_kinds[col] = (ttype, tid, field)
        else:
            # New format: validate column names (rules 4a-4e)
            # First pass: parse each column into (ttype, tid, field)
            _ep_cols_by_cause: dict = {}  # cause_id -> {slot_n -> {suffix -> col}}
            _target_var_cols: dict = {}   # (ttype, tid) -> col_name (for rule 4d)
            for col in var_cols:
                parts = col.split(".")
                if len(parts) != 3 or any(p == "" for p in parts):
                    raise ValueError(
                        f"worlds.csv: variable column {col!r} must split into "
                        "exactly 3 non-empty parts on '.'"
                    )
                ttype, tid, field = parts
                kind_key = (ttype, field)
                # Determine column category
                _is_ep = _is_new_episode_kind(ttype, field)
                _is_lane_delay = _is_new_lane_delay_kind(ttype, field)
                # Also allow legacy non-kind columns: purchase_order receipt_date,
                # offer delay_business_days (these are always valid in both formats)
                _is_legacy_base = kind_key in _OPEN_KINDS and kind_key not in _LEGACY_KINDS
                if not (_is_ep or _is_lane_delay or _is_legacy_base):
                    raise ValueError(
                        f"worlds.csv: variable column {col!r}: "
                        f"kind ({ttype!r}, {field!r}) is not supported yet"
                    )
                # Validate target_id
                if ttype == "purchase_order":
                    if tid not in disrupted_po_ids:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"target_id {tid!r} is not a PO named in disruptions"
                        )
                    _target_var_cols[("purchase_order", tid)] = col
                elif ttype == "offer":
                    if tid not in offers:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"target_id {tid!r} is not in supplier_offers"
                        )
                    _target_var_cols[("offer", tid)] = col
                elif ttype == "lane":
                    if tid not in lanes:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"target_id {tid!r} is not in transfer_lanes"
                        )
                    if _is_lane_delay:
                        _target_var_cols[("lane", tid)] = col
                elif ttype == "cause":
                    # Must be an episode field
                    if not _is_ep:
                        raise ValueError(
                            f"worlds.csv: variable column {col!r}: "
                            f"only episode fields are allowed for 'cause' in "
                            f"new-format files, got field {field!r}"
                        )
                    m = _EP_FIELD_RE.match(field)
                    slot_n = int(m.group(1))
                    suffix = m.group(2)
                    if tid not in _ep_cols_by_cause:
                        _ep_cols_by_cause[tid] = {}
                    _ep_cols_by_cause[tid].setdefault(slot_n, {})[suffix] = col
                col_kinds[col] = (ttype, tid, field)

            # Rule 4a: cause columns while causes is None
            if _ep_cols_by_cause and _causes is None:
                raise ValueError(
                    "worlds.csv: file has cause episode columns but "
                    "data/causes.csv is not present"
                )

            if _causes is not None:
                # Build set of cause_ids in causes.csv
                _known_causes = {r["cause_id"] for r in _causes}

                # Rule 4b: every cause in causes.csv must have episode columns
                for _cid in _known_causes:
                    if _cid not in _ep_cols_by_cause:
                        raise ValueError(
                            f"worlds.csv: cause {_cid!r} from causes.csv has no "
                            f"episode columns in worlds.csv"
                        )

                # Rule 4c: episode columns for a cause not in causes.csv
                for _cid in _ep_cols_by_cause:
                    if _cid not in _known_causes:
                        raise ValueError(
                            f"worlds.csv: episode columns for cause {_cid!r} "
                            f"which is not in causes.csv"
                        )

                # Rule 4d: every target in causes.csv must have a variable column
                for _cr in _causes:
                    _tt = _cr["target_type"]
                    _ti = _cr["target_id"]
                    _key = (_tt, _ti)
                    if _tt == "lane":
                        _key = ("lane", _ti)
                    if _key not in _target_var_cols:
                        if _tt == "purchase_order":
                            _expected_col = f"purchase_order.{_ti}.receipt_date"
                        elif _tt == "offer":
                            _expected_col = f"offer.{_ti}.delay_business_days"
                        else:
                            _expected_col = f"lane.{_ti}.delay_days"
                        raise ValueError(
                            f"worlds.csv: target {_ti!r} (type {_tt!r}) from "
                            f"causes.csv has no variable column; "
                            f"expected column {_expected_col!r}"
                        )

                # Rule 4e: for every cause, slots 1..S with no gap; each slot
                # has all three fields
                for _cid, _slots in _ep_cols_by_cause.items():
                    _slot_nums = sorted(_slots.keys())
                    if _slot_nums != list(range(1, len(_slot_nums) + 1)):
                        raise ValueError(
                            f"worlds.csv: cause {_cid!r} episode slot numbers "
                            f"are not contiguous from 1: {_slot_nums}"
                        )
                    for _sn in _slot_nums:
                        _have = set(_slots[_sn].keys())
                        _want = {"start_date", "end_date", "delay_days"}
                        if _have != _want:
                            missing_f = _want - _have
                            raise ValueError(
                                f"worlds.csv: cause {_cid!r} slot {_sn} is "
                                f"missing fields {sorted(missing_f)}"
                            )

        # Read all rows; check raw column count per row
        with worlds_path.open(encoding="utf-8", newline="") as fh:
            all_raw = list(csv.reader(fh))
        # all_raw[0] is the header; data rows start at index 1
        raw_data_rows = all_raw[1:]

        with worlds_path.open(encoding="utf-8", newline="") as fh:
            dict_rows = list(csv.DictReader(fh))

        worlds_db = []
        seen_world_ids = set()
        draw_totals = {}  # draw int -> total weight int

        # For new format: collect episode column info per cause
        _new_ep_info = {}  # cause_id -> sorted list of slot_n, each with col names
        if worlds_format == "new":
            for col, (ttype, tid, field) in col_kinds.items():
                if ttype == "cause":
                    m = _EP_FIELD_RE.match(field)
                    if m:
                        slot_n = int(m.group(1))
                        suffix = m.group(2)
                        if tid not in _new_ep_info:
                            _new_ep_info[tid] = {}
                        _new_ep_info[tid].setdefault(slot_n, {})[suffix] = col
            # Sort slots for each cause
            for _cid in _new_ep_info:
                _new_ep_info[_cid] = {
                    sn: _new_ep_info[_cid][sn]
                    for sn in sorted(_new_ep_info[_cid])
                }

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

                if worlds_format == "legacy":
                    # Legacy row processing: existing rules
                    overrides = {}
                    tags = {}
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
                        elif kind_key == ("offer", "delay_business_days"):
                            pass  # checked after calendar load
                        elif kind_key == ("lane", "lead_days"):
                            if DAY0 + timedelta(days=parsed) > SAMPLING_CAP:
                                raise ValueError(
                                    f"worlds.csv: world {wid!r}: "
                                    f"lane {tid!r} lead_days {parsed} would put "
                                    f"DAY0 + lead_days beyond the sampling cap "
                                    f"({SAMPLING_CAP})"
                                )
                        if ttype == "cause":
                            tags[tid] = parsed
                        else:
                            override_key = (ttype, tid, field)
                            overrides[override_key] = parsed

                    draw_totals[draw] = draw_totals.get(draw, 0) + weight
                    worlds_db.append({
                        "world_id": wid,
                        "draw": draw,
                        "weight": weight,
                        "overrides": overrides,
                        "tags": tags,
                        "episodes": {},
                    })

                else:
                    # New format row processing
                    overrides = {}
                    tags = {}
                    episodes = {}  # cause_id -> list of {start, end, delay}

                    for col in var_cols:
                        raw_val = row.get(col, "")
                        ttype, tid, field = col_kinds[col]
                        kind_key = (ttype, field)

                        if ttype == "cause":
                            # Episode cells may be "none" or values; handled below
                            continue

                        # Non-episode columns: must not be empty
                        if raw_val == "":
                            raise ValueError(
                                f"worlds.csv: world {wid!r}: "
                                f"column {col!r} must not be empty"
                            )

                        if kind_key == ("purchase_order", "receipt_date"):
                            try:
                                parsed = _OPEN_KINDS[kind_key](raw_val, field)
                            except ValueError as exc:
                                raise ValueError(
                                    f"worlds.csv: world {wid!r}: {exc}"
                                ) from exc
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
                            overrides[("purchase_order", tid, "receipt_date")] = parsed

                        elif kind_key == ("offer", "delay_business_days"):
                            try:
                                parsed = _signed_int(raw_val, field)
                            except ValueError as exc:
                                raise ValueError(
                                    f"worlds.csv: world {wid!r}: {exc}"
                                ) from exc
                            overrides[("offer", tid, "delay_business_days")] = parsed

                        elif kind_key == ("lane", "delay_days"):
                            # New lane delay kind: signed integer
                            try:
                                parsed = _signed_int(raw_val, field)
                            except ValueError as exc:
                                raise ValueError(
                                    f"worlds.csv: world {wid!r}: {exc}"
                                ) from exc
                            overrides[("lane", tid, "delay_days")] = parsed

                    # Process episode columns per cause
                    for cause_id, slots_info in _new_ep_info.items():
                        slot_list = []
                        prev_none = False
                        max_slot_delay = None
                        for slot_n, field_cols in slots_info.items():
                            start_col = field_cols["start_date"]
                            end_col = field_cols["end_date"]
                            delay_col = field_cols["delay_days"]
                            sv = row.get(start_col, "")
                            ev = row.get(end_col, "")
                            dv = row.get(delay_col, "")

                            # Rule 5a: all three "none" or all three values
                            is_none_triple = (sv == "none" and ev == "none" and dv == "none")
                            is_val_triple = (sv != "none" and ev != "none" and dv != "none")
                            if not is_none_triple and not is_val_triple:
                                raise ValueError(
                                    f"worlds.csv: world {wid!r}: cause {cause_id!r} "
                                    f"slot {slot_n}: cells must be all 'none' or "
                                    f"all values, got "
                                    f"start={sv!r} end={ev!r} delay={dv!r}"
                                )

                            if is_none_triple:
                                prev_none = True
                            else:
                                # Rule 5b: cannot have values after a "none" slot
                                if prev_none:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: cause {cause_id!r} "
                                        f"slot {slot_n} has values but an earlier "
                                        f"slot was 'none'"
                                    )
                                # Parse the values
                                try:
                                    start_d = _date(sv, "start_date")
                                except ValueError as exc:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: {exc}"
                                    ) from exc
                                try:
                                    end_d = _date(ev, "end_date")
                                except ValueError as exc:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: {exc}"
                                    ) from exc
                                try:
                                    delay_i = _signed_int(dv, "delay_days")
                                except ValueError as exc:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: {exc}"
                                    ) from exc

                                # Rule 5c: start <= end, delay >= 1
                                if end_d < start_d:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: cause "
                                        f"{cause_id!r} slot {slot_n}: "
                                        f"end_date {end_d} is before start_date "
                                        f"{start_d}"
                                    )
                                if delay_i < 1:
                                    raise ValueError(
                                        f"worlds.csv: world {wid!r}: cause "
                                        f"{cause_id!r} slot {slot_n}: "
                                        f"delay_days {delay_i} must be >= 1"
                                    )

                                # Rule 5d: next slot's start > previous end
                                if slot_list:
                                    prev_end = slot_list[-1]["end"]
                                    if start_d <= prev_end:
                                        raise ValueError(
                                            f"worlds.csv: world {wid!r}: cause "
                                            f"{cause_id!r} slot {slot_n}: "
                                            f"start_date {start_d} must be after "
                                            f"previous slot end_date {prev_end}"
                                        )

                                # Rule 5e: start_date bounds
                                if _cause_horizons is not None and cause_id in _cause_horizons:
                                    H = _cause_horizons[cause_id]["H"]
                                    if start_d > H:
                                        raise ValueError(
                                            f"worlds.csv: world {wid!r}: cause "
                                            f"{cause_id!r} slot {slot_n}: "
                                            f"start_date {start_d} is after the "
                                            f"cause horizon H={H}"
                                        )
                                # start_date >= DAY0, except slot 1 may start before
                                # DAY0 if end_date >= DAY0
                                if slot_n == 1:
                                    if start_d < DAY0 and end_d < DAY0:
                                        raise ValueError(
                                            f"worlds.csv: world {wid!r}: cause "
                                            f"{cause_id!r} slot 1: start_date "
                                            f"{start_d} is before DAY0 {DAY0} and "
                                            f"end_date {end_d} is also before DAY0"
                                        )
                                else:
                                    if start_d < DAY0:
                                        raise ValueError(
                                            f"worlds.csv: world {wid!r}: cause "
                                            f"{cause_id!r} slot {slot_n}: "
                                            f"start_date {start_d} is before "
                                            f"DAY0 {DAY0} (only slot 1 may)"
                                        )

                                if max_slot_delay is None or delay_i > max_slot_delay:
                                    max_slot_delay = delay_i
                                slot_list.append({
                                    "start": start_d,
                                    "end": end_d,
                                    "delay": delay_i,
                                })

                        episodes[cause_id] = slot_list

                        # Rule 5f: cap check using room_t per target
                        if max_slot_delay is not None and _causes is not None:
                            for _cr in _causes:
                                if _cr["cause_id"] != cause_id:
                                    continue
                                _tt = _cr["target_type"]
                                _ti = _cr["target_id"]
                                _ld = _cr["lead_days"]
                                if _tt in ("offer", "purchase_order"):
                                    if _tt == "purchase_order":
                                        _offer_id = _cr["source_id"]
                                        _delay_col = f"offer.{_offer_id}.delay_business_days"
                                        _ld_use = offers[_offer_id]["lead_days"]
                                    else:
                                        _offer_id = _ti
                                        _delay_col = f"offer.{_offer_id}.delay_business_days"
                                        _ld_use = _ld
                                    _raw_delay = row.get(_delay_col)
                                    if _raw_delay is not None and _raw_delay != "":
                                        try:
                                            _d_val = _signed_int(_raw_delay, "delay_business_days")
                                        except ValueError:
                                            _d_val = 0
                                        # room_t for this offer: business days from
                                        # latest promised date (over DAY0 and all
                                        # recovery_purchases rows) to SAMPLING_CAP
                                        _L_offer = calendar.next_business_day(
                                            DAY0 + timedelta(days=_ld_use)
                                        )
                                        for (_rp_sid, _rp_oid), _rp in recovery_purchases.items():
                                            if _rp_oid == _offer_id:
                                                _rp_promised = calendar.next_business_day(
                                                    _rp["action_date"] + timedelta(days=_ld_use)
                                                )
                                                if _rp_promised > _L_offer:
                                                    _L_offer = _rp_promised
                                        _room_offer = calendar.business_days_between(
                                            _L_offer, SAMPLING_CAP
                                        )
                                        if _d_val + max_slot_delay > _room_offer:
                                            raise ValueError(
                                                f"worlds.csv: world {wid!r}: "
                                                f"offer {_offer_id!r} "
                                                f"delay_business_days {_d_val} "
                                                f"plus cause {cause_id!r} max "
                                                f"episode delay {max_slot_delay} "
                                                f"exceeds room {_room_offer}"
                                            )
                                elif _tt == "lane":
                                    _lane_delay_col = f"lane.{_ti}.delay_days"
                                    _raw_lane_delay = row.get(_lane_delay_col)
                                    if _raw_lane_delay is not None and _raw_lane_delay != "":
                                        try:
                                            _ld_val = _signed_int(
                                                _raw_lane_delay, "delay_days"
                                            )
                                        except ValueError:
                                            _ld_val = 0
                                        # room_t for this lane: calendar days from
                                        # latest base arrival (over DAY0 and all
                                        # recovery_transfers rows) to SAMPLING_CAP
                                        _L_lane = DAY0 + timedelta(days=_ld)
                                        for (_rt_sid, _rt_lid, _rt_cid), _rt in recovery_transfers.items():
                                            if _rt_lid == _ti:
                                                _rt_arrival = _rt["action_date"] + timedelta(days=_ld)
                                                if _rt_arrival > _L_lane:
                                                    _L_lane = _rt_arrival
                                        _room_lane = (SAMPLING_CAP - _L_lane).days
                                        if _ld_val + max_slot_delay > _room_lane:
                                            raise ValueError(
                                                f"worlds.csv: world {wid!r}: "
                                                f"lane {_ti!r} delay_days {_ld_val} "
                                                f"plus cause {cause_id!r} max "
                                                f"episode delay {max_slot_delay} "
                                                f"exceeds room {_room_lane}"
                                            )

                    draw_totals[draw] = draw_totals.get(draw, 0) + weight
                    worlds_db.append({
                        "world_id": wid,
                        "draw": draw,
                        "weight": weight,
                        "overrides": overrides,
                        "tags": tags,
                        "episodes": episodes,
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

    # ── SIM_END: latest schedulable date + max production_days ───────────────
    # Collect all dates the simulation may need to reach.
    # This runs after calendar is loaded because offer delay bounds use it.
    sim_end_candidates = [HORIZON]

    # planned and revised receipts of purchase_orders / disruptions
    for po in purchase_orders.values():
        sim_end_candidates.append(po["planned_receipt_date"])
    for dis in disruptions.values():
        sim_end_candidates.append(dis["revised_receipt_date"])

    # recovery purchase receipts (stage 1: calendar days only)
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

    # Worlds: receipt_date overrides, offer delay receipts (at DAY0), lane leads
    if worlds_db is not None:
        from engine.simulate import offer_receipt_date as _ord
        for w in worlds_db:
            for (ttype, tid, field), val in w["overrides"].items():
                if field == "receipt_date":
                    sim_end_candidates.append(val)
                elif ttype == "offer" and field == "delay_business_days":
                    offer = offers[tid]
                    offer_w = dict(offer)
                    offer_w["delay_business_days"] = val
                    rd = _ord(DAY0, offer_w, calendar)
                    # Bounds: must not exceed sampling cap
                    if rd > SAMPLING_CAP:
                        raise ValueError(
                            f"worlds.csv: offer {tid!r} delay_business_days {val} "
                            f"converts to receipt {rd} which exceeds the sampling cap "
                            f"({SAMPLING_CAP}, one year after DAY0)"
                        )
                    sim_end_candidates.append(rd)
                elif ttype == "lane" and field == "lead_days":
                    sim_end_candidates.append(DAY0 + timedelta(days=val))

    max_sched = max(sim_end_candidates)
    max_prod_days = max(p["production_days"] for p in products.values())
    SIM_END = max_sched + timedelta(days=max_prod_days)

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
        "causes": _causes,
        "cause_horizons": _cause_horizons,
        "scenarios": scenarios,
        "recovery_purchases": recovery_purchases,
        "recovery_transfers": recovery_transfers,
        "worlds": worlds_db,
        "worlds_format": worlds_format,
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
