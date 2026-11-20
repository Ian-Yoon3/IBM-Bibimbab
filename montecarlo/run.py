"""Run command for the Monte Carlo engine.

Writes out_dir/worlds.csv and out_dir/run_record.json.
Refuses an out_dir inside data_dir.

Usage:
    python -m montecarlo.run --data data --out runs/demo [--M 1000] [--N 200]
                             [--seed 20261109] [--plain]
"""

import argparse
import csv
import json
import pathlib
import time
from datetime import date, datetime

from engine.loader import load_all
from montecarlo.estimate import estimate
from montecarlo.sample import sample_worlds

_WORLDS_HEADER_FIXED = ["world_id", "draw", "weight"]


def run(data_dir, out_dir, M: int = 1000, N: int = 200,
        seed: int = 20261109, method: str = "lhs") -> dict:
    """Generate worlds.csv and run_record.json in out_dir.

    Parameters
    ----------
    data_dir : str or Path
    out_dir  : str or Path  — must NOT be inside data_dir
    M        : parameter draws
    N        : worlds per draw
    seed     : master seed
    method   : "lhs" or "plain"

    Returns
    -------
    run_record dict (also written to out_dir/run_record.json).
    """
    data_dir = pathlib.Path(data_dir).resolve()
    out_dir  = pathlib.Path(out_dir).resolve()

    # Refuse out_dir inside data_dir
    try:
        out_dir.relative_to(data_dir)
        raise ValueError(
            f"out_dir {out_dir!r} is inside data_dir {data_dir!r}; "
            "choose a different output directory"
        )
    except ValueError as exc:
        if "inside data_dir" in str(exc):
            raise
        # out_dir is not relative to data_dir — that's fine

    out_dir.mkdir(parents=True, exist_ok=True)

    t0  = time.monotonic()
    db  = load_all(data_dir)
    est = estimate(data_dir)

    worlds, meta = sample_worlds(est, db, M, N, seed, method)

    elapsed = time.monotonic() - t0

    # Build column order from est: variable columns then cause tag columns
    var_cols   = []
    cause_tags = []
    for vkey in est["variables"]:
        ttype, tid = vkey.split(".", 1)
        if ttype == "purchase_order":
            var_cols.append(f"purchase_order.{tid}.receipt_date")
        elif ttype == "offer":
            var_cols.append(f"offer.{tid}.delay_business_days")
        else:
            var_cols.append(f"lane.{tid}.lead_days")
    for cid in est["causes"]:
        cause_tags.append(f"cause.{cid}.active")

    all_cols = _WORLDS_HEADER_FIXED + var_cols + cause_tags

    # Write worlds.csv
    worlds_path = out_dir / "worlds.csv"
    with worlds_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=all_cols)
        w.writeheader()
        for row in worlds:
            w.writerow(row)

    # Count distinct worlds: distinct value combinations across ALL draws
    # (exclude world_id, draw, weight, and cause.*.active tag columns)
    value_cols = var_cols   # only the non-tag variable columns
    distinct_values: set = set()
    for row in worlds:
        key = tuple(row[c] for c in value_cols)
        distinct_values.add(key)
    distinct = len(distinct_values)

    # Collect tag shares
    tag_totals:  dict = {t: 0 for t in cause_tags}
    weight_total = 0
    for row in worlds:
        wt = row["weight"]
        weight_total += wt
        for t in cause_tags:
            if row[t] == "1":
                tag_totals[t] += wt

    tag_shares = {t: tag_totals[t] / weight_total for t in cause_tags}

    # Build per-cause and per-variable summaries for the record
    cause_summary = {}
    for cid, cp in est["causes"].items():
        cause_summary[cid] = {
            "p_active":              cp["p_active"],
            "w_days":                cp["w_days"],
            "open_on_day0":          cp["open_on_day0"],
            "T_free_days":           cp["T_free_days"],
            "duration_prior_share":  cp["duration_prior_share"],
            "severity_prior_share":  cp["severity_prior_share"],
        }

    var_summary = {}
    for vkey, vp in est["variables"].items():
        var_summary[vkey] = {"prior_share": vp["prior_share"]}

    # History counts: episodes and shipments from history files
    hist_dir = data_dir / "history"
    n_shipments = 0
    n_episodes  = 0
    if (hist_dir / "shipments.csv").exists():
        with (hist_dir / "shipments.csv").open(encoding="utf-8") as fh:
            n_shipments = sum(1 for _ in fh) - 1  # subtract header
    if (hist_dir / "episodes.csv").exists():
        with (hist_dir / "episodes.csv").open(encoding="utf-8") as fh:
            n_episodes = sum(1 for _ in fh) - 1

    record = {
        "seed":            seed,
        "M":               M,
        "N":               N,
        "method":          method,
        "total_samples":   M * N,
        "rows":            len(worlds),
        "distinct_worlds": distinct,
        "run_time_s":      round(elapsed, 3),
        "DAY0":            db["DAY0"].isoformat(),
        "causes":          cause_summary,
        "variables":       var_summary,
        "raised_count":    meta["raised_count"],
        "cut_count":       meta["cut_count"],
        "tag_shares":      tag_shares,
        "history_shipments": n_shipments,
        "history_episodes":  n_episodes,
        "created_at":      datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
    }

    record_path = out_dir / "run_record.json"
    with record_path.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Run the Monte Carlo engine and write worlds.csv."
    )
    p.add_argument("--data",  default="data",        help="data directory")
    p.add_argument("--out",   required=True,         help="output directory")
    p.add_argument("--M",     type=int, default=1000, help="parameter draws")
    p.add_argument("--N",     type=int, default=200,  help="worlds per draw")
    p.add_argument("--seed",  type=int, default=20261109, help="random seed")
    p.add_argument("--plain", action="store_true",   help="plain MC instead of LHS")
    args = p.parse_args()

    method = "plain" if args.plain else "lhs"
    record = run(args.data, args.out, args.M, args.N, args.seed, method)

    print(f"Done in {record['run_time_s']:.1f}s")
    print(f"  rows={record['rows']}, distinct={record['distinct_worlds']}, "
          f"total_samples={record['total_samples']}")
    print(f"  raised={record['raised_count']}, cut={record['cut_count']}")
    for cid, share in record["tag_shares"].items():
        print(f"  {cid} share={share:.4f}")
    print(f"  written to {args.out}/")


if __name__ == "__main__":
    main()
