"""Rate-grid (threshold analysis) for the Monte Carlo engine.

build_grid(data_dir, run_dir, N, seed, method, ...) -> grid dict
Writes run_dir/grid.json.
"""

import csv
import json
import math
import pathlib
import shutil
import statistics
import tempfile

from engine.episodes import world_identity
from engine.loader import load_all
from engine.worlds import world_result
from montecarlo.estimate import estimate
from montecarlo.run import worlds_columns
from montecarlo.sample import (
    _compute_slot_count,
    sample_worlds,
    slot_count_fixed_rate,
    slot_count_posterior,
)

P_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.99]


# ---------------------------------------------------------------------------
# find_crossings (pure, testable)
# ---------------------------------------------------------------------------

def find_crossings(diff_at, p_grid, resolution=0.01):
    """Find sign-change brackets of diff_at(p) on p_grid.

    Parameters
    ----------
    diff_at    : callable p -> float
    p_grid     : sorted list of float p values
    resolution : stop bisecting when hi - lo <= this

    Returns
    -------
    list of (p_lo, p_hi, d_lo, d_hi) brackets.
    d_lo and d_hi are the diff values at the bracket endpoints.
    For exact-zero brackets p_lo == p_hi and d_lo == d_hi == 0.0.
    """
    crossings = []
    diffs = [(p, diff_at(p)) for p in p_grid]

    for i in range(len(diffs) - 1):
        p_lo, d_lo = diffs[i]
        p_hi, d_hi = diffs[i + 1]

        # Exact zero at a grid point
        if d_lo == 0.0:
            crossings.append((p_lo, p_lo, 0.0, 0.0))
            continue

        # Sign change (strictly opposite signs)
        if d_lo * d_hi < 0:
            lo, hi = p_lo, p_hi
            d_lo_cur = d_lo
            d_hi_cur = d_hi
            while hi - lo > resolution:
                mid = (lo + hi) / 2
                d_mid = diff_at(mid)
                if d_mid == 0.0:
                    lo = mid
                    hi = mid
                    d_lo_cur = 0.0
                    d_hi_cur = 0.0
                    break
                if d_lo_cur * d_mid < 0:
                    hi = mid
                    d_hi_cur = d_mid
                else:
                    lo = mid
                    d_lo_cur = d_mid
            crossings.append((lo, hi, d_lo_cur, d_hi_cur))

    # Check last grid point
    if diffs and diffs[-1][1] == 0.0:
        p_last = diffs[-1][0]
        # Only add if not already covered
        already = any(
            abs(c[0] - p_last) < 1e-12 and abs(c[1] - p_last) < 1e-12
            for c in crossings
        )
        if not already:
            crossings.append((p_last, p_last, 0.0, 0.0))

    return crossings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lam_for_p(p, D0_k):
    """lambda_k(p) = -ln(1-p) / D0_k (0 at p=0 or D0_k=0)."""
    if p == 0.0 or D0_k <= 0:
        return 0.0
    return -math.log(1.0 - p) / D0_k


def _write_tmp_worlds(est, worlds_w, meta, tmp_data_dir):
    """Write worlds.csv into tmp_data_dir."""
    slot_counts = meta["slot_counts"]
    all_cols = worlds_columns(est, slot_counts)
    worlds_csv = tmp_data_dir / "worlds.csv"
    with worlds_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=all_cols)
        w.writeheader()
        for row in worlds_w:
            w.writerow(row)


