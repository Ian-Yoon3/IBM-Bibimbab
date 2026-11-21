"""Two-level LHS sampler for the stage 2 Monte Carlo engine (new episode format).

sample_worlds(est, db, M, N, seed, method) -> (worlds, meta)

Outer level (M parameter draws from posteriors):
  per cause: lambda_k ~ Gamma(rate_shape, 1/T_free_days) per day;
             phi_k ~ Beta(duration_a, duration_b);
             theta_k ~ Beta(severity_a, severity_b).
  per variable: category probs = Dirichlet; size theta_e, theta_l = Beta.

Inner level (N worlds per draw via LHS or plain MC):
  Dimensions: one per variable (own delay), then for each cause in causes.csv
  order, for each slot j = 1..S_k, three dimensions: gap, duration, severity.

Inverse CDFs (monotone):
  own delay E(u; pe, po, pl, theta_e, theta_l):
    u < pe:       E = -(1 + floor(log(u/pe) / log(1-theta_e)))
    u < pe+po:    E = 0
    else v=(u-pe-po)/pl, E = 1 + floor(log(1-v) / log(1-theta_l))
    theta=1 gives size=1 (special case).
  severity C(u; theta) = 1 + floor(log(1-u) / log(1-theta)); theta=1 -> 1.

Episode timeline (alternating renewal process):
  Slot 1 (open episode): start = open_episode.start_date; fill from data or samples.
  Remaining slots: exponential gap then geometric duration and severity.

World columns:
  purchase_order: receipt_date = add_business_days(revised, E + shock)
  offer:          delay_business_days = own deviation E only
  lane:           delay_days = own deviation E only (new format, no lower clamp)
  cause:          ep<n>_start_date, ep<n>_end_date, ep<n>_delay_days (or "none")
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
    """
    cols = []
    for _ in range(d):
        perm = list(range(n))
        rng.shuffle(perm)
        col = [(perm[i] + rng.random()) / n for i in range(n)]
        cols.append(col)
    return [[cols[j][i] for j in range(d)] for i in range(n)]


# ---------------------------------------------------------------------------
# Inverse CDFs
# ---------------------------------------------------------------------------

def _inv_own_delay(u: float, pe: float, po: float, pl: float,
                   theta_e: float, theta_l: float) -> int:
    """Monotone inverse CDF for own delay E."""
    if u < pe:
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
        v = (u - pe - po) / pl
        if v >= 1.0:
            v = 1.0 - 1e-15
        if theta_l >= 1.0:
            return 1
        log_q = math.log(1.0 - theta_l)
        w = 1.0 - v
        if w <= 0.0:
            w = 1e-300
        size = 1 + int(math.floor(math.log(w) / log_q))
        return size


def _inv_severity(u: float, theta: float) -> int:
    """Monotone inverse CDF for C = 1 + Geometric({0,1,...}, theta)."""
    if theta >= 1.0:
        return 1
    w = 1.0 - u
    if w <= 0.0:
        w = 1e-300
    log_q = math.log(1.0 - theta)
    return 1 + int(math.floor(math.log(w) / log_q))


# ---------------------------------------------------------------------------
# Slot count computation
# ---------------------------------------------------------------------------

def _nb_cdf_term(j: int, r: int, p: float, q: float) -> float:
    """Compute C(j+r-1, j) * p^r * q^j."""
    # log binomial coefficient: log C(j+r-1, j)
    log_bc = 0.0
    for k in range(j):
        log_bc += math.log(r + k) - math.log(k + 1)
    log_term = log_bc + r * math.log(p) + j * math.log(q) if q > 0 else (
        log_bc + r * math.log(p) if j == 0 else -math.inf
    )
    return math.exp(log_term)


def _compute_slot_count(rate_shape: int, T_free_days: float,
                        D_k: int, has_open: bool) -> int:
    """Smallest s with 1 - NB_CDF(s; r, T/(T+D)) < 1e-6, plus 1 if open_episode."""
    r = rate_shape
    T = T_free_days
    D = D_k
    if D <= 0:
        s = 0
    elif T <= 0:
        # Almost certain to have events; set a generous count
        s = 20
    else:
        p = T / (T + D)
        q = D / (T + D)
        # Sum from j=0 until 1 - cdf < 1e-6 (i.e., cdf >= 1 - 1e-6)
        cdf = 0.0
        s = 0
        while True:
            cdf += _nb_cdf_term(s, r, p, q)
            if 1.0 - cdf < 1e-6:
                break
            s += 1
            if s > 10000:
                break
    if has_open:
        s += 1
    return max(s, 1) if has_open else max(s, 0)


