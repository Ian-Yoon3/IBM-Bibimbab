"""Bayesian estimator for the stage 2 Monte Carlo engine.

estimate(data_dir) -> dict

Reads:
  - Standard engine CSVs via engine.loader.load_all(data_dir) for DAY0,
    the business calendar, offers, lanes, purchase orders and disruptions.
  - data/history/causes.csv, shipments.csv, episodes.csv, period.csv.

Returns a dict with keys:
  "causes"    : {cause_id: cause_posterior}
  "variables" : {"<target_type>.<target_id>": variable_posterior}
               e.g. "purchase_order.PO01", "offer.OF02", "lane.LN01"

cause_posterior keys:
  n, S, open_on_day0, w_days, T_days, rate_shape, rate_rate,
  p_active, severity_a, severity_b

variable_posterior keys:
  cause_id, day_unit, source_id, records,
  n_early, n_ontime, n_late,
  dir_early, dir_ontime, dir_late,   (Dirichlet alpha parameters)
  early_a, early_b,                  (Beta for size-1 of early delays)
  late_a, late_b,                    (Beta for size-1 of late delays)
  prior_share

predictive_size_pmf is a module-level function (not in the returned dict).

Section 7.1 posteriors (uniform/Bayes-Laplace priors), T = period length in days:
  rate lambda:   Gamma(n+1, T)   [rate parameter T means scale = 1/T]
  P(active):     1 if open_on_day0 else 1-(1+w/T)^-(n+1)
  severity theta: Beta(n+1, S+1)      S = sum of (delay_days - 1)
  category:      Dirichlet(counts + 1)
  size theta:    Beta(count+1, sum_of_(size-1)+1)
  prior_share:   3 / (records + 3)   (3 pseudo-records from Dirichlet prior)
"""

import csv
import math
import pathlib
from datetime import date, timedelta
from fractions import Fraction

from engine.loader import load_all

# ---------------------------------------------------------------------------
# History file headers (exact)
# ---------------------------------------------------------------------------

_CAUSES_HEADER    = ["cause_id", "day_unit", "target_type", "target_id"]
_SHIPMENTS_HEADER = ["shipment_id", "source_id", "ship_date",
                     "promised_date", "receipt_date", "episode_id"]
_EPISODES_HEADER  = ["episode_id", "cause_id", "start_date",
                     "end_date", "delay_days"]
_PERIOD_HEADER    = ["start_date", "end_date"]


# ---------------------------------------------------------------------------
# CSV reader with header validation
# ---------------------------------------------------------------------------

def _read_history_csv(path: pathlib.Path, expected_header: list) -> list:
    fname = str(path)
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        actual = list(reader.fieldnames or [])
        if actual != expected_header:
            raise ValueError(
                f"{fname}: header must be exactly "
                f"{','.join(expected_header)}, got {','.join(actual)}"
            )
        return list(reader)


# ---------------------------------------------------------------------------
# Period reader
# ---------------------------------------------------------------------------

def _read_period(hist_dir: pathlib.Path) -> tuple:
    """Read period.csv and return (period_start, period_end, T_days).

    Raises ValueError if file is missing or malformed.
    """
    fname = "data/history/period.csv"
    path  = hist_dir / "period.csv"
    if not path.exists():
        raise ValueError(
            f"{fname}: file is missing; every history must have a period.csv"
        )
    rows = _read_history_csv(path, _PERIOD_HEADER)
    if len(rows) != 1:
        raise ValueError(
            f"{fname}: must contain exactly one data row, got {len(rows)}"
        )
    row = rows[0]
    try:
        period_start = date.fromisoformat(row["start_date"])
        period_end   = date.fromisoformat(row["end_date"])
    except (ValueError, KeyError) as exc:
        raise ValueError(f"{fname}: invalid date in row {dict(row)}: {exc}") from exc
    if period_end < period_start:
        raise ValueError(
            f"{fname}: end_date {period_end} is before start_date {period_start}"
        )
    T_days = (period_end - period_start).days + 1
    return period_start, period_end, T_days


