"""History generator for the stage 2 Monte Carlo engine.

Generates synthetic shipment and episode history over the twelve months
before DAY0.  Standard library only (csv, math, pathlib, random, datetime).
engine.loader.load_all is used for DAY0, offer/lane lead times and the
business calendar.  See docs/montecarlo-engine.md sections 6.1 – 6.3.

generate_history(data_dir, out_dir, seed) -> dict
    Writes data/history/shipments.csv and data/history/episodes.csv.
    Returns a dict of internals (own delays keyed by shipment_id) for
    testing.  The own delay of each shipment is the signed business-day
    or calendar-day distance from promised to receipt MINUS the episode
    severity (0 when no episode).  Clamped shipments are flagged in the
    internals dict as well.

True parameters (section 6.3) are module-level constants.  The estimator
in a later step never reads them; it works from the CSV files only.
"""

import csv
import math
import pathlib
import random
from datetime import date, timedelta

from engine.loader import load_all

# ---------------------------------------------------------------------------
# True parameters (section 6.3) — estimator never reads these
# ---------------------------------------------------------------------------

# OF01: 0.20 early / 0.30 on-time / 0.50 late, mean size 2 (business days)
OF01_P_EARLY  = 0.20
OF01_P_ONTIME = 0.30
OF01_P_LATE   = 0.50
OF01_MEAN_SIZE = 2        # 1 + Geometric({0,1,...}, mean = m-1 = 1)

# OF02: 0.10 / 0.60 / 0.30, mean size 1.5 (business days)
OF02_P_EARLY  = 0.10
OF02_P_ONTIME = 0.60
OF02_P_LATE   = 0.30
OF02_MEAN_SIZE = 1.5

# LN01, LN02: 0.05 / 0.75 / 0.20, mean size 1.5 (calendar days)
LN_P_EARLY  = 0.05
LN_P_ONTIME = 0.75
LN_P_LATE   = 0.20
LN_MEAN_SIZE = 1.5

# K1: 4 episodes/year, severity mean 3, duration mean 3 (business days)
K1_RATE     = 4.0
K1_SEV_MEAN = 3     # days
K1_DUR_MEAN = 3     # days

# K2: 5 episodes/year, severity mean 2, duration mean 2 (calendar days)
K2_RATE     = 5.0
K2_SEV_MEAN = 2
K2_DUR_MEAN = 2

# Shipment counts per source (kept as constants; causes.csv sets order/config)
N_OF01 = 12
N_OF02 = 6
N_LN01 = 15
N_LN02 = 10

# Map source_id -> (p_early, p_ontime, p_late, mean_size, n_shipments)
# Used by generate_history after the sources are resolved from causes.csv.
_SOURCE_PARAMS = {
    "OF01": (OF01_P_EARLY, OF01_P_ONTIME, OF01_P_LATE, OF01_MEAN_SIZE, N_OF01),
    "OF02": (OF02_P_EARLY, OF02_P_ONTIME, OF02_P_LATE, OF02_MEAN_SIZE, N_OF02),
    "LN01": (LN_P_EARLY,   LN_P_ONTIME,   LN_P_LATE,   LN_MEAN_SIZE,   N_LN01),
    "LN02": (LN_P_EARLY,   LN_P_ONTIME,   LN_P_LATE,   LN_MEAN_SIZE,   N_LN02),
}

# ---------------------------------------------------------------------------
# causes.csv reader and validator
# ---------------------------------------------------------------------------

_CAUSES_HEADER = ["cause_id", "day_unit", "target_type", "target_id"]
_VALID_DAY_UNITS = {"business", "calendar"}
_VALID_TARGET_TYPES = {"purchase_order", "offer", "lane"}