# ---------------------------------------------------------------------------
# Cap / room computations
# ---------------------------------------------------------------------------

def _compute_room_offer(db: dict, offer_id: str, cap: date) -> int:
    """Business-day room from latest promised date of offer to cap."""
    cal = db["calendar"]
    day0 = db["DAY0"]
    offer = db["offers"][offer_id]
    lead = offer["lead_days"]
    # Base: promise on DAY0
    L = cal.next_business_day(day0 + timedelta(days=lead))
    # Recovery purchases for this offer
    for (sid, oid), rp in db["recovery_purchases"].items():
        if oid == offer_id:
            promised = cal.next_business_day(
                rp["action_date"] + timedelta(days=lead)
            )
            if promised > L:
                L = promised
    return cal.business_days_between(L, cap)


def _compute_room_lane(db: dict, lane_id: str, cap: date) -> int:
    """Calendar-day room from latest base arrival of lane to cap."""
    day0 = db["DAY0"]
    lane = db["lanes"][lane_id]
    lead = lane["lead_days"]
    L = day0 + timedelta(days=lead)
    for (sid, lid, cid), rt in db["recovery_transfers"].items():
        if lid == lane_id:
            arrival = rt["action_date"] + timedelta(days=lead)
            if arrival > L:
                L = arrival
    return (cap - L).days


def _compute_room_po(db: dict, po_id: str, cap: date) -> int:
    """Business-day room from revised receipt date of PO to cap."""
    cal = db["calendar"]
    for dis in db["disruptions"].values():
        if dis["po_id"] == po_id:
            return cal.business_days_between(dis["revised_receipt_date"], cap)
    # No disruption: use planned date
    return cal.business_days_between(
        db["purchase_orders"][po_id]["planned_receipt_date"], cap
    )


# ---------------------------------------------------------------------------
# Parameter draw (outer level)
# ---------------------------------------------------------------------------

def _draw_parameters(est: dict, rng: random.Random) -> dict:
    """Sample one parameter set from the posteriors."""
    params = {"causes": {}, "variables": {}}

    for cid, cp in est["causes"].items():
        lam = rng.gammavariate(cp["rate_shape"], 1.0 / cp["T_free_days"])
        phi = rng.betavariate(cp["duration_a"], cp["duration_b"])
        theta_sev = rng.betavariate(cp["severity_a"], cp["severity_b"])
        params["causes"][cid] = {
            "lambda": lam,
            "phi": phi,
            "theta_sev": theta_sev,
        }

    for vkey, vp in est["variables"].items():
        g_e = rng.gammavariate(vp["dir_early"],  1.0)
        g_o = rng.gammavariate(vp["dir_ontime"], 1.0)
        g_l = rng.gammavariate(vp["dir_late"],   1.0)
        total = g_e + g_o + g_l
        pe = g_e / total
        po = g_o / total
        pl = g_l / total
        theta_e = rng.betavariate(vp["early_a"], vp["early_b"])
        theta_l = rng.betavariate(vp["late_a"],  vp["late_b"])
        params["variables"][vkey] = {
            "pe": pe, "po": po, "pl": pl,
            "theta_e": theta_e, "theta_l": theta_l,
        }

    return params


# ---------------------------------------------------------------------------
# Episode generation for one cause in one world
# ---------------------------------------------------------------------------