# ---------------------------------------------------------------------------
# Causes loader with full validation
# ---------------------------------------------------------------------------

def _load_causes_meta(data_dir: pathlib.Path, db: dict) -> tuple:
    """Parse causes.csv and return three structures.

    Validation rules (each raises ValueError naming the problem):
      - header must be exactly cause_id,day_unit,target_type,target_id
      - purchase_order and offer must use day_unit 'business'
      - lane must use day_unit 'calendar'
      - a (target_type, target_id) pair may not appear twice
      - a source may belong to at most one cause
      - all target_ids must exist in the base data

    Several variables may share one source (purchase_order.PO01 and offer.OF01
    can both use source OF01). The source_to_causes map stores all causes for a
    source; for the single-cause constraint it checks ONLY that the same source
    is not in TWO DIFFERENT causes (same cause is allowed).

    Returns
    -------
    causes : dict  {cause_id: {day_unit, entries, targets}}
    source_to_causes : dict  {source_id: set of cause_ids}
    """
    fname = "data/history/causes.csv"
    path  = data_dir / "history" / "causes.csv"
    rows  = _read_history_csv(path, _CAUSES_HEADER)

    causes: dict = {}
    source_to_causes: dict = {}   # source_id -> set of cause_ids
    seen_vkeys: set = set()       # (ttype, tid) pairs already seen

    _REQUIRED_UNIT = {
        "purchase_order": "business",
        "offer":          "business",
        "lane":           "calendar",
    }

    for row in rows:
        cid   = row["cause_id"]
        dunit = row["day_unit"]
        ttype = row["target_type"]
        tid   = row["target_id"]
        vkey  = f"{ttype}.{tid}"

        # day_unit must match target_type
        if ttype in _REQUIRED_UNIT:
            expected_unit = _REQUIRED_UNIT[ttype]
            if dunit != expected_unit:
                raise ValueError(
                    f"{fname}: target_type {ttype!r} requires day_unit "
                    f"{expected_unit!r}, got {dunit!r} for target {tid!r} "
                    f"(cause {cid!r})"
                )
        else:
            raise ValueError(
                f"{fname}: unknown target_type {ttype!r} in row {dict(row)}"
            )

        # (ttype, tid) must not appear twice
        vtuple = (ttype, tid)
        if vtuple in seen_vkeys:
            raise ValueError(
                f"{fname}: ({ttype!r}, {tid!r}) appears more than once"
            )
        seen_vkeys.add(vtuple)

        # Resolve source_id and validate target exists
        if ttype == "purchase_order":
            if tid not in db.get("purchase_orders", {}):
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in purchase_orders "
                    f"(row {dict(row)})"
                )
            source_id = db["purchase_orders"][tid]["offer_id"]
        elif ttype == "offer":
            if tid not in db.get("offers", {}):
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in supplier_offers "
                    f"(row {dict(row)})"
                )
            source_id = tid
        else:  # lane
            if tid not in db.get("lanes", {}):
                raise ValueError(
                    f"{fname}: target_id {tid!r} is not in transfer_lanes "
                    f"(row {dict(row)})"
                )
            source_id = tid

        # A source may belong to at most one cause
        existing_causes = source_to_causes.get(source_id, set())
        if existing_causes and cid not in existing_causes:
            other = next(iter(existing_causes))
            raise ValueError(
                f"{fname}: source {source_id!r} is in both cause {other!r} "
                f"and cause {cid!r}; a source may belong to one cause only"
            )

        if cid not in causes:
            causes[cid] = {"day_unit": dunit, "entries": [], "targets": []}
        causes[cid]["entries"].append({"ttype": ttype, "tid": tid,
                                       "source_id": source_id, "vkey": vkey})
        causes[cid]["targets"].append({"ttype": ttype, "tid": tid})

        if source_id not in source_to_causes:
            source_to_causes[source_id] = set()
        source_to_causes[source_id].add(cid)

    return causes, source_to_causes


