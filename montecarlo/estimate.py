"""Bayesian estimator for the stage 2 Monte Carlo engine.

estimate(data_dir) -> dict

Reads:
  - Standard engine CSVs via engine.loader.load_all(data_dir) for DAY0,
    the business calendar, offers, lanes, purchase orders and disruptions.
  - data/history/causes.csv, shipments.csv, episodes.csv.

Returns a dict with keys:
  "causes"    : {cause_id: cause_posterior}
  "variables" : {source_id: variable_posterior}

cause_posterior keys:
  n, S, open_on_day0, w_days, rate_shape, rate_rate,
  p_active, severity_a, severity_b, prior_share_rate

variable_posterior keys:
  source_id, records,
  n_early, n_ontime, n_late,
  dir_early, dir_ontime, dir_late,   (Dirichlet alpha parameters)
  early_a, early_b,                  (Beta for size-1 of early delays)
  late_a, late_b,                    (Beta for size-1 of late delays)
  prior_share

Also top-level key:
  "predictive_size_pmf": the helper function (a, b, k) -> Fraction

Section 7.1 posteriors (uniform/Bayes-Laplace priors):
  rate lambda:   Gamma(n+1, rate=1 per year)
  P(active):     1 if open_on_day0 else 1-(1+w/365)^-(n+1)
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

# History length used for the rate posterior (1 year = 365 days)
_HISTORY_DAYS = 365


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
# Causes loader (mirrors generator._load_causes without producing source config)
# ---------------------------------------------------------------------------

def _load_causes_meta(data_dir: pathlib.Path, db: dict) -> dict:
    """Return {cause_id: {day_unit, sources: [source_id, ...], targets: [...]}}
    plus a reverse map {source_id: cause_id}.

    targets are raw target dicts from causes.csv.
    """
    fname = "data/history/causes.csv"
    path  = data_dir / "history" / "causes.csv"
    rows  = _read_history_csv(path, _CAUSES_HEADER)

    causes: dict = {}           # cause_id -> {day_unit, sources, targets}
    source_to_cause: dict = {}  # source_id -> cause_id

    for row in rows:
        cid   = row["cause_id"]
        dunit = row["day_unit"]
        ttype = row["target_type"]
        tid   = row["target_id"]

        if ttype == "purchase_order":
            source_id = db["purchase_orders"][tid]["offer_id"]
        elif ttype == "offer":
            source_id = tid
        else:  # lane
            source_id = tid

        if cid not in causes:
            causes[cid] = {"day_unit": dunit, "sources": [], "targets": []}
        causes[cid]["sources"].append(source_id)
        causes[cid]["targets"].append({"ttype": ttype, "tid": tid})
        source_to_cause[source_id] = cid

    return causes, source_to_cause


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
    latest = day0  # will compute latest arrival date then subtract

    for t in targets:
        ttype = t["ttype"]
        tid   = t["tid"]
        if ttype == "purchase_order":
            # revised_receipt_date of the disruption affecting this PO
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

def _log_factorial(n: int) -> float:
    return math.lgamma(n + 1)


def _beta_fraction(a: int, b: int) -> Fraction:
    """B(a, b) = (a-1)! * (b-1)! / (a+b-1)! as a Fraction (a, b >= 1 integers)."""
    # numerator: prod(1..a-1) * prod(1..b-1)
    # denominator: prod(1..a+b-1)
    # Use Fraction arithmetic for exactness
    result = Fraction(1)
    # Multiply by (k / (a+b-1+... )) iteratively is fragile; just compute directly
    # (a-1)! / (a+b-1)! = 1 / [(a) * (a+1) * ... * (a+b-1)]
    # B(a,b) = (b-1)! / [a * (a+1) * ... * (a+b-1)]
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

    Parameters
    ----------
    a, b : int  — Beta posterior parameters (>= 1)
    k    : int  — value of (size - 1), i.e. 0, 1, 2, ...
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
        data/history/{causes,shipments,episodes}.csv.

    Returns
    -------
    dict with keys "causes", "variables", "predictive_size_pmf".
    """
    data_dir = pathlib.Path(data_dir)
    db       = load_all(data_dir)
    cal      = db["calendar"]
    day0     = db["DAY0"]
    hist_dir = data_dir / "history"

    # 1a. Load and validate episodes
    ep_rows = _read_history_csv(hist_dir / "episodes.csv", _EPISODES_HEADER)
    episodes: dict = {}  # episode_id -> dict
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
        episodes[eid] = {
            "episode_id": eid,
            "cause_id":   row["cause_id"],
            "start_date": row["start_date"],
            "end_date":   row["end_date"],
            "delay_days": int(row["delay_days"]),
        }

    # 1b. Load causes meta (for source->cause mapping)
    causes_meta, source_to_cause = _load_causes_meta(data_dir, db)

    # 1c. Load and validate shipments
    ship_rows = _read_history_csv(hist_dir / "shipments.csv", _SHIPMENTS_HEADER)
    for row in ship_rows:
        sid = row["shipment_id"]
        src = row["source_id"]
        eid = row["episode_id"]

        if eid:
            # episode_id must exist
            if eid not in episodes:
                raise ValueError(
                    f"data/history/shipments.csv: shipment {sid!r} "
                    f"references unknown episode_id {eid!r}"
                )
            # cause of episode must match cause of source
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
    # own delay = (receipt - promised in day unit) - episode delay_days
    # day unit determined by source_to_cause -> causes_meta day_unit

    # Per-variable accumulators
    var_stats: dict = {}  # source_id -> stats dict
    for src_id in source_to_cause:
        var_stats[src_id] = {
            "source_id": src_id,
            "records":   0,
            "n_early":   0, "n_ontime": 0, "n_late": 0,
            "early_count": 0, "early_sum": 0,  # count and sum of (size-1)
            "late_count":  0, "late_sum":  0,
        }

    for row in ship_rows:
        sid  = row["shipment_id"]
        src  = row["source_id"]
        prom = date.fromisoformat(row["promised_date"])
        rcpt = date.fromisoformat(row["receipt_date"])
        eid  = row["episode_id"]
        sev  = episodes[eid]["delay_days"] if eid else 0

        # Day unit of this source
        cause_id = source_to_cause[src]
        day_unit = causes_meta[cause_id]["day_unit"]

        if day_unit == "business":
            # Signed business days from promised to receipt
            if rcpt > prom:
                raw = cal.business_days_between(prom, rcpt)
            elif rcpt < prom:
                raw = -cal.business_days_between(rcpt, prom)
            else:
                raw = 0
        else:
            raw = (rcpt - prom).days

        own = raw - sev

        st = var_stats[src]
        st["records"] += 1

        if own < 0:
            st["n_early"] += 1
            st["early_count"] += 1
            st["early_sum"]   += (-own) - 1   # sum of (size - 1)
        elif own == 0:
            st["n_ontime"] += 1
        else:
            st["n_late"]    += 1
            st["late_count"] += 1
            st["late_sum"]   += own - 1        # sum of (size - 1)

    # 3. Per-cause stats
    cause_stats: dict = {}  # cause_id -> stats
    for cid in causes_meta:
        cause_stats[cid] = {
            "n":           0,
            "S":           0,
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
        if not ep["end_date"]:
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

        rate_shape = n + 1    # Gamma(n+1, rate=1/year)
        rate_rate  = 1        # rate parameter (inverse scale = 1 per year)

        if open_on_day0:
            p_active = 1.0
        else:
            # P(active) = 1 - (1 + w/365)^-(n+1)
            p_active = 1.0 - (1.0 + w / _HISTORY_DAYS) ** (-(n + 1))

        severity_a = n + 1
        severity_b = S + 1

        cause_posteriors[cid] = {
            "n":            n,
            "S":            S,
            "open_on_day0": open_on_day0,
            "w_days":       w,
            "rate_shape":   rate_shape,
            "rate_rate":    rate_rate,
            "p_active":     p_active,
            "severity_a":   severity_a,
            "severity_b":   severity_b,
        }

    # --- variable posteriors ---
    var_posteriors: dict = {}
    for src_id, st in var_stats.items():
        records = st["records"]

        n_early  = st["n_early"]
        n_ontime = st["n_ontime"]
        n_late   = st["n_late"]

        # Dirichlet: add 1 to each count (uniform prior adds pseudo-count 1)
        dir_early  = n_early  + 1
        dir_ontime = n_ontime + 1
        dir_late   = n_late   + 1

        # Size Beta posteriors (uniform Beta(1,1) prior: add 1 to both)
        early_a = st["early_count"] + 1
        early_b = st["early_sum"]   + 1
        late_a  = st["late_count"]  + 1
        late_b  = st["late_sum"]    + 1

        # prior_share = 3 / (records + 3)  (3 pseudo-records from Dirichlet)
        prior_share = 3.0 / (records + 3.0)

        var_posteriors[src_id] = {
            "source_id":  src_id,
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
        "causes":              cause_posteriors,
        "variables":           var_posteriors,
        "predictive_size_pmf": predictive_size_pmf,
    }