def _generate_episodes(cause_id: str, est_cp: dict, draw_cp: dict,
                       slot_uniforms: list, H_k: date, day0: date) -> list:
    """Generate episode list for one cause in one world.

    slot_uniforms: list of S_k triples (u_gap, u_dur, u_sev).
    Returns list of dicts {start, end, delay} for filled slots (empty = "none").
    """
    lam   = draw_cp["lambda"]
    phi   = draw_cp["phi"]
    theta = draw_cp["theta_sev"]

    open_ep = est_cp.get("open_episode")
    S_k = len(slot_uniforms)
    episodes = []

    slot_idx = 0
    t = day0  # current time pointer

    if open_ep is not None:
        # Slot 1: open episode
        u_gap, u_dur, u_sev = slot_uniforms[slot_idx]
        slot_idx += 1

        start = open_ep["start_date"]
        # end
        if open_ep["end_date"] is not None:
            end = open_ep["end_date"]
        else:
            dur = _inv_severity(u_dur, phi)
            dur_capped = min(dur - 1, 10**6)
            end = day0 + timedelta(days=dur_capped)
        # delay
        if open_ep["delay_days"] is not None:
            delay = open_ep["delay_days"]
        else:
            delay = _inv_severity(u_sev, theta)
            # capping happens later
        episodes.append({"start": start, "end": end, "delay": delay})
        t = end + timedelta(days=1)

    # Remaining slots (or all slots if no open episode)
    for si in range(slot_idx, S_k):
        u_gap, u_dur, u_sev = slot_uniforms[si]
        if lam <= 0.0:
            gap = 10**9
        else:
            w = 1.0 - u_gap
            if w <= 0.0:
                w = 1e-300
            gap = int(math.floor(-math.log(w) / lam))
        start_days = gap
        if start_days > 10**6:
            break
        start = t + timedelta(days=start_days)
        if start > H_k:
            # This slot and all later are "none"
            break
        dur = _inv_severity(u_dur, phi)
        dur_capped = min(dur - 1, 10**6)
        end = start + timedelta(days=dur_capped)
        delay = _inv_severity(u_sev, theta)
        episodes.append({"start": start, "end": end, "delay": delay})
        t = end + timedelta(days=1)

    return episodes


# ---------------------------------------------------------------------------
# Main sample_worlds function
# ---------------------------------------------------------------------------