# ---------------------------------------------------------------------------
# Exposure window w_k (section 4.7)
# purchase_order -> disruption's revised_receipt_date
# offer          -> calendar.next_business_day(DAY0 + lead_days)
# lane           -> DAY0 + lead_days (calendar days)
# w = max over all targets of that cause, in calendar days from DAY0
# ---------------------------------------------------------------------------

def _exposure_days(db: dict, targets: list) -> int:
    """Return w_k in calendar days from DAY0."""
    day0 = db["DAY0"]
    cal  = db["calendar"]
    latest = day0

    for t in targets:
        ttype = t["ttype"]
        tid   = t["tid"]
        if ttype == "purchase_order":
            for dis in db["disruptions"].values():
                if dis["po_id"] == tid:
                    arr = dis["revised_receipt_date"]
                    break
            else:
                raise ValueError(f"No disruption found for purchase_order {tid!r}")
        elif ttype == "offer":
            lead = db["offers"][tid]["lead_days"]
            arr  = cal.next_business_day(day0 + timedelta(days=lead))
        else:  # lane
            lead = db["lanes"][tid]["lead_days"]
            arr  = day0 + timedelta(days=lead)

        if arr > latest:
            latest = arr

    return (latest - day0).days


# ---------------------------------------------------------------------------
# Predictive PMF helper (section 7.1)
# P(size - 1 = k | Beta(a, b) prior) = B(a+1, b+k) / B(a, b)
# B(a, b) = Gamma(a)*Gamma(b)/Gamma(a+b)  (a, b positive integers)
# ---------------------------------------------------------------------------

def _beta_fraction(a: int, b: int) -> Fraction:
    """B(a, b) = (a-1)! * (b-1)! / (a+b-1)! as a Fraction (a, b >= 1 integers)."""
    num = Fraction(1)
    for k in range(1, b):       # (b-1)!
        num *= k
    den = Fraction(1)
    for k in range(a, a + b):   # a * (a+1) * ... * (a+b-1)
        den *= k
    return num / den


def predictive_size_pmf(a: int, b: int, k: int) -> Fraction:
    """P(size - 1 = k) under Geometric(theta), theta ~ Beta(a, b).

    = B(a+1, b+k) / B(a, b)   for non-negative integer k.
    """
    return _beta_fraction(a + 1, b + k) / _beta_fraction(a, b)


# ---------------------------------------------------------------------------
# Main estimator
# ---------------------------------------------------------------------------

