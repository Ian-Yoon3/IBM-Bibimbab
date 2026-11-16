"""Two-level LHS sampler for the stage 2 Monte Carlo engine.

sample_worlds(est, db, M, N, seed, method) -> list of world dicts

Outer level (M parameter draws from posteriors):
  per cause: lambda = Gamma(n+1, 365/T); p = 1 if open else 1-exp(-lambda*w/365);
             severity theta = Beta(a, b).
  per variable: category probs = Dirichlet; size theta_e, theta_l = Beta.

Inner level (N worlds per draw via LHS or plain MC):
  Dimensions: one per variable (own delay) + 2 per cause (active, severity),
  ordered as [var_0, var_1, ..., cause_0_active, cause_0_sev, cause_1_active, cause_1_sev, ...]
  in causes.csv order.

Inverse CDFs (monotone):
  own delay E(u; pe, po, pl, theta_e, theta_l):
    u < pe:       E = -(1 + floor(log(u/pe) / log(1-theta_e)))
    u < pe+po:    E = 0
    else v=(u-pe-po)/pl, E = 1 + floor(log(1-v) / log(1-theta_l))
    theta=1 gives size=1 (special case).
  severity C(u; theta) = 1 + floor(log(1-u) / log(1-theta)); theta=1 -> 1.
  active S(u; p) = 1 if u < p else 0.

World values (section 4.3 / 4.7):
  purchase_order: receipt = add_business_days(revised_date, E + S*C)
  offer:          column offer.<id>.delay_business_days = E + S*C
  lane:           column lane.<id>.lead_days = max(1, base_lead + E + S*C)
  Tags:           cause.<K>.active = S

Sampling cap: DAY0 + 365 days. Values beyond the cap are cut to the cap.
"""

import math
import random
from datetime import date, timedelta

from engine.loader import load_all
from montecarlo.estimate import estimate

# ---------------------------------------------------------------------------
# LHS uniforms
# ---------------------------------------------------------------------------

def lhs_uniforms(n: int, d: int, rng: random.Random) -> list:
    """Return an n x d list-of-lists of LHS uniform draws.

    Every column j has exactly one value in each stratum [k/n, (k+1)/n).
    The rows are paired at random across columns.

    Parameters
    ----------
    n   : number of samples
    d   : number of dimensions
    rng : random.Random instance

    Returns
    -------
    list of n rows, each a list of d floats in [0, 1).
    """
    # Build each column independently then zip into rows
    cols = []
    for _ in range(d):
        perm = list(range(n))
        rng.shuffle(perm)
        col = [(perm[i] + rng.random()) / n for i in range(n)]
        cols.append(col)
    # Transpose: rows[i] = [cols[j][i] for j in range(d)]
    return [[cols[j][i] for j in range(d)] for i in range(n)]


# ---------------------------------------------------------------------------
# Inverse CDFs
# ---------------------------------------------------------------------------

def _inv_own_delay(u: float, pe: float, po: float, pl: float,
                   theta_e: float, theta_l: float) -> int:
    """Monotone inverse CDF for own delay E.

    Returns a signed integer (negative=early, 0=on-time, positive=late).
    """
    if u < pe:
        # Early: size = 1 + floor(log(u/pe) / log(1-theta_e))
        if theta_e >= 1.0:
            return -1
        log_q = math.log(1.0 - theta_e)
        v = u / pe
        if v <= 0.0:
            v = 1e-300
        size = 1 + int(math.floor(math.log(v) / log_q))
        return -size
    elif u < pe + po:
        return 0
    else:
        # Late: v = (u - pe - po) / pl
        v = (u - pe - po) / pl
        if v >= 1.0:
            v = 1.0 - 1e-15
        if theta_l >= 1.0:
            return 1
        log_q = math.log(1.0 - theta_l)
        # size = 1 + floor(log(1-v) / log(1-theta_l))
        w = 1.0 - v
        if w <= 0.0:
            w = 1e-300
        size = 1 + int(math.floor(math.log(w) / log_q))
        return size


def _inv_severity(u: float, theta: float) -> int:
    """Monotone inverse CDF for severity C = 1 + Geometric({0,1,...}, theta).

    C = 1 + floor(log(1-u) / log(1-theta)).
    """
    if theta >= 1.0:
        return 1
    w = 1.0 - u
    if w <= 0.0:
        w = 1e-300
    log_q = math.log(1.0 - theta)
    return 1 + int(math.floor(math.log(w) / log_q))