def _eval_worlds(est, db_base, tmp_data_dir, scenario_sids, pair_keys,
                 cache, use_cache, worlds_w, meta):
    """Compute per-draw stats for a list of worlds.

    Parameters
    ----------
    scenario_sids : list of (disruption_id, scenario_id) in scenarios.csv order
    pair_keys     : list of "A|B" pair keys where A and B are from the SAME disruption
    """
    # Load a db with the worlds
    db_point = load_all(tmp_data_dir)
    actual_worlds = db_point["worlds"]

    draws: dict = {}
    for w in actual_worlds:
        d = w["draw"]
        draws.setdefault(d, []).append(w)

    sids = [sid for _, sid in scenario_sids]
    per_draw: dict = {sid: [] for sid in sids}
    total_weight_all = 0
    cause_ep_weight: dict = {}

    for j in sorted(draws.keys()):
        draw_worlds = draws[j]
        draw_weight = sum(w["weight"] for w in draw_worlds)
        if draw_weight == 0:
            for sid in sids:
                per_draw[sid].append(0.0)
            continue

        draw_late: dict = {sid: 0 for sid in sids}
        for w in draw_worlds:
            wt = w["weight"]
            total_weight_all += wt
            identity = world_identity(w)
            for did, sid in scenario_sids:
                if use_cache:
                    key = (did, sid, identity)
                    if key in cache:
                        late, cost = cache[key]
                    else:
                        late, cost = world_result(db_point, did, sid, w)
                        cache[key] = (late, cost)
                else:
                    late, cost = world_result(db_point, did, sid, w)
                draw_late[sid] += wt * late

            # worlds_with_episode
            for cid, ep_list in w.get("episodes", {}).items():
                if ep_list:
                    cause_ep_weight[cid] = cause_ep_weight.get(cid, 0) + wt

        for sid in sids:
            per_draw[sid].append(draw_late[sid] / draw_weight)

    # Statistics
    expected_late = {}
    se_dict = {}
    for sid in sids:
        vals = per_draw[sid]
        if not vals:
            expected_late[sid] = 0.0
            se_dict[sid] = 0.0
        elif len(vals) == 1:
            expected_late[sid] = vals[0]
            se_dict[sid] = 0.0
        else:
            expected_late[sid] = sum(vals) / len(vals)
            se_dict[sid] = statistics.stdev(vals) / math.sqrt(len(vals))

    # Pair diffs — only for same-disruption pairs
    diff_dict = {}
    se_diff_dict = {}
    for pk in pair_keys:
        A, B = pk.split("|")
        diffs_per_draw = [
            per_draw[A][k] - per_draw[B][k]
            for k in range(len(per_draw[A]))
        ]
        if not diffs_per_draw:
            diff_dict[pk] = 0.0
            se_diff_dict[pk] = 0.0
        elif len(diffs_per_draw) == 1:
            diff_dict[pk] = diffs_per_draw[0]
            se_diff_dict[pk] = 0.0
        else:
            diff_dict[pk] = sum(diffs_per_draw) / len(diffs_per_draw)
            se_diff_dict[pk] = (
                statistics.stdev(diffs_per_draw) / math.sqrt(len(diffs_per_draw))
            )

    overflow = dict(meta.get("overflow_counts", {}))
    total_w = total_weight_all if total_weight_all > 0 else 1
    cause_ids = list(est["causes"].keys())
    worlds_with_ep = {
        cid: cause_ep_weight.get(cid, 0) / total_w for cid in cause_ids
    }

    return expected_late, se_dict, diff_dict, se_diff_dict, overflow, worlds_with_ep


def _eval_point_at_M(est, db_base, tmp_data_dir, scenario_sids, pair_keys,
                     cache, use_cache, M, N, seed, method,
                     rate_fixed=None, rate_scale=None, slot_counts=None):
    """Sample M draws, write tmp worlds.csv, load db, evaluate."""
    worlds_w, meta = sample_worlds(
        est, db_base, M, N, seed, method,
        rate_fixed=rate_fixed,
        rate_scale=rate_scale,
        slot_counts=slot_counts,
    )
    _write_tmp_worlds(est, worlds_w, meta, tmp_data_dir)
    return _eval_worlds(est, db_base, tmp_data_dir, scenario_sids, pair_keys,
                        cache, use_cache, worlds_w, meta)


def _round_floats(obj):
    """Recursively round all floats to 6 decimal places."""
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def _make_pair_keys(scenario_sids):
    """Build pair keys for scenarios of the same disruption (A before B in order).

    scenario_sids : list of (disruption_id, scenario_id) in scenarios.csv order
    Returns list of "A|B" strings.
    """
    # Group sids by disruption, preserving order
    by_dis: dict = {}
    for did, sid in scenario_sids:
        by_dis.setdefault(did, []).append(sid)

    pair_keys = []
    for did, sids in by_dis.items():
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                pair_keys.append(f"{sids[i]}|{sids[j]}")
    return pair_keys