def _load_causes(data_dir: pathlib.Path, db: dict) -> list:
    """Read and validate data/history/causes.csv.

    Returns a list of dicts with keys:
        cause_id, day_unit, source_id, lead_days, business (bool)
    in the order the rows appear in the file.

    Raises ValueError naming the file and the offending row for any
    validation error.
    """
    fname = "data/history/causes.csv"
    path  = data_dir / "history" / "causes.csv"

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        actual_header = list(reader.fieldnames or [])
        if actual_header != _CAUSES_HEADER:
            raise ValueError(
                f"{fname}: header must be exactly "
                f"{','.join(_CAUSES_HEADER)}, got {','.join(actual_header)}"
            )
        raw_rows = list(reader)

    # Validate day_unit per cause (must be consistent across rows)
    cause_day_unit: dict[str, str] = {}
    result = []

    for row in raw_rows:
        cid   = row.get("cause_id", "").strip()
        dunit = row.get("day_unit", "").strip()
        ttype = row.get("target_type", "").strip()
        tid   = row.get("target_id", "").strip()

        # Required fields
        for field, val in [("cause_id", cid), ("day_unit", dunit),
                           ("target_type", ttype), ("target_id", tid)]:
            if not val:
                raise ValueError(
                    f"{fname}: field '{field}' is empty in row {dict(row)}"
                )

        # day_unit must be valid
        if dunit not in _VALID_DAY_UNITS:
            raise ValueError(
                f"{fname}: day_unit must be 'business' or 'calendar', "
                f"got {dunit!r} in row {dict(row)}"
            )

        # day_unit must be consistent within a cause
        if cid in cause_day_unit:
            if cause_day_unit[cid] != dunit:
                raise ValueError(
                    f"{fname}: cause {cid!r} has conflicting day_unit values "
                    f"({cause_day_unit[cid]!r} and {dunit!r})"
                )
        else:
            cause_day_unit[cid] = dunit

        # target_type must be valid
        if ttype not in _VALID_TARGET_TYPES:
            raise ValueError(
                f"{fname}: target_type must be one of "
                f"{sorted(_VALID_TARGET_TYPES)}, got {ttype!r} in row {dict(row)}"
            )

        # Resolve source_id and lead_days from the base data
        if ttype == "purchase_order":
            pos = db.get("purchase_orders", {})
            if tid not in pos:
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in purchase_orders "
                    f"(row {dict(row)})"
                )
            offer_id = pos[tid]["offer_id"]
            source_id = offer_id
            lead_days = db["offers"][offer_id]["lead_days"]
        elif ttype == "offer":
            if tid not in db.get("offers", {}):
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in supplier_offers "
                    f"(row {dict(row)})"
                )
            source_id = tid
            lead_days = db["offers"][tid]["lead_days"]
        else:  # lane
            if tid not in db.get("lanes", {}):
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in transfer_lanes "
                    f"(row {dict(row)})"
                )
            source_id = tid
            lead_days = db["lanes"][tid]["lead_days"]

        result.append({
            "cause_id":  cid,
            "day_unit":  dunit,
            "source_id": source_id,
            "lead_days": lead_days,
            "business":  dunit == "business",
        })

    return result


# ---------------------------------------------------------------------------
# Geometric on {0, 1, 2, ...} with mean m
# P(k) = t*(1-t)^k,  t = 1/(1+m)
# ---------------------------------------------------------------------------

def _geom_non_neg(rng: random.Random, mean: float) -> int:
    """Sample Geometric on {0, 1, 2, ...} with given mean (>= 0).

    P(k) = t*(1-t)^k,  t = 1/(1+mean).
    Uses the floor(log(U) / log(1-t)) inverse-CDF form.
    """
    if mean <= 0:
        return 0
    t = 1.0 / (1.0 + mean)
    if t >= 1.0:
        return 0
    u = rng.random()
    if u <= 0.0:
        u = 1e-15
    return int(math.floor(math.log(u) / math.log(1.0 - t)))


def _own_delay_sample(rng: random.Random, p_early: float, p_ontime: float,
                      p_late: float, mean_size: float) -> int:
    """Sample own delay.  Negative = early, 0 = on time, positive = late.

    Size = 1 + Geometric({0,1,...}, mean = mean_size - 1).
    """
    u = rng.random()
    if u < p_early:
        size = 1 + _geom_non_neg(rng, mean_size - 1)
        return -size
    elif u < p_early + p_ontime:
        return 0
    else:
        size = 1 + _geom_non_neg(rng, mean_size - 1)
        return size


