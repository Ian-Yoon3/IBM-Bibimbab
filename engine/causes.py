import csv
from pathlib import Path

_HEADER = ["cause_id", "day_unit", "target_type", "target_id"]
_VALID_DAY_UNITS = {"business", "calendar"}
_VALID_TARGET_TYPES = {"purchase_order", "offer", "lane"}
_REQUIRED_UNIT = {
    "purchase_order": "business",
    "offer":          "business",
    "lane":           "calendar",
}
_PREFIX = "data/causes.csv: "


def load_causes(data_dir: Path, db: dict):
    """Load and validate data/causes.csv.

    Returns None if the file does not exist.
    Otherwise returns a list of dicts (file row order) with keys:
        cause_id, day_unit, target_type, target_id, source_id, lead_days, business
    """
    path = data_dir / "causes.csv"
    if not path.exists():
        return None

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        actual_header = list(reader.fieldnames or [])
        if actual_header != _HEADER:
            raise ValueError(
                f"{_PREFIX}header must be exactly "
                f"{','.join(_HEADER)}, got {','.join(actual_header)}"
            )
        raw_rows = list(reader)

    cause_day_unit: dict = {}
    seen_vkeys: set = set()
    source_to_causes: dict = {}
    result = []

    for row in raw_rows:
        cid   = row.get("cause_id",    "").strip()
        dunit = row.get("day_unit",    "").strip()
        ttype = row.get("target_type", "").strip()
        tid   = row.get("target_id",   "").strip()

        # (b) no empty field
        for field, val in [("cause_id", cid), ("day_unit", dunit),
                           ("target_type", ttype), ("target_id", tid)]:
            if not val:
                raise ValueError(
                    f"{_PREFIX}field '{field}' is empty in row {dict(row)}"
                )

        # (c) day_unit valid
        if dunit not in _VALID_DAY_UNITS:
            raise ValueError(
                f"{_PREFIX}day_unit must be 'business' or 'calendar', "
                f"got {dunit!r} in row {dict(row)}"
            )

        # (d) target_type valid
        if ttype not in _VALID_TARGET_TYPES:
            raise ValueError(
                f"{_PREFIX}target_type must be one of "
                f"{sorted(_VALID_TARGET_TYPES)}, got {ttype!r} in row {dict(row)}"
            )

        # (e) target_type determines required day_unit
        required_unit = _REQUIRED_UNIT[ttype]
        if dunit != required_unit:
            raise ValueError(
                f"{_PREFIX}target_type {ttype!r} requires day_unit "
                f"{required_unit!r}, got {dunit!r} for target {tid!r} "
                f"(cause {cid!r})"
            )

        # (f) one cause has one day_unit
        if cid in cause_day_unit:
            if cause_day_unit[cid] != dunit:
                raise ValueError(
                    f"{_PREFIX}cause {cid!r} has conflicting day_unit values "
                    f"({cause_day_unit[cid]!r} and {dunit!r})"
                )
        else:
            cause_day_unit[cid] = dunit

        # (g) (target_type, target_id) at most once
        vtuple = (ttype, tid)
        if vtuple in seen_vkeys:
            raise ValueError(
                f"{_PREFIX}({ttype!r}, {tid!r}) appears more than once"
            )
        seen_vkeys.add(vtuple)

        # (h) target_id exists; also resolve source_id and lead_days
        if ttype == "purchase_order":
            if tid not in db.get("purchase_orders", {}):
                raise ValueError(
                    f"{_PREFIX}target_id {tid!r} is not in purchase_orders "
                    f"(row {dict(row)})"
                )
            offer_id  = db["purchase_orders"][tid]["offer_id"]
            source_id = offer_id
            lead_days = db["offers"][offer_id]["lead_days"]
        elif ttype == "offer":
            if tid not in db.get("offers", {}):
                raise ValueError(
                    f"{_PREFIX}target_id {tid!r} is not in supplier_offers "
                    f"(row {dict(row)})"
                )
            source_id = tid
            lead_days = db["offers"][tid]["lead_days"]
        else:  # lane
            if tid not in db.get("lanes", {}):
                raise ValueError(
                    f"{_PREFIX}target_id {tid!r} is not in transfer_lanes "
                    f"(row {dict(row)})"
                )
            source_id = tid
            lead_days = db["lanes"][tid]["lead_days"]

        # (i) a source belongs to one cause only (same cause is allowed)
        existing_causes = source_to_causes.get(source_id, set())
        if existing_causes and cid not in existing_causes:
            other = next(iter(existing_causes))
            raise ValueError(
                f"{_PREFIX}source {source_id!r} is in both cause {other!r} "
                f"and cause {cid!r}; a source may belong to one cause only"
            )
        if source_id not in source_to_causes:
            source_to_causes[source_id] = set()
        source_to_causes[source_id].add(cid)

        result.append({
            "cause_id":    cid,
            "day_unit":    dunit,
            "target_type": ttype,
            "target_id":   tid,
            "source_id":   source_id,
            "lead_days":   lead_days,
            "business":    dunit == "business",
        })

    return result