# ---------------------------------------------------------------------------
# Main build_grid
# ---------------------------------------------------------------------------

def build_grid(data_dir, run_dir, N: int, seed: int, method: str,
               target_se: float = 0.02, pilot_M: int = 100, max_M: int = 2000,
               families=None, use_cache: bool = True) -> dict:
    """Build the rate grid and write run_dir/grid.json.

    Parameters
    ----------
    data_dir  : base data directory (must NOT contain worlds.csv)
    run_dir   : run folder (must contain results.csv, row_map.csv, run_record.json)
    N         : worlds per draw
    seed      : master seed
    method    : "lhs" or "plain"
    target_se : target SE for required_M calculation
    pilot_M   : pilot draws per point
    max_M     : maximum draws per point
    families  : list of family names (None = all)
    use_cache : if False, skip the world-result cache

    Returns
    -------
    grid dict (also written to run_dir/grid.json)
    """
    data_dir = pathlib.Path(data_dir).resolve()
    run_dir = pathlib.Path(run_dir).resolve()

    if (data_dir / "worlds.csv").exists():
        raise ValueError(
            "data_dir contains worlds.csv; build_grid requires base data only"
        )

    est = estimate(data_dir)
    db_base = load_all(data_dir)
    day0 = db_base["DAY0"]
    cause_horizons = db_base.get("cause_horizons") or {}

    # Disrupted scenarios in scenarios.csv order
    scenario_sids = []
    for sid, s in db_base["scenarios"].items():
        dis_id = s.get("disruption_id", "")
        if dis_id and dis_id in db_base["disruptions"]:
            scenario_sids.append((dis_id, sid))

    if not scenario_sids:
        raise ValueError("build_grid: no disrupted scenarios found")

    cause_ids = list(est["causes"].keys())

    # Build family definitions
    all_family_names = cause_ids + ["scale"]
    if families is not None:
        all_family_names = [f for f in all_family_names if f in families]

    # Precompute cause info
    cause_info = {}
    for cid in cause_ids:
        cp = est["causes"][cid]
        H_k_obj = cause_horizons.get(cid, {}).get("H")
        H0_k_obj = cause_horizons.get(cid, {}).get("H0")
        D_k = (H_k_obj - day0).days + 1 if H_k_obj else 0
        D0_k = (H0_k_obj - day0).days + 1 if H0_k_obj else 0
        has_open = cp.get("open_episode") is not None
        T_free = cp["T_free_days"]
        rate_shape = cp["rate_shape"]
        cause_info[cid] = {
            "D_k": D_k,
            "D0_k": D0_k,
            "has_open": has_open,
            "T_free_days": T_free,
            "rate_shape": rate_shape,
        }

    # Reference cause for scale family:
    # largest 1 - (1 + D0_k / T_free_k) ** (-rate_shape_k) (first on tie)
    def _scale_ref_score(cid):
        ci = cause_info[cid]
        D0 = ci["D0_k"]
        T = ci["T_free_days"]
        r = ci["rate_shape"]
        if T <= 0:
            return 1.0
        return 1.0 - (1.0 + D0 / T) ** (-r)

    ref_cause = cause_ids[0]
    best_score = _scale_ref_score(cause_ids[0])
    for cid in cause_ids[1:]:
        sc = _scale_ref_score(cid)
        if sc > best_score:
            best_score = sc
            ref_cause = cid

    # Shared world-result cache
    cache: dict = {}

    # Single temporary copy of data_dir for all evaluations
    _tmp_data_dir = pathlib.Path(tempfile.mkdtemp())
    try:
        shutil.copytree(data_dir, _tmp_data_dir, dirs_exist_ok=True)
        return _build_grid_impl(
            est, db_base, run_dir, _tmp_data_dir,
            cause_ids, cause_info, ref_cause, scenario_sids,
            N, seed, method, target_se, pilot_M, max_M,
            all_family_names, cache, use_cache
        )
    finally:
        shutil.rmtree(_tmp_data_dir, ignore_errors=True)