# ---------------------------------------------------------------------------
# Episode generation (section 6.3 / spec step 1)
# ---------------------------------------------------------------------------

def _generate_episodes(rng: random.Random, cause_id: str, rate: float,
                       sev_mean: float, dur_mean: float,
                       period_start: date, period_end: date) -> list:
    """Generate episodes for one cause.

    Exponential inter-arrivals: gap = floor(Exponential(365/rate)).
    Duration = 1 + Geometric({0,1,...}, mean = dur_mean - 1).
    Severity  = 1 + Geometric({0,1,...}, mean = sev_mean - 1).
    Episodes never overlap (each starts the day after the previous ends + gap).
    Stop when a start passes period_end.
    An episode still running on (period_end + 1) = DAY0 gets empty end_date.
    """
    day0     = period_end + timedelta(days=1)   # = DAY0
    mean_gap = 365.0 / rate                     # mean inter-arrival in days

    episodes = []
    idx = 1

    # First episode starts at period_start + floor(Exponential gap)
    next_start = period_start

    while True:
        u = rng.random()
        if u <= 0.0:
            u = 1e-15
        gap   = int(math.floor(-mean_gap * math.log(u)))
        start = next_start + timedelta(days=gap)

        if start > period_end:
            break

        dur = 1 + _geom_non_neg(rng, dur_mean - 1)
        sev = 1 + _geom_non_neg(rng, sev_mean - 1)
        end = start + timedelta(days=dur - 1)

        # Episode open on DAY0?
        if end >= day0:
            end_date_str    = ""
            end_for_overlap = period_end   # treat as running until period_end
        else:
            end_date_str    = end.isoformat()
            end_for_overlap = end

        eid = f"{cause_id}E{idx:03d}"
        episodes.append({
            "episode_id": eid,
            "cause_id":   cause_id,
            "start_date": start.isoformat(),
            "end_date":   end_date_str,
            "delay_days": sev,
            # internal Python objects for matching
            "_start": start,
            "_end":   end_for_overlap,
        })
        idx += 1

        # Next episode starts the day after this one ends + exponential gap
        next_start = end_for_overlap + timedelta(days=1)

    return episodes


# ---------------------------------------------------------------------------
# Shipment schedule (section 6.3 / spec step 2)
# ship_i = period_start + floor((i + 0.5) * 365 / n)   for i = 0..n-1
# ---------------------------------------------------------------------------

def _shipment_schedule(period_start: date, n: int, business: bool, cal) -> list:
    """Return n ship dates inside the period.

    cal is a BusinessCalendar instance; used only when business=True.
    """
    dates = []
    for i in range(n):
        offset = int(math.floor((i + 0.5) * 365.0 / n))
        d = period_start + timedelta(days=offset)
        if business:
            d = cal.next_business_day(d)
        dates.append(d)
    return dates


# ---------------------------------------------------------------------------
# Main generate_history function
# ---------------------------------------------------------------------------