# ---------------------------------------------------------------------------
# Parameter draw from posteriors (outer level)
# ---------------------------------------------------------------------------

def _offer_delay_cap(db: dict, offer_id: str, cap: date) -> int:
    """Maximum business-day delay for an offer so its receipt at DAY0 <= cap.

    promised = cal.next_business_day(DAY0 + lead_days)
    return cal.business_days_between(promised, cap)
    """
    cal  = db["calendar"]
    day0 = db["DAY0"]
    lead = db["offers"][offer_id]["lead_days"]
    promised = cal.next_business_day(day0 + timedelta(days=lead))
    return cal.business_days_between(promised, cap)


def _draw_parameters(est: dict, rng: random.Random) -> dict:
    """Sample one parameter set from the posteriors.

    Returns a dict with cause params and variable params.
    """
    params = {"causes": {}, "variables": {}}

    for cid, cp in est["causes"].items():
        # Rate: Gamma(shape=n+1, scale=365/T) so lambda is per year
        T_days = cp["T_days"]
        lam = rng.gammavariate(cp["rate_shape"], 365.0 / T_days)
        if cp["open_on_day0"]:
            p = 1.0
        else:
            w = cp["w_days"]
            p = 1.0 - math.exp(-lam * w / 365.0)
        # Severity theta: Beta(severity_a, severity_b)
        theta_sev = rng.betavariate(cp["severity_a"], cp["severity_b"])
        params["causes"][cid] = {
            "lambda": lam, "p": p, "theta_sev": theta_sev,
        }

    for vkey, vp in est["variables"].items():
        # Category: Dirichlet via normalised gammavariates
        g_e = rng.gammavariate(vp["dir_early"],  1.0)
        g_o = rng.gammavariate(vp["dir_ontime"], 1.0)
        g_l = rng.gammavariate(vp["dir_late"],   1.0)
        total = g_e + g_o + g_l
        pe = g_e / total
        po = g_o / total
        pl = g_l / total
        # Size thetas
        theta_e = rng.betavariate(vp["early_a"], vp["early_b"])
        theta_l = rng.betavariate(vp["late_a"],  vp["late_b"])
        params["variables"][vkey] = {
            "pe": pe, "po": po, "pl": pl,
            "theta_e": theta_e, "theta_l": theta_l,
        }

    return params


# ---------------------------------------------------------------------------
# Main sample_worlds function
# ---------------------------------------------------------------------------