def _build_grid_impl(est, db_base, run_dir, tmp_data_dir,
                     cause_ids, cause_info, ref_cause, scenario_sids,
                     N, seed, method, target_se, pilot_M, max_M,
                     family_names, cache, use_cache):
    """Core grid building logic."""
    sids = [sid for _, sid in scenario_sids]

    # Pairs only within the same disruption
    pair_keys = _make_pair_keys(scenario_sids)

    families_out = []

    for fam_name in family_names:
        if fam_name == "scale":
            fam_data = _build_scale_family(
                est, db_base, tmp_data_dir, cause_ids, cause_info, ref_cause,
                scenario_sids, pair_keys, N, seed, method,
                target_se, pilot_M, max_M, cache, use_cache, run_dir
            )
        else:
            cid = fam_name
            fam_data = _build_cause_family(
                est, db_base, tmp_data_dir, cid, cause_ids, cause_info,
                scenario_sids, pair_keys, N, seed, method,
                target_se, pilot_M, max_M, cache, use_cache
            )
        families_out.append(fam_data)

    # m1_check
    m1_check = _build_m1_check(run_dir, families_out, sids)

    grid = {
        "version": 1,
        "settings": {
            "N": N,
            "seed": seed,
            "method": method,
            "target_se": target_se,
            "pilot_M": pilot_M,
            "max_M": max_M,
            "p_grid": P_GRID,
        },
        "families": families_out,
        "m1_check": m1_check,
    }

    grid = _round_floats(grid)

    grid_path = run_dir / "grid.json"
    with grid_path.open("w", encoding="utf-8") as fh:
        json.dump(grid, fh, indent=2, sort_keys=True)
        fh.write("\n")

    return grid


def _default_slot_counts(cause_ids, cause_info):
    """Return the default slot counts for all causes."""
    sc = {}
    for cid in cause_ids:
        ci = cause_info[cid]
        sc[cid] = _compute_slot_count(
            ci["rate_shape"], ci["T_free_days"], ci["D_k"], ci["has_open"]
        )
    return sc