def estimate(data_dir) -> dict:
    """Estimate all model parameters from history.

    Parameters
    ----------
    data_dir : str or Path
        Base data directory.  Must contain the standard engine CSVs and
        data/history/{causes,shipments,episodes,period}.csv.

    Returns
    -------
    dict with keys "causes" and "variables".
    """
    data_dir = pathlib.Path(data_dir)
    db       = load_all(data_dir)
    cal      = db["calendar"]
    day0     = db["DAY0"]
    hist_dir = data_dir / "history"

    # 0. Read period
    period_start, period_end, T_days = _read_period(hist_dir)
    if period_end >= day0:
        raise ValueError(
            f"data/history/period.csv: period end_date {period_end} must be "
            f"before DAY0 {day0}"
        )

    # 1a. Load and validate episodes
    ep_rows = _read_history_csv(hist_dir / "episodes.csv", _EPISODES_HEADER)
    episodes: dict = {}
    for row in ep_rows:
        eid = row["episode_id"]
        if not eid:
            raise ValueError(
                f"data/history/episodes.csv: episode_id is empty in row {dict(row)}"
            )
        if eid in episodes:
            raise ValueError(
                f"data/history/episodes.csv: duplicate episode_id {eid!r}"
            )
        start_d = date.fromisoformat(row["start_date"])
        if start_d > day0:
            raise ValueError(
                f"data/history/episodes.csv: episode {eid!r} starts after DAY0 "
                f"({start_d} > {day0})"
            )
        if start_d < period_start:
            raise ValueError(
                f"data/history/episodes.csv: episode {eid!r} start_date {start_d} "
                f"is before period start {period_start}"
            )
        # Open on DAY0: end_date empty OR end_date >= DAY0
        end_str = row["end_date"]
        if end_str:
            end_d = date.fromisoformat(end_str)
            open_on_day0 = (end_d >= day0)
        else:
            open_on_day0 = True

        episodes[eid] = {
            "episode_id":    eid,
            "cause_id":      row["cause_id"],
            "start_date":    row["start_date"],
            "end_date":      end_str,
            "delay_days":    int(row["delay_days"]),
            "open_on_day0":  open_on_day0,
        }

    # 1b. Load causes meta (for source->cause mapping)
    causes_meta, source_to_causes = _load_causes_meta(data_dir, db)

    # Build source_to_cause (single cause per source is validated above)
    source_to_cause: dict = {
        src: next(iter(cids)) for src, cids in source_to_causes.items()
    }

    # 1c. Load and validate shipments
    ship_rows = _read_history_csv(hist_dir / "shipments.csv", _SHIPMENTS_HEADER)
    for row in ship_rows:
        sid      = row["shipment_id"]
        src      = row["source_id"]
        eid      = row["episode_id"]
        ship_d   = date.fromisoformat(row["ship_date"])
        receipt_d = date.fromisoformat(row["receipt_date"])

        if ship_d < period_start or ship_d > period_end:
            raise ValueError(
                f"data/history/shipments.csv: shipment {sid!r} ship_date "
                f"{ship_d} is outside the period [{period_start}, {period_end}]"
            )
        if receipt_d > day0:
            raise ValueError(
                f"data/history/shipments.csv: shipment {sid!r} receipt_date "
                f"{receipt_d} is after DAY0 {day0}"
            )

        if eid:
            if eid not in episodes:
                raise ValueError(
                    f"data/history/shipments.csv: shipment {sid!r} "
                    f"references unknown episode_id {eid!r}"
                )
            ep_cause  = episodes[eid]["cause_id"]
            src_cause = source_to_cause.get(src)
            if src_cause is None:
                raise ValueError(
                    f"data/history/shipments.csv: shipment {sid!r} "
                    f"source {src!r} not found in causes.csv"
                )
            if ep_cause != src_cause:
                raise ValueError(
                    f"data/history/shipments.csv: shipment {sid!r} "
                    f"source {src!r} (cause {src_cause!r}) references "
                    f"episode {eid!r} of cause {ep_cause!r}"
                )

    # 2. Compute own delays and accumulate per-variable stats
    # Per-variable accumulators keyed by "ttype.tid"
    var_stats: dict = {}
    for cid, meta in causes_meta.items():
        for entry in meta["entries"]:
            vkey = entry["vkey"]
            var_stats[vkey] = {
                "cause_id":    cid,
                "day_unit":    meta["day_unit"],
                "source_id":   entry["source_id"],
                "ttype":       entry["ttype"],
                "tid":         entry["tid"],
                "records":     0,
                "n_early":     0, "n_ontime": 0, "n_late": 0,
                "early_count": 0, "early_sum": 0,
                "late_count":  0, "late_sum":  0,
            }

    # Build source_id -> [vkeys] map (a source may appear in multiple vkeys)
    source_to_vkeys: dict = {}
    for vkey, st in var_stats.items():
        src = st["source_id"]
        if src not in source_to_vkeys:
            source_to_vkeys[src] = []
        source_to_vkeys[src].append(vkey)

    for row in ship_rows:
        src  = row["source_id"]
        prom = date.fromisoformat(row["promised_date"])
        rcpt = date.fromisoformat(row["receipt_date"])
        eid  = row["episode_id"]
        sev  = episodes[eid]["delay_days"] if eid else 0

        # Each shipment contributes to ALL vkeys sharing this source
        vkeys_for_src = source_to_vkeys.get(src, [])
        for vkey in vkeys_for_src:
            day_unit = var_stats[vkey]["day_unit"]

            if day_unit == "business":
                if rcpt > prom:
                    raw = cal.business_days_between(prom, rcpt)
                elif rcpt < prom:
                    raw = -cal.business_days_between(rcpt, prom)
                else:
                    raw = 0
            else:
                raw = (rcpt - prom).days

            own = raw - sev
            st  = var_stats[vkey]
            st["records"] += 1

            if own < 0:
                st["n_early"]     += 1
                st["early_count"] += 1
                st["early_sum"]   += (-own) - 1
            elif own == 0:
                st["n_ontime"] += 1
            else:
                st["n_late"]    += 1
                st["late_count"] += 1
                st["late_sum"]   += own - 1

    # 3. Per-cause stats
    cause_stats: dict = {}
    for cid in causes_meta:
        cause_stats[cid] = {
            "n":            0,
            "S":            0,
            "open_on_day0": False,
        }

    for ep in episodes.values():
        cid = ep["cause_id"]
        if cid not in cause_stats:
            raise ValueError(
                f"data/history/episodes.csv: episode {ep['episode_id']!r} "
                f"references unknown cause {cid!r}"
            )
        cs = cause_stats[cid]
        cs["n"] += 1
        cs["S"] += ep["delay_days"] - 1
        if ep["open_on_day0"]:
            cs["open_on_day0"] = True

    # 4. Exposure windows
    for cid, meta in causes_meta.items():
        w = _exposure_days(db, meta["targets"])
        cause_stats[cid]["w_days"] = w

    # 5. Build posteriors

    # --- cause posteriors ---
    cause_posteriors: dict = {}
    for cid, cs in cause_stats.items():
        n            = cs["n"]
        S            = cs["S"]
        open_on_day0 = cs["open_on_day0"]
        w            = cs["w_days"]

        rate_shape = n + 1    # Gamma(n+1, T)
        rate_rate  = T_days   # rate parameter T (scale = 1/T per day)

        if open_on_day0:
            p_active = 1.0
        else:
            # P(active) = 1 - (1 + w/T)^-(n+1)
            p_active = 1.0 - (1.0 + w / T_days) ** (-(n + 1))

        severity_a = n + 1
        severity_b = S + 1

        cause_posteriors[cid] = {
            "n":            n,
            "S":            S,
            "open_on_day0": open_on_day0,
            "w_days":       w,
            "T_days":       T_days,
            "rate_shape":   rate_shape,
            "rate_rate":    rate_rate,
            "p_active":     p_active,
            "severity_a":   severity_a,
            "severity_b":   severity_b,
        }

    # --- variable posteriors ---
    var_posteriors: dict = {}
    for vkey, st in var_stats.items():
        records  = st["records"]
        n_early  = st["n_early"]
        n_ontime = st["n_ontime"]
        n_late   = st["n_late"]

        dir_early  = n_early  + 1
        dir_ontime = n_ontime + 1
        dir_late   = n_late   + 1

        early_a = st["early_count"] + 1
        early_b = st["early_sum"]   + 1
        late_a  = st["late_count"]  + 1
        late_b  = st["late_sum"]    + 1

        prior_share = 3.0 / (records + 3.0)

        var_posteriors[vkey] = {
            "cause_id":   st["cause_id"],
            "day_unit":   st["day_unit"],
            "source_id":  st["source_id"],
            "records":    records,
            "n_early":    n_early,
            "n_ontime":   n_ontime,
            "n_late":     n_late,
            "dir_early":  dir_early,
            "dir_ontime": dir_ontime,
            "dir_late":   dir_late,
            "early_a":    early_a,
            "early_b":    early_b,
            "late_a":     late_a,
            "late_b":     late_b,
            "prior_share": prior_share,
        }

    return {
        "causes":    cause_posteriors,
        "variables": var_posteriors,
    }