def sample_worlds(est: dict, db: dict, M: int, N: int, seed: int,
                  method: str = "lhs") -> tuple:
    """Sample M*N worlds using two-level parameter sampling.

    Parameters
    ----------
    est    : output of estimate(data_dir)
    db     : output of load_all(data_dir)
    M      : number of parameter draws
    N      : number of worlds per draw
    seed   : master random seed
    method : "lhs" (default) or "plain"

    Returns
    -------
    (worlds, meta) where:
      worlds : list of dicts with keys world_id, draw, weight, <columns>
      meta   : dict with raised_count, cut_count
    """
    rng  = random.Random(seed)
    cal  = db["calendar"]
    day0 = db["DAY0"]
    cap  = day0 + timedelta(days=365)

    # Build ordered lists from est (preserving causes.csv order)
    var_keys   = list(est["variables"].keys())   # ordered variable keys
    cause_ids  = list(est["causes"].keys())       # ordered cause ids

    # Number of uniform dimensions: 1 per variable + 2 per cause
    n_vars   = len(var_keys)
    n_causes = len(cause_ids)
    d = n_vars + 2 * n_causes

    # Base lead days per lane (for lead_days column)
    base_leads = {}
    for vkey, vp in est["variables"].items():
        if vkey.startswith("lane."):
            lid = vp["source_id"]
            base_leads[lid] = db["lanes"][lid]["lead_days"]

    # Revised receipt dates for purchase_order targets
    revised_dates = {}
    planned_dates = {}
    for vkey, vp in est["variables"].items():
        if vkey.startswith("purchase_order."):
            po_id = vkey.split(".")[1]  # e.g. "PO01"
            po    = db["purchase_orders"][po_id]
            planned_dates[po_id] = po["planned_receipt_date"]
            for dis in db["disruptions"].values():
                if dis["po_id"] == po_id:
                    revised_dates[po_id] = dis["revised_receipt_date"]
                    break

    raised_count = 0
    cut_count    = 0
    world_counter = 0
    all_worlds   = []

    # Column names for the output
    var_col_names   = []  # list of (vkey, col_name) for variable columns
    cause_col_names = []  # list of (cid, col_active, col_sev) for cause tags
    for vkey, vp in est["variables"].items():
        ttype, tid = vkey.split(".", 1)
        if ttype == "purchase_order":
            col = f"purchase_order.{tid}.receipt_date"
        elif ttype == "offer":
            col = f"offer.{tid}.delay_business_days"
        else:  # lane
            col = f"lane.{tid}.lead_days"
        var_col_names.append((vkey, col))
    for cid in cause_ids:
        cause_col_names.append((cid, f"cause.{cid}.active"))

    for m in range(M):
        draw_params = _draw_parameters(est, rng)

        if method == "lhs":
            uniforms = lhs_uniforms(N, d, rng)
        else:
            uniforms = [[rng.random() for _ in range(d)] for _ in range(N)]

        # Group worlds within this draw: value_tuple -> count
        draw_groups: dict = {}

        for i in range(N):
            row_u = uniforms[i]
            vals: dict = {}

            # Cause dimensions: active and severity (positioned after var dims)
            cause_vals = {}  # cid -> (S, C)
            for ci, cid in enumerate(cause_ids):
                u_active = row_u[n_vars + 2 * ci]
                u_sev    = row_u[n_vars + 2 * ci + 1]
                cp       = draw_params["causes"][cid]
                S = 1 if u_active < cp["p"] else 0
                C = _inv_severity(u_sev, cp["theta_sev"])
                cause_vals[cid] = (S, C)

            # Variable dimensions
            for vi, (vkey, col) in enumerate(var_col_names):
                u_own = row_u[vi]
                vp    = draw_params["variables"][vkey]
                E = _inv_own_delay(u_own, vp["pe"], vp["po"], vp["pl"],
                                   vp["theta_e"], vp["theta_l"])

                est_vp = est["variables"][vkey]
                cid    = est_vp["cause_id"]
                S, C   = cause_vals[cid]
                shift  = S * C

                ttype  = vkey.split(".")[0]
                tid    = vkey.split(".", 1)[1]

                if ttype == "purchase_order":
                    revised = revised_dates[tid]
                    planned = planned_dates[tid]
                    receipt = cal.add_business_days(revised, E + shift)
                    if receipt < planned:
                        receipt = cal.next_business_day(planned)
                        raised_count += 1
                    if receipt > cap:
                        receipt = _snap_to_cap_biz(cal, cap)
                        cut_count += 1
                    vals[col] = receipt.isoformat()

                elif ttype == "offer":
                    delay     = E + shift
                    offer_id  = est["variables"][vkey]["source_id"]
                    delay_cap = _offer_delay_cap(db, offer_id, cap)
                    if delay > delay_cap:
                        delay = delay_cap
                        cut_count += 1
                    vals[col] = str(delay)

                else:  # lane (calendar days)
                    lid      = est_vp["source_id"]
                    base     = base_leads[lid]
                    new_lead = max(1, base + E + shift)
                    if day0 + timedelta(days=new_lead) > cap:
                        new_lead = (cap - day0).days
                        cut_count += 1
                    vals[col] = str(new_lead)

            # Cause tag columns
            for cid, col_active in cause_col_names:
                S, _ = cause_vals[cid]
                vals[col_active] = str(S)

            # Group by all column values
            key = tuple(vals[c] for _, c in var_col_names) + \
                  tuple(vals[col_active] for _, col_active in cause_col_names)
            draw_groups[key] = draw_groups.get(key, 0) + 1

        # Emit worlds for this draw
        for key, count in draw_groups.items():
            world_counter += 1
            wid   = f"W{world_counter:06d}"
            # Reconstruct vals dict from key
            all_cols = [c for _, c in var_col_names] + \
                       [col_active for _, col_active in cause_col_names]
            row = {"world_id": wid, "draw": m, "weight": count}
            for col, val in zip(all_cols, key):
                row[col] = val
            all_worlds.append(row)

    meta = {"raised_count": raised_count, "cut_count": cut_count}
    return all_worlds, meta


def _snap_to_cap_biz(cal, cap: date) -> date:
    """Return the latest business day on or before cap."""
    d = cap
    while cal.is_closed(d):
        d -= timedelta(days=1)
    return d