def generate_history(data_dir, out_dir, seed: int) -> dict:
    """Generate synthetic shipment and episode history.

    Parameters
    ----------
    data_dir : str or Path
        Path to the base data directory.  Must contain the standard engine
        CSV files (disruptions.csv etc.) and data/history/causes.csv.
        If data/closed_days.csv is present it is honoured.
    out_dir : str or Path
        Directory to write shipments.csv and episodes.csv into.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict
        Internals for testing.  Keys:
          "own_delays"   : {shipment_id: int}  signed own delay in the
                           source's day unit (negative = early).
          "clamped"      : {shipment_id: bool}  True if receipt was clamped.
          "in_transit"   : [shipment_id]  shipments not yet received on DAY0,
                           left out of shipments.csv.
    """
    rng      = random.Random(seed)
    data_dir = pathlib.Path(data_dir)

    # Load base data: DAY0, offers, lanes, calendar (honours closed_days.csv)
    db  = load_all(data_dir)
    cal = db["calendar"]
    day0 = db["DAY0"]

    period_start = day0 - timedelta(days=365)
    period_end   = day0 - timedelta(days=1)

    # Read causes.csv to build source config
    source_rows = _load_causes(data_dir, db)

    # Map cause_id -> (rate, sev_mean, dur_mean) from constants
    cause_params = {
        "K1": (K1_RATE, K1_SEV_MEAN, K1_DUR_MEAN),
        "K2": (K2_RATE, K2_SEV_MEAN, K2_DUR_MEAN),
    }

    # 1. Generate episodes for each cause (in first-seen order from causes.csv)
    seen_causes: dict[str, list] = {}
    for row in source_rows:
        cid = row["cause_id"]
        if cid not in seen_causes:
            rate, sev_mean, dur_mean = cause_params[cid]
            seen_causes[cid] = _generate_episodes(
                rng, cid, rate, sev_mean, dur_mean, period_start, period_end
            )

    # 2. & 3. & 4. Generate shipments for each source (order = causes.csv rows)
    all_shipments: list = []
    own_delays:    dict = {}
    clamped:       dict = {}
    in_transit:    list = []
    shipment_index: dict[str, int] = {}   # source_id -> running counter

    for row in source_rows:
        src_id   = row["source_id"]
        is_biz   = row["business"]
        lead     = row["lead_days"]
        cause    = row["cause_id"]
        eps      = seen_causes[cause]

        p_early, p_ontime, p_late, mean_size, n = _SOURCE_PARAMS[src_id]

        ship_dates = _shipment_schedule(period_start, n, is_biz, cal)

        for i, ship in enumerate(ship_dates, start=1):
            # promised = ship + lead_days (calendar), snapped to next business
            # day for business-day sources
            promised = ship + timedelta(days=lead)
            if is_biz:
                promised = cal.next_business_day(promised)

            # First episode whose [start, end] overlaps [ship, promised]
            matched_ep = None
            for ep in eps:
                if ep["_start"] <= promised and ep["_end"] >= ship:
                    matched_ep = ep
                    break

            sev = matched_ep["delay_days"] if matched_ep else 0

            # Own delay
            own = _own_delay_sample(rng, p_early, p_ontime, p_late, mean_size)

            # Receipt
            total_shift = own + sev
            if is_biz:
                receipt = cal.add_business_days(promised, total_shift)
            else:
                receipt = promised + timedelta(days=total_shift)

            # Clamp: receipt must be strictly after ship
            was_clamped = False
            if receipt <= ship:
                was_clamped = True
                if is_biz:
                    receipt = cal.next_business_day(ship + timedelta(days=1))
                else:
                    receipt = ship + timedelta(days=1)

            sid = f"{src_id}{i:03d}"
            if receipt > day0:
                # Still in transit on the decision day: no receipt is known yet,
                # so the shipment is not part of the history.
                in_transit.append(sid)
                continue
            all_shipments.append({
                "shipment_id":   sid,
                "source_id":     src_id,
                "ship_date":     ship.isoformat(),
                "promised_date": promised.isoformat(),
                "receipt_date":  receipt.isoformat(),
                "episode_id":    matched_ep["episode_id"] if matched_ep else "",
            })
            own_delays[sid] = own
            clamped[sid]    = was_clamped

    # 5. Write CSV files
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_shipments(all_shipments, out_dir / "shipments.csv")
    # episodes in causes.csv row order (preserves K1 before K2)
    all_episodes = []
    for cid in seen_causes:
        all_episodes.extend(seen_causes[cid])
    _write_episodes(all_episodes, out_dir / "episodes.csv")

    # Write period.csv
    with (out_dir / "period.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["start_date", "end_date"])
        w.writerow([period_start.isoformat(), period_end.isoformat()])

    return {"own_delays": own_delays, "clamped": clamped, "in_transit": in_transit}


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

_SHIPMENT_HEADER = ["shipment_id", "source_id", "ship_date",
                    "promised_date", "receipt_date", "episode_id"]
_EPISODE_HEADER  = ["episode_id", "cause_id", "start_date",
                    "end_date", "delay_days"]


def _write_shipments(rows: list, path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_SHIPMENT_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in _SHIPMENT_HEADER})


def _write_episodes(eps: list, path: pathlib.Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_EPISODE_HEADER)
        w.writeheader()
        for e in eps:
            w.writerow({k: e[k] for k in _EPISODE_HEADER})