def _build_cause_family(est, db_base, tmp_data_dir, cid, cause_ids, cause_info,
                        scenario_sids, pair_keys, N, seed, method,
                        target_se, pilot_M, max_M, cache, use_cache):
    """Build one cause family."""
    ci = cause_info[cid]
    D_k = ci["D_k"]
    D0_k = ci["D0_k"]
    has_open = ci["has_open"]

    # Slot count for this cause: max over P_GRID
    max_sk = max(
        slot_count_fixed_rate(_lam_for_p(p, D0_k), D_k, has_open)
        for p in P_GRID
    )

    # Fixed slot counts: default for all causes, override for this cause
    fam_slot_counts = _default_slot_counts(cause_ids, cause_info)
    fam_slot_counts[cid] = max_sk

    def eval_p(p, M):
        lam = _lam_for_p(p, D0_k)
        return _eval_point_at_M(
            est, db_base, tmp_data_dir, scenario_sids, pair_keys, cache, use_cache,
            M, N, seed, method,
            rate_fixed={cid: lam},
            slot_counts=fam_slot_counts,
        )

    # Pilot run
    pilot_results = [eval_p(p, pilot_M) for p in P_GRID]

    # required_M
    required_M = pilot_M
    for exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep in pilot_results:
        for pk, se_dv in se_diff_d.items():
            if se_dv > 0 and target_se > 0:
                r = math.ceil((se_dv * math.sqrt(pilot_M) / target_se) ** 2)
                if r > required_M:
                    required_M = r

    M_family = min(max(required_M, pilot_M), max_M)
    target_met = required_M <= max_M

    # Full run at M_family — collect results keyed by p for crossing lookup
    full_points = []
    recorded: dict = {}  # p -> (exp_late, se_d, diff_d, se_diff_d, ...)
    for p in P_GRID:
        lam = _lam_for_p(p, D0_k)
        exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep = eval_p(p, M_family)
        pt = {
            "kind": "grid",
            "p": p,
            "lambda_per_day": lam,
            "lambda_per_year": lam * 365,
            "M": M_family,
            "overflow": dict(overflow),
            "worlds_with_episode": dict(worlds_ep),
            "expected_late": {sid: exp_late[sid] for _, sid in scenario_sids},
            "se": {sid: se_d[sid] for _, sid in scenario_sids},
            "diff": dict(diff_d),
            "se_diff": dict(se_diff_d),
        }
        full_points.append(pt)
        recorded[p] = (diff_d, se_diff_d)

    # Crossings via find_crossings for each pair
    bisect_points, all_crossings = _compute_crossings(
        full_points, recorded, pair_keys, P_GRID, M_family,
        eval_at_p=lambda p: eval_p(p, M_family),
        make_pt=lambda p, res: {
            "kind": "bisect",
            "p": p,
            "lambda_per_day": _lam_for_p(p, D0_k),
            "lambda_per_year": _lam_for_p(p, D0_k) * 365,
            "M": M_family,
            "overflow": dict(res[4]),
            "worlds_with_episode": dict(res[5]),
            "expected_late": {sid: res[0][sid] for _, sid in scenario_sids},
            "se": {sid: res[1][sid] for _, sid in scenario_sids},
            "diff": dict(res[2]),
            "se_diff": dict(res[3]),
        },
    )

    all_points = full_points + bisect_points
    _kind_order = {"grid": 0, "bisect": 1, "m1": 2}
    all_points.sort(key=lambda pt: (pt["p"], _kind_order.get(pt.get("kind", "grid"), 99)))

    return {
        "family": cid,
        "open_episode": has_open,
        "D0_days": D0_k,
        "slot_counts": fam_slot_counts,
        "M": M_family,
        "required_M": required_M,
        "target_met": target_met,
        "points": all_points,
        "crossings": all_crossings,
    }


