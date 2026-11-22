"""Worlds module: apply world overrides, aggregate multi-world results."""

import decimal
from datetime import timedelta
from fractions import Fraction

from engine.episodes import derived_tags, world_identity
from engine.evaluate import evaluate
from engine.simulate import build_scenario_actions, simulate


# ---------------------------------------------------------------------------
# apply_world
# ---------------------------------------------------------------------------

def apply_world(db: dict, world: dict) -> dict:
    """Return a shallow copy of db with world overrides applied.

    Supported override kinds:
      ("purchase_order", po_id, "receipt_date")          – update disruption date
      ("offer",          offer_id, "delay_business_days") – copy offer with delay
      ("lane",           lane_id,  "delay_days")          – copy lane with delay
    db itself is never mutated.
    """
    db2 = dict(db)
    overrides = world.get("overrides", {})

    # Always propagate world_episodes, even when there are no overrides.
    episodes = world.get("episodes", {})
    if episodes:
        db2["world_episodes"] = episodes
    else:
        db2["world_episodes"] = None

    if not overrides:
        return db2

    # Copy the disruptions dict so we can set revised dates without touching db.
    new_disruptions = dict(db["disruptions"])
    new_offers = None   # copied lazily if needed
    new_lanes = None    # copied lazily if needed

    for (ttype, tid, field), value in overrides.items():
        if ttype == "purchase_order" and field == "receipt_date":
            # Update every disruption whose po_id matches tid.
            for did, dis in db["disruptions"].items():
                if dis["po_id"] == tid:
                    new_dis = dict(dis)
                    new_dis["revised_receipt_date"] = value
                    new_disruptions[did] = new_dis
        elif ttype == "offer" and field == "delay_business_days":
            if new_offers is None:
                new_offers = dict(db["offers"])
            offer_copy = dict(new_offers[tid])
            offer_copy["delay_business_days"] = value
            new_offers[tid] = offer_copy
        elif ttype == "lane" and field == "delay_days":
            if new_lanes is None:
                new_lanes = dict(db["lanes"])
            lane_copy = dict(new_lanes[tid])
            lane_copy["delay_days"] = value
            new_lanes[tid] = lane_copy
        else:
            raise ValueError(
                f"apply_world: override kind ({ttype!r}, {field!r}) is not supported"
            )

    db2["disruptions"] = new_disruptions
    if new_offers is not None:
        db2["offers"] = new_offers
    if new_lanes is not None:
        db2["lanes"] = new_lanes
    return db2


# ---------------------------------------------------------------------------
# worlds_for
# ---------------------------------------------------------------------------