def sample_worlds(est: dict, db: dict, M: int, N: int, seed: int,
                  method: str = "lhs") -> tuple:
    """Sample M*N worlds using two-level parameter sampling.

    Returns (worlds, meta) where worlds is a list of dicts and meta contains
    raised_count, cut_count, slot_counts, overflow_counts.
    """
    rng  = random.Random(seed)
    cal  = db["calendar"]
    day0 = db["DAY0"]
    cap  = day0 + timedelta(days=365)

    var_keys   = list(est["variables"].keys())
    cause_ids  = list(est["causes"].keys())
    n_vars     = len(var_keys)

    # ── Slot counts per cause ─────────────────────────────────────────────────
    cause_horizons = db.get("cause_horizons") or {}
    slot_counts: dict = {}
    for cid in cause_ids:
        cp = est["causes"][cid]
        H_k = cause_horizons.get(cid, {}).get("H")
        if H_k is None:
            D_k = 0
        else:
            D_k = (H_k - day0).days + 1
        has_open = cp.get("open_episode") is not None
        S_k = _compute_slot_count(
            cp["rate_shape"], cp["T_free_days"], D_k, has_open
        )
        slot_counts[cid] = S_k

    # Total LHS dimensions
    d = n_vars + sum(3 * slot_counts[cid] for cid in cause_ids)

    # ── Room and cause caps ───────────────────────────────────────────────────
    # room per (ttype, tid): business days or calendar days to cap
    room_by_target: dict = {}  # (ttype, tid) -> room_t
    for cid in cause_ids:
        for cr in (db.get("causes") or []):
            if cr["cause_id"] != cid:
                continue
            ttype = cr["target_type"]
            tid   = cr["target_id"]
            if ttype == "offer":
                room_by_target[(ttype, tid)] = _compute_room_offer(db, tid, cap)
            elif ttype == "lane":
                room_by_target[(ttype, tid)] = _compute_room_lane(db, tid, cap)
            elif ttype == "purchase_order":
                room_by_target[(ttype, tid)] = _compute_room_po(db, tid, cap)

    # C_k = min room over all targets of cause k
    cause_caps: dict = {}
    for cid in cause_ids:
        rooms = []
        for cr in (db.get("causes") or []):
            if cr["cause_id"] != cid:
                continue
            ttype = cr["target_type"]
            tid   = cr["target_id"]
            key   = (ttype, tid)
            if key in room_by_target:
                rooms.append(room_by_target[key])
        cause_caps[cid] = min(rooms) if rooms else 0

    # ── Cause-to-variables mapping ────────────────────────────────────────────
    # For each cause: which offer/lane/po targets exist
    cause_targets_map: dict = {}  # cid -> list of (ttype, tid)
    for cid in cause_ids:
        cause_targets_map[cid] = []
        for cr in (db.get("causes") or []):
            if cr["cause_id"] == cid:
                cause_targets_map[cid].append(
                    (cr["target_type"], cr["target_id"])
                )

    # variable key -> cause_id
    vkey_cause: dict = {}
    for vkey in var_keys:
        vkey_cause[vkey] = est["variables"][vkey]["cause_id"]

    # ── Purchase order info ───────────────────────────────────────────────────
    revised_dates: dict = {}
    planned_dates: dict = {}
    po_max_shift:  dict = {}
    po_min_shift:  dict = {}
    for vkey in var_keys:
        if not vkey.startswith("purchase_order."):
            continue
        po_id = vkey.split(".")[1]
        po    = db["purchase_orders"][po_id]
        planned_dates[po_id] = po["planned_receipt_date"]
        for dis in db["disruptions"].values():
            if dis["po_id"] == po_id:
                revised_dates[po_id] = dis["revised_receipt_date"]
                break
        po_max_shift[po_id] = cal.business_days_between(
            revised_dates[po_id], cap
        )
        po_min_shift[po_id] = -(
            (revised_dates[po_id] - planned_dates[po_id]).days + 1
        )

    # ── Build ordered column names ────────────────────────────────────────────
    var_col_names = []  # list of (vkey, col_name)
    for vkey in var_keys:
        ttype, tid = vkey.split(".", 1)
        if ttype == "purchase_order":
            col = f"purchase_order.{tid}.receipt_date"
        elif ttype == "offer":
            col = f"offer.{tid}.delay_business_days"
        else:
            col = f"lane.{tid}.delay_days"
        var_col_names.append((vkey, col))

    # Episode column names per cause (slot 1..S_k)
    ep_col_names: dict = {}  # cid -> list of (start_col, end_col, delay_col)
    for cid in cause_ids:
        ep_col_names[cid] = []
        for j in range(1, slot_counts[cid] + 1):
            ep_col_names[cid].append((
                f"cause.{cid}.ep{j}_start_date",
                f"cause.{cid}.ep{j}_end_date",
                f"cause.{cid}.ep{j}_delay_days",
            ))

    # ── Tracking ──────────────────────────────────────────────────────────────
    raised_count  = 0
    cut_count     = 0
    overflow_counts: dict = {cid: 0 for cid in cause_ids}
    world_counter = 0
    all_worlds    = []

    for m in range(M):
        draw_params = _draw_parameters(est, rng)

        if method == "lhs":
            uniforms = lhs_uniforms(N, d, rng)
        else:
            uniforms = [[rng.random() for _ in range(d)] for _ in range(N)]

        draw_groups: dict = {}

        for i in range(N):
            row_u = uniforms[i]
            vals: dict = {}

            # ── Dimension index layout ────────────────────────────────────────
            # [0 .. n_vars-1]: one per variable
            # [n_vars ..]: per cause in order, 3*S_k per cause
            cause_dim_start: dict = {}
            idx = n_vars
            for cid in cause_ids:
                cause_dim_start[cid] = idx
                idx += 3 * slot_counts[cid]

            # ── Generate episode timelines for each cause ─────────────────────
            cause_episodes: dict = {}  # cid -> list of {start, end, delay} (filled)
            cause_max_delay: dict = {}  # cid -> max delay among filled slots (or 0)
            overflow_this_world: dict = {}  # cid -> 0 or 1

            for ci, cid in enumerate(cause_ids):
                S_k = slot_counts[cid]
                H_k = cause_horizons.get(cid, {}).get("H")
                est_cp = est["causes"][cid]
                draw_cp = draw_params["causes"][cid]
                C_k = cause_caps[cid]

                # Collect slot uniforms
                base = cause_dim_start[cid]
                slot_uniforms = []
                for j in range(S_k):
                    slot_uniforms.append((
                        row_u[base + 3*j],
                        row_u[base + 3*j + 1],
                        row_u[base + 3*j + 2],
                    ))

                if H_k is None or S_k == 0:
                    episodes = []
                    overflow_this_world[cid] = 0
                else:
                    episodes = _generate_episodes(
                        cid, est_cp, draw_cp, slot_uniforms, H_k, day0
                    )

                    # Cap episode delays to C_k
                    for ep in episodes:
                        if ep["delay"] > C_k:
                            ep["delay"] = C_k
                            cut_count += 1

                    # Overflow check: only when all S_k slots are filled
                    ov = 0
                    if len(episodes) == S_k:
                        t_overflow = episodes[-1]["end"] + timedelta(days=1)
                        if t_overflow <= H_k:
                            lam = draw_cp["lambda"]
                            u_extra = rng.random()
                            if lam > 0:
                                w = 1.0 - u_extra
                                if w <= 0.0:
                                    w = 1e-300
                                gap_extra = int(math.floor(-math.log(w) / lam))
                            else:
                                gap_extra = 10**9
                            if t_overflow + timedelta(days=gap_extra) <= H_k:
                                ov = 1
                    overflow_this_world[cid] = ov

                cause_episodes[cid] = episodes
                max_d = max((ep["delay"] for ep in episodes), default=0)
                cause_max_delay[cid] = max_d

            # ── Accumulate overflow counts ─────────────────────────────────────
            for cid in cause_ids:
                overflow_counts[cid] += overflow_this_world[cid]

            # ── Write episode columns ─────────────────────────────────────────
            for cid in cause_ids:
                episodes = cause_episodes[cid]
                for slot_j, (sc, ec, dc) in enumerate(ep_col_names[cid]):
                    if slot_j < len(episodes):
                        ep = episodes[slot_j]
                        vals[sc] = ep["start"].isoformat()
                        vals[ec] = ep["end"].isoformat()
                        vals[dc] = str(ep["delay"])
                    else:
                        vals[sc] = "none"
                        vals[ec] = "none"
                        vals[dc] = "none"

            # ── Variable columns ──────────────────────────────────────────────
            for vi, (vkey, col) in enumerate(var_col_names):
                u_own = row_u[vi]
                vp    = draw_params["variables"][vkey]
                E = _inv_own_delay(u_own, vp["pe"], vp["po"], vp["pl"],
                                   vp["theta_e"], vp["theta_l"])

                ttype = vkey.split(".")[0]
                tid   = vkey.split(".", 1)[1]
                cid   = vkey_cause[vkey]

                if ttype == "purchase_order":
                    # shock = delay of first episode with overlap
                    po_id    = tid
                    revised  = revised_dates[po_id]
                    planned  = planned_dates[po_id]
                    offer_id = db["purchase_orders"][po_id]["offer_id"]
                    lead_days = db["offers"][offer_id]["lead_days"]
                    min_end  = max(day0, revised - timedelta(days=lead_days))
                    shock = 0
                    for ep in cause_episodes[cid]:
                        if ep["start"] <= revised and ep["end"] >= min_end:
                            shock = ep["delay"]
                            break
                    x = E + shock
                    if x > po_max_shift[po_id]:
                        receipt = cap + timedelta(days=1)
                    elif x <= po_min_shift[po_id]:
                        receipt = planned - timedelta(days=1)
                    else:
                        receipt = cal.add_business_days(revised, x)
                    if receipt < planned:
                        receipt = cal.next_business_day(planned)
                        raised_count += 1
                    if receipt > cap:
                        receipt = _snap_to_cap_biz(cal, cap)
                        cut_count += 1
                    vals[col] = receipt.isoformat()

                elif ttype == "offer":
                    offer_id = est["variables"][vkey]["source_id"]
                    room_t   = room_by_target.get(("offer", offer_id), 0)
                    max_delay = cause_max_delay[cid]
                    effective_room = room_t - max_delay
                    if E > effective_room:
                        E = effective_room
                        cut_count += 1
                    vals[col] = str(E)

                else:  # lane
                    lid    = est["variables"][vkey]["source_id"]
                    room_t = room_by_target.get(("lane", lid), 0)
                    max_delay = cause_max_delay[cid]
                    effective_room = room_t - max_delay
                    if E > effective_room:
                        E = effective_room
                        cut_count += 1
                    vals[col] = str(E)

            # Group by all column values
            key = tuple(
                vals[c] for _, c in var_col_names
            ) + tuple(
                vals[cn]
                for cid in cause_ids
                for cols_triple in ep_col_names[cid]
                for cn in cols_triple
            )
            draw_groups[key] = draw_groups.get(key, 0) + 1

        # Emit worlds for this draw
        for key, count in draw_groups.items():
            world_counter += 1
            wid = f"W{world_counter:06d}"
            all_cols = (
                [c for _, c in var_col_names] +
                [cn for cid in cause_ids
                 for cols_triple in ep_col_names[cid]
                 for cn in cols_triple]
            )
            row = {"world_id": wid, "draw": m, "weight": count}
            for col, val in zip(all_cols, key):
                row[col] = val
            all_worlds.append(row)

    meta = {
        "raised_count":    raised_count,
        "cut_count":       cut_count,
        "slot_counts":     slot_counts,
        "overflow_counts": overflow_counts,
    }
    return all_worlds, meta


def _snap_to_cap_biz(cal, cap: date) -> date:
    """Return the latest business day on or before cap."""
    d = cap
    while cal.is_closed(d):
        d -= timedelta(days=1)
    return d