def _build_scale_family(est, db_base, tmp_data_dir, cause_ids, cause_info, ref_cause,
                        scenario_sids, pair_keys, N, seed, method,
                        target_se, pilot_M, max_M, cache, use_cache, run_dir):
    """Build the scale family."""
    ci_ref = cause_info[ref_cause]
    T_free_r = ci_ref["T_free_days"]
    rate_shape_r = ci_ref["rate_shape"]
    D0_r = ci_ref["D0_k"]

    if T_free_r > 0:
        lam_bar = rate_shape_r / T_free_r
    else:
        lam_bar = float("inf")

    def m_at_p(p):
        if p == 0.0:
            return 0.0
        denom = lam_bar * D0_r if (math.isfinite(lam_bar) and D0_r > 0) else 0.0
        if denom == 0:
            return 0.0
        return -math.log(1.0 - p) / denom

    # m1 p value
    if math.isfinite(lam_bar) and lam_bar > 0 and D0_r > 0:
        p_m1 = 1.0 - math.exp(-lam_bar * D0_r)
    else:
        p_m1 = 0.0

    # All m values including m=1
    all_m_values = [m_at_p(p) for p in P_GRID] + [1.0]

    # Slot counts: max over all m values of slot_count_posterior for each cause
    fam_slot_counts = {}
    for c2 in cause_ids:
        ci2 = cause_info[c2]
        max_s = max(
            slot_count_posterior(
                ci2["rate_shape"], ci2["T_free_days"], ci2["D_k"],
                ci2["has_open"], scale=m
            )
            for m in all_m_values
        )
        fam_slot_counts[c2] = max_s

    def eval_scale(m, M):
        return _eval_point_at_M(
            est, db_base, tmp_data_dir, scenario_sids, pair_keys, cache, use_cache,
            M, N, seed, method,
            rate_scale=m,
            slot_counts=fam_slot_counts,
        )

    # Pilot run for P_GRID points
    pilot_results = [eval_scale(m_at_p(p), pilot_M) for p in P_GRID]

    # required_M (P_GRID points only, not m1)
    required_M = pilot_M
    for exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep in pilot_results:
        for pk, se_dv in se_diff_d.items():
            if se_dv > 0 and target_se > 0:
                r = math.ceil((se_dv * math.sqrt(pilot_M) / target_se) ** 2)
                if r > required_M:
                    required_M = r

    M_family = min(max(required_M, pilot_M), max_M)
    target_met = required_M <= max_M

    # Full run at M_family for P_GRID points
    full_points = []
    recorded: dict = {}  # p -> (diff_d, se_diff_d)
    for p in P_GRID:
        m = m_at_p(p)
        exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep = eval_scale(m, M_family)
        pt = {
            "kind": "grid",
            "p": p,
            "m": m,
            "M": M_family,
            "overflow": dict(overflow),
            "worlds_with_episode": dict(worlds_ep),
            "expected_late": {sid: exp_late[sid] for _, sid in scenario_sids},
            "se": {sid: se_d[sid] for _, sid in scenario_sids},
            "diff": dict(diff_d),
            "se_diff": dict(se_diff_d),
        }
        full_points.append(pt)
        recorded[p] = (diff_d, se_diff_d)

    # m1 point at M_family
    exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep = eval_scale(1.0, M_family)
    m1_point = {
        "kind": "m1",
        "p": p_m1,
        "m": 1.0,
        "M": M_family,
        "overflow": dict(overflow),
        "worlds_with_episode": dict(worlds_ep),
        "expected_late": {sid: exp_late[sid] for _, sid in scenario_sids},
        "se": {sid: se_d[sid] for _, sid in scenario_sids},
        "diff": dict(diff_d),
        "se_diff": dict(se_diff_d),
    }

    # Crossings on P_GRID points via find_crossings
    bisect_points, all_crossings = _compute_crossings(
        full_points, recorded, pair_keys, P_GRID, M_family,
        eval_at_p=lambda p: eval_scale(m_at_p(p), M_family),
        make_pt=lambda p, res: {
            "kind": "bisect",
            "p": p,
            "m": m_at_p(p),
            "M": M_family,
            "overflow": dict(res[4]),
            "worlds_with_episode": dict(res[5]),
            "expected_late": {sid: res[0][sid] for _, sid in scenario_sids},
            "se": {sid: res[1][sid] for _, sid in scenario_sids},
            "diff": dict(res[2]),
            "se_diff": dict(res[3]),
        },
    )

    all_points = full_points + [m1_point] + bisect_points
    _kind_order = {"grid": 0, "bisect": 1, "m1": 2}
    all_points.sort(key=lambda pt: (pt["p"], _kind_order.get(pt.get("kind", "grid"), 99)))

    return {
        "family": "scale",
        "reference_cause": ref_cause,
        "D0_days": ci_ref["D0_k"],
        "slot_counts": fam_slot_counts,
        "M": M_family,
        "required_M": required_M,
        "target_met": target_met,
        "points": all_points,
        "crossings": all_crossings,
    }