def worlds_for(db: dict, disruption_id: str) -> tuple:
    """Return (worlds_list, source) for a disruption.

    If db["worlds"] is not None, returns (db["worlds"], "file").
    Otherwise synthesises a single-world list from the disruption's
    revised_receipt_date, returning source "announced_date".

    Raises ValueError for an unknown disruption_id.
    """
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"worlds_for: unknown disruption_id {disruption_id!r}")

    if db["worlds"] is not None:
        return db["worlds"], "file"

    dis = db["disruptions"][disruption_id]
    po_id = dis["po_id"]
    revised = dis["revised_receipt_date"]
    synthetic = [
        {
            "world_id": "ANNOUNCED",
            "weight": 1,
            "overrides": {
                ("purchase_order", po_id, "receipt_date"): revised,
            },
        }
    ]
    return synthetic, "announced_date"


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def round_half_away(x: Fraction, digits: int) -> float:
    """Round x to *digits* decimal places, half away from zero.

    Uses decimal.ROUND_HALF_UP on the exact rational value.
    """
    fmt = "1." + "0" * digits if digits > 0 else "1"
    d = decimal.Decimal(x.numerator) / decimal.Decimal(x.denominator)
    return float(d.quantize(decimal.Decimal(fmt), rounding=decimal.ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Quantile
# ---------------------------------------------------------------------------

def quantile(values_and_weights: list, level: Fraction) -> int:
    """Smallest value whose cumulative weight share is >= level.

    values_and_weights: list of (value: int, weight: Fraction)
    level: Fraction, must satisfy 0 < level <= 1.
    """
    if not (Fraction(0) < level <= Fraction(1)):
        raise ValueError(
            f"quantile level must satisfy 0 < level <= 1, got {level}"
        )
    pairs = sorted(values_and_weights, key=lambda t: t[0])
    total_w = sum(w for _, w in pairs)
    cumw = Fraction(0)
    for value, wt in pairs:
        cumw += wt
        if cumw / total_w >= level:
            return value
    # Should not reach here if level <= 1 and total_w > 0.
    return pairs[-1][0]


def quantile_frac(values_and_weights: list, level: Fraction) -> Fraction:
    """Smallest Fraction value whose cumulative weight share is >= level.

    Like quantile() but accepts Fraction values and returns Fraction.
    values_and_weights: list of (value: Fraction, weight: Fraction)
    level: Fraction, must satisfy 0 < level <= 1.
    """
    if not (Fraction(0) < level <= Fraction(1)):
        raise ValueError(
            f"quantile_frac level must satisfy 0 < level <= 1, got {level}"
        )
    pairs = sorted(values_and_weights, key=lambda t: t[0])
    total_w = sum(w for _, w in pairs)
    cumw = Fraction(0)
    for value, wt in pairs:
        cumw += wt
        if cumw / total_w >= level:
            return value
    return pairs[-1][0]


# ---------------------------------------------------------------------------
# evaluate_worlds
# ---------------------------------------------------------------------------

def world_result(db: dict, disruption_id: str, scenario_id: str,
                 world: dict) -> tuple:
    """Run apply_world + simulate + evaluate for one (scenario, world) pair.

    Returns (late_orders, total_extra_cost).
    """
    actions, _ = build_scenario_actions(scenario_id, db)
    db_w = apply_world(db, world)
    sim = simulate(actions, disruption_id, db_w)
    ev = evaluate(sim)
    return ev["late_orders"], ev["total_extra_cost"]


def _tail_mean(lates_and_weights: list, tail_w: Fraction) -> Fraction:
    """Exact weighted mean of the worst tail_w units of weight.

    lates_and_weights: list of (late: int, weight: Fraction).
    tail_w: the target tail weight (> 0).

    Sorts descending by late, then takes whole weights until adding the next
    one would exceed tail_w, takes the needed fractional part of that weight,
    and returns late_sum / tail_w.
    """
    pairs = sorted(lates_and_weights, key=lambda t: t[0], reverse=True)
    late_sum = Fraction(0)
    remaining = tail_w
    for late, wt in pairs:
        if remaining <= 0:
            break
        taken = min(wt, remaining)
        late_sum += Fraction(late) * taken
        remaining -= taken
    return late_sum / tail_w


def aggregate_options(disruption_id: str, db: dict, weighted_results: list,
                      weights_source: str, world_count: int,
                      level: Fraction = Fraction(9, 10)) -> dict:
    """Aggregate simulation results for all disrupted scenarios.

    Parameters
    ----------
    disruption_id : str
        Disruption to evaluate (must exist in db["disruptions"]).
    db : dict
        Loaded database (from loader.load_all()).  Never mutated.
    weighted_results : list of (weight, results, draw, tags)
        weight : int
        results : dict scenario_id -> (late_orders, total_extra_cost)
        draw : int or None
        tags : dict {cause_id: 0 or 1} or None
        One entry per distinct world.
    weights_source : str
        Source of the weights ("file", "announced_date", or "run").
    world_count : int
        Total number of worlds (rows in worlds.csv).
    level : Fraction
        Quantile level for the pXX_late_orders key (default 9/10).

    Returns
    -------
    JSON-serialisable dict (same keys as evaluate_worlds).
    """
    # Validate level and derive key suffix.
    level_pct = level * 100
    if level_pct.denominator != 1:
        raise ValueError(
            f"evaluate_worlds: level*100 must be an integer, got {level}"
        )
    pXX_key = f"p{int(level_pct)}_late_orders"

    total_w = Fraction(sum(wt for wt, _, _draw, _tags in weighted_results))

    dis = db["disruptions"][disruption_id]
    po_id = dis["po_id"]
    announced_receipt_date = dis["revised_receipt_date"].isoformat()
    po = db["purchase_orders"][po_id]

    # Disrupted scenarios in scenarios.csv order.
    disrupted_scenario_ids = [
        sid for sid, s in db["scenarios"].items()
        if s["disruption_id"] == disruption_id
    ]

    # Tail weight = (1 - level) * total_w
    tail_w = (1 - level) * total_w

    # ── per-draw aggregation (for average_range and ranking) ──────────────────
    # draw -> {sid -> (sum_wt_late, sum_wt)} for per-draw expected late
    draw_sids: dict = {}   # draw -> {sid -> [sum_wt_late: Fraction, sum_wt: Fraction]}
    has_none_draw = any(d is None for _, _, d, _t in weighted_results)
    draws_seen: set = set()
    for wt, results, draw, _tags in weighted_results:
        if draw is not None:
            draws_seen.add(draw)
            if draw not in draw_sids:
                draw_sids[draw] = {
                    sid: [Fraction(0), Fraction(0)]
                    for sid in disrupted_scenario_ids
                }
            for sid in disrupted_scenario_ids:
                late, _cost = results[sid]
                draw_sids[draw][sid][0] += Fraction(wt) * Fraction(late)
                draw_sids[draw][sid][1] += Fraction(wt)

    # average_range and ranking require >= 2 distinct draws and no None draws.
    use_draws = (not has_none_draw) and len(draws_seen) >= 2

    # ── per-cause tag accumulation ─────────────────────────────────────────────
    # cause_id -> {0: Fraction weight, 1: Fraction weight}
    db_causes = db.get("causes") or []
    # First-appearance cause order (preserving causes.csv order).
    cause_ids_ordered = []
    _seen_cids: set = set()
    for _cr in db_causes:
        _cid = _cr["cause_id"]
        if _cid not in _seen_cids:
            cause_ids_ordered.append(_cid)
            _seen_cids.add(_cid)

    # Check whether any world has tags=None (makes causes aggregation unavailable).
    any_tags_none = any(t is None for _, _, _d, t in weighted_results)
    use_causes = bool(cause_ids_ordered) and not any_tags_none

    # Accumulate per-cause tag weights and per-(cause, tag, sid) late sums.
    # cause_tag_w[cid][tag] = Fraction total weight of worlds with that tag
    # cause_tag_late[cid][tag][sid] = Fraction sum of weight*late
    cause_tag_w: dict = {}
    cause_tag_late: dict = {}
    if use_causes:
        for cid in cause_ids_ordered:
            cause_tag_w[cid] = {0: Fraction(0), 1: Fraction(0)}
            cause_tag_late[cid] = {
                0: {sid: Fraction(0) for sid in disrupted_scenario_ids},
                1: {sid: Fraction(0) for sid in disrupted_scenario_ids},
            }
        for wt, results, _draw, tags in weighted_results:
            wt_frac = Fraction(wt)
            for cid in cause_ids_ordered:
                tag = tags.get(cid, 0)
                cause_tag_w[cid][tag] += wt_frac
                for sid in disrupted_scenario_ids:
                    late, _ = results[sid]
                    cause_tag_late[cid][tag][sid] += wt_frac * Fraction(late)

    # ── per-option aggregation ─────────────────────────────────────────────────
    option_results = {}   # scenario_id -> aggregated dict

    for sid in disrupted_scenario_ids:
        scenario = db["scenarios"][sid]

        extra_cost_seen = None
        exp_late = Fraction(0)
        worst = 0
        p_no_w = Fraction(0)
        lates_and_weights = []

        for wt, results, _draw, _tags in weighted_results:
            wt_frac = Fraction(wt)
            late, cost = results[sid]

            if extra_cost_seen is None:
                extra_cost_seen = cost
            elif cost != extra_cost_seen:
                raise ValueError(
                    "extra cost depends on the world; "
                    "the cost axis must be extended"
                )

            exp_late += wt_frac * Fraction(late)
            worst = max(worst, late)
            if late == 0:
                p_no_w += wt_frac
            lates_and_weights.append((late, wt_frac))

        exp_exact = exp_late / total_w
        p_no_exact = Fraction(100) * p_no_w / total_w
        p90 = quantile(lates_and_weights, level)

        # Tail mean (worst (1-level) fraction of total weight).
        tail_mean_exact = _tail_mean(lates_and_weights, tail_w)

        # average_range: [q(1/20), q(19/20)] of per-draw expected late, each
        # draw has weight 1 for the quantile.
        if use_draws:
            per_draw_exp = []
            for draw in sorted(draws_seen):
                acc = draw_sids[draw][sid]
                per_draw_exp.append((acc[0] / acc[1], Fraction(1)))
            ar_lo = quantile_frac(per_draw_exp, Fraction(1, 20))
            ar_hi = quantile_frac(per_draw_exp, Fraction(19, 20))
            average_range = [
                round_half_away(ar_lo, 2),
                round_half_away(ar_hi, 2),
            ]
            # Keep exact per-draw expected lates for ranking.
            per_draw_exp_exact = {
                draw: draw_sids[draw][sid][0] / draw_sids[draw][sid][1]
                for draw in sorted(draws_seen)
            }
        else:
            average_range = None
            per_draw_exp_exact = None

        option_results[sid] = {
            "scenario_id": sid,
            "label": scenario["label"],
            "extra_cost": extra_cost_seen,
            "expected_late_orders": round_half_away(exp_exact, 2),
            "worst_late_orders": worst,
            pXX_key: p90,
            "p_no_late_pct": round_half_away(p_no_exact, 1),
            "tail_mean_late_orders": round_half_away(tail_mean_exact, 2),
            "average_range": average_range,
            # Keep exact Fraction values for tradeoff arithmetic.
            "_exp_exact": exp_exact,
            "_p_no_exact": p_no_exact,
            "_tail_mean_exact": tail_mean_exact,
            "_per_draw_exp_exact": per_draw_exp_exact,
        }

    # ── ranking ───────────────────────────────────────────────────────────────
    if use_draws:
        sorted_draws = sorted(draws_seen)
        draw_count = len(sorted_draws)

        # Scenario order: ascending (expected_late_exact, scenarios.csv position).
        sid_to_pos = {sid: i for i, sid in enumerate(disrupted_scenario_ids)}

        def _scenario_sort_key(sid, exp_exact):
            return (exp_exact, sid_to_pos[sid])

        # Global order by global expected.
        global_order = sorted(
            disrupted_scenario_ids,
            key=lambda sid: _scenario_sort_key(
                sid, option_results[sid]["_exp_exact"]
            ),
        )

        # Per-draw order.
        draw_orders = []
        for draw in sorted_draws:
            order = sorted(
                disrupted_scenario_ids,
                key=lambda sid: _scenario_sort_key(
                    sid, option_results[sid]["_per_draw_exp_exact"][draw]
                ),
            )
            draw_orders.append(tuple(order))

        global_order_tuple = tuple(global_order)
        same_draws = sum(1 for o in draw_orders if o == global_order_tuple)

        # Collect other orders.
        other_counts: dict = {}
        for o in draw_orders:
            if o != global_order_tuple:
                other_counts[o] = other_counts.get(o, 0) + 1

        # Sort other orders: draws descending, then order list ascending.
        other_orders = sorted(
            other_counts.items(),
            key=lambda item: (-item[1], list(item[0])),
        )

        ranking = {
            "order": list(global_order_tuple),
            "draws": draw_count,
            "same_draws": same_draws,
            "other_orders": [
                {"order": list(o), "draws": n}
                for o, n in other_orders
            ],
        }
    else:
        ranking = None

    # ── what_if: late_orders per option per receipt date ──────────────────────
    what_if_dates = []
    d = po["planned_receipt_date"]
    while d <= db["HORIZON"]:
        what_if_dates.append(d)
        d += timedelta(days=1)

    what_if_late = {sid: [] for sid in disrupted_scenario_ids}
    for dt in what_if_dates:
        # Build a one-world db override for this date.
        synthetic_world = {
            "overrides": {("purchase_order", po_id, "receipt_date"): dt}
        }
        db_wi = apply_world(db, synthetic_world)
        for sid in disrupted_scenario_ids:
            actions, _ = build_scenario_actions(sid, db)
            sim = simulate(actions, disruption_id, db_wi)
            ev = evaluate(sim)
            what_if_late[sid].append(ev["late_orders"])

    # ── tradeoff_steps ────────────────────────────────────────────────────────
    sorted_sids = sorted(
        disrupted_scenario_ids,
        key=lambda s: (option_results[s]["extra_cost"], s),
    )

    tradeoff_steps = []
    for i in range(len(sorted_sids) - 1):
        frm = sorted_sids[i]
        to = sorted_sids[i + 1]
        rf = option_results[frm]
        rt = option_results[to]

        exp_chg = rt["_exp_exact"] - rf["_exp_exact"]
        worst_chg = rt["worst_late_orders"] - rf["worst_late_orders"]
        p90_chg = rt[pXX_key] - rf[pXX_key]
        p_no_chg = rt["_p_no_exact"] - rf["_p_no_exact"]
        tail_chg = rt["_tail_mean_exact"] - rf["_tail_mean_exact"]

        tradeoff_steps.append({
            "from": frm,
            "to": to,
            "extra_cost_change": rt["extra_cost"] - rf["extra_cost"],
            "expected_late_change": round_half_away(exp_chg, 2),
            "worst_late_change": worst_chg,
            f"p{int(level_pct)}_late_change": p90_chg,
            "p_no_late_pct_change": round_half_away(p_no_chg, 1),
            "tail_mean_late_change": round_half_away(tail_chg, 2),
        })

    # ── causes aggregation ────────────────────────────────────────────────────
    if use_causes:
        # Build targets list per cause in causes.csv order.
        cause_targets: dict = {}
        for _cr in db_causes:
            _cid = _cr["cause_id"]
            if _cid not in cause_targets:
                cause_targets[_cid] = []
            cause_targets[_cid].append([_cr["target_type"], _cr["target_id"]])

        causes_out = []
        for cid in cause_ids_ordered:
            w1 = cause_tag_w[cid][1]
            w0 = cause_tag_w[cid][0]
            active_pct = round_half_away(Fraction(100) * w1 / total_w, 1)

            without_dict = {}
            with_dict = {}
            for sid in disrupted_scenario_ids:
                if w0 > 0:
                    without_dict[sid] = round_half_away(
                        cause_tag_late[cid][0][sid] / w0, 2
                    )
                else:
                    without_dict[sid] = None
                if w1 > 0:
                    with_dict[sid] = round_half_away(
                        cause_tag_late[cid][1][sid] / w1, 2
                    )
                else:
                    with_dict[sid] = None

            causes_out.append({
                "cause_id": cid,
                "targets": cause_targets.get(cid, []),
                "active_pct": active_pct,
                "without": without_dict,
                "with": with_dict,
                "per_year_mean": None,
                "open_episode": None,
                "grid": None,
            })
    else:
        causes_out = []

    # ── assemble final output (remove internal Fraction fields) ───────────────
    options_out = []
    for sid in disrupted_scenario_ids:
        row = {k: v for k, v in option_results[sid].items()
               if not k.startswith("_")}
        options_out.append(row)

    return {
        "disruption_id": disruption_id,
        "po_id": po_id,
        "announced_receipt_date": announced_receipt_date,
        "weights_source": weights_source,
        "world_count": world_count,
        "quantile_level": float(level),
        "options": options_out,
        "what_if": {
            "dates": [d.isoformat() for d in what_if_dates],
            "late_orders": what_if_late,
        },
        "tradeoff_steps": tradeoff_steps,
        "ranking": ranking,
        "causes": causes_out,
        "common_scale": None,
    }


def evaluate_worlds(disruption_id: str, db: dict,
                    level: Fraction = Fraction(9, 10)) -> dict:
    """Aggregate simulation results across worlds for all disrupted scenarios.

    Parameters
    ----------
    disruption_id : str
        Disruption to evaluate (must exist in db["disruptions"]).
    db : dict
        Loaded database (from loader.load_all()).  Never mutated.
    level : Fraction
        Quantile level for the pXX_late_orders key (default 9/10).

    Returns
    -------
    JSON-serialisable dict with:
        disruption_id, po_id, announced_receipt_date, weights_source,
        world_count, quantile_level,
        options (list of per-option dicts),
        what_if (date table independent of worlds),
        tradeoff_steps (consecutive option pairs sorted by cost).
    """
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"evaluate_worlds: unknown disruption_id {disruption_id!r}")

    worlds, weights_source = worlds_for(db, disruption_id)

    # Disrupted scenarios in scenarios.csv order.
    disrupted_scenario_ids = [
        sid for sid, s in db["scenarios"].items()
        if s["disruption_id"] == disruption_id
    ]

    # ── per-option, per-world simulation ──────────────────────────────────────
    # Cache: (scenario_id, world_identity(world)) -> (late_orders, total_extra_cost)
    _sim_cache: dict = {}

    # Build weighted_results: list of (weight, {sid: (late, cost)}, draw, tags)
    weighted_results = []
    for w in worlds:
        wt = w["weight"]
        draw = w.get("draw")  # int or None (synthetic fallback world has no draw)
        # tags: derived_tags for worlds that have episodes, else None
        tags = derived_tags(w, db) if "episodes" in w else None
        results = {}
        for sid in disrupted_scenario_ids:
            cache_key = (sid, world_identity(w))
            if cache_key in _sim_cache:
                late, cost = _sim_cache[cache_key]
            else:
                late, cost = world_result(db, disruption_id, sid, w)
                _sim_cache[cache_key] = (late, cost)
            results[sid] = (late, cost)
        weighted_results.append((wt, results, draw, tags))

    return aggregate_options(disruption_id, db, weighted_results, weights_source,
                             len(worlds), level)