def _compute_crossings(full_points, recorded, pair_keys, p_grid, M_family,
                       eval_at_p, make_pt):
    """Compute sign-change crossings for each pair using find_crossings.

    Parameters
    ----------
    full_points : list of already-evaluated grid points
    recorded    : dict p -> (diff_d, se_diff_d) for grid p values
    pair_keys   : list of "A|B" pair strings
    p_grid      : the grid p values (used to look up recorded diffs)
    M_family    : M at which bisection points are evaluated
    eval_at_p   : callable(p) -> (exp_late, se_d, diff_d, se_diff_d, overflow, worlds_ep)
                  evaluates a NEW bisection point at p
    make_pt     : callable(p, result_tuple) -> dict for a bisect point record

    Returns
    -------
    (bisect_points, all_crossings)
    """
    # Cache of already-evaluated bisection points so we reuse within a family
    bisect_cache: dict = {}  # p -> result_tuple

    # Map from grid p to its point record (for se_diff lookup at bracket ends)
    grid_by_p = {pt["p"]: pt for pt in full_points if pt.get("kind") == "grid"}

    bisect_points = []
    all_crossings = []

    for pk in pair_keys:
        A, B = pk.split("|")

        # Build diff_at using recorded diffs for grid points and evaluate+record for bisect
        def diff_at(p, _pk=pk):
            if p in recorded:
                return recorded[p][0].get(_pk, 0.0)
            if p in bisect_cache:
                return bisect_cache[p][2].get(_pk, 0.0)
            res = eval_at_p(p)
            bisect_cache[p] = res
            # Also record as a bisect point
            pt = make_pt(p, res)
            bisect_points.append(pt)
            return res[2].get(_pk, 0.0)

        brackets = find_crossings(diff_at, p_grid, resolution=0.01)

        for p_lo, p_hi, d_lo, d_hi in brackets:
            # se_diff at bracket ends: look up from recorded or bisect_cache
            def _get_se(p, _pk=pk):
                if p in recorded:
                    return recorded[p][1].get(_pk, 0.0)
                if p in bisect_cache:
                    return bisect_cache[p][3].get(_pk, 0.0)
                return 0.0

            se_lo = _get_se(p_lo)
            se_hi = _get_se(p_hi)

            all_crossings.append({
                "pair": pk.split("|"),
                "p_lo": p_lo,
                "p_hi": p_hi,
                "diff_lo": d_lo,
                "diff_hi": d_hi,
                "se_diff_lo": se_lo,
                "se_diff_hi": se_hi,
            })

    # De-duplicate bisect_points (same p may be evaluated multiple times across pairs)
    seen_p = set()
    deduped = []
    for pt in bisect_points:
        if pt["p"] not in seen_p:
            seen_p.add(pt["p"])
            deduped.append(pt)

    return deduped, all_crossings


def _build_m1_check(run_dir, families_out, sids):
    """Compare scale family m=1 point vs main results.csv.

    Keeps an entry for every disrupted scenario.
    When se == 0 at m=1, stores "z": null instead of dropping the entry.
    """
    m1_check = {}

    scale_fam = None
    for fam in families_out:
        if fam["family"] == "scale":
            scale_fam = fam
            break

    if scale_fam is None:
        return m1_check

    m1_point = None
    for pt in scale_fam["points"]:
        if pt.get("kind") == "m1":
            m1_point = pt
            break

    if m1_point is None:
        return m1_check

    results_path = run_dir / "results.csv"
    row_map_path = run_dir / "row_map.csv"
    if not results_path.exists() or not row_map_path.exists():
        raise ValueError(
            f"build_grid: run_dir {run_dir} must contain results.csv and row_map.csv "
            "(required for m1_check)"
        )

    with results_path.open(encoding="utf-8", newline="") as fh:
        results_rows = list(csv.DictReader(fh))
    with row_map_path.open(encoding="utf-8", newline="") as fh:
        row_map_rows = list(csv.DictReader(fh))

    results_by_index = {row["world_index"]: row for row in results_rows}
    weight_by_index: dict = {}
    for rm in row_map_rows:
        idx = rm["world_index"]
        weight_by_index[idx] = weight_by_index.get(idx, 0) + int(rm["weight"])

    total_w = sum(weight_by_index.values())
    if total_w == 0:
        return m1_check

    # Check which sid columns exist
    first_row = results_rows[0] if results_rows else {}

    for sid in sids:
        col = f"late_orders.{sid}"
        if col not in first_row:
            continue
        exp_main = sum(
            weight_by_index[idx] * int(results_by_index[idx][col])
            for idx in weight_by_index
            if idx in results_by_index and col in results_by_index[idx]
        ) / total_w

        exp_grid = m1_point["expected_late"].get(sid, 0.0)
        se_m1 = m1_point["se"].get(sid, 0.0)
        if se_m1 > 0:
            z = (exp_grid - exp_main) / se_m1
            z_val = z if math.isfinite(z) else None
        else:
            z_val = None

        # Always keep the entry; z is None when se == 0
        m1_check[sid] = {
            "grid": exp_grid,
            "main": exp_main,
            "z": z_val,
        }

    return m1_check
