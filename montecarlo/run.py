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

from engine.episodes import derived_tags
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

    # Build column order from est: variable columns then episode columns
    var_cols = []
    for vkey in est["variables"]:
        ttype, tid = vkey.split(".", 1)
        if ttype == "purchase_order":
            var_cols.append(f"purchase_order.{tid}.receipt_date")
        elif ttype == "offer":
            var_cols.append(f"offer.{tid}.delay_business_days")
        else:
            var_cols.append(f"lane.{tid}.delay_days")

    slot_counts = meta["slot_counts"]
    ep_cols = []
    for cid in est["causes"]:
        for j in range(1, slot_counts.get(cid, 0) + 1):
            ep_cols.append(f"cause.{cid}.ep{j}_start_date")
            ep_cols.append(f"cause.{cid}.ep{j}_end_date")
            ep_cols.append(f"cause.{cid}.ep{j}_delay_days")

    all_cols = _WORLDS_HEADER_FIXED + var_cols + ep_cols

    # Write worlds.csv
    worlds_path = out_dir / "worlds.csv"
    with worlds_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=all_cols)
        w.writeheader()
        for row in worlds:
            w.writerow(row)

    # Count distinct worlds: distinct value combinations across ALL draws
    value_cols = var_cols + ep_cols
    distinct_values: set = set()
    for row in worlds:
        key = tuple(row[c] for c in value_cols)
        distinct_values.add(key)
    distinct = len(distinct_values)

    # Collect active_shares using derived_tags
    # Load worlds.csv back into db to use derived_tags
    dst_data = out_dir / "_tmp_data"
    import shutil
    shutil.copytree(data_dir, dst_data, dirs_exist_ok=True)
    shutil.copy(worlds_path, dst_data / "worlds.csv")
    db2 = load_all(dst_data)
    shutil.rmtree(dst_data, ignore_errors=True)

    cause_ids = list(est["causes"].keys())
    active_totals: dict = {cid: 0 for cid in cause_ids}
    weight_total = 0
    for w_row in db2["worlds"]:
        wt = w_row["weight"]
        weight_total += wt
        tags = derived_tags(w_row, db2)
        for cid in cause_ids:
            if tags.get(cid, 0) == 1:
                active_totals[cid] += wt

    active_shares = {
        cid: active_totals[cid] / weight_total for cid in cause_ids
    }

    # Build per-cause and per-variable summaries for the record
    cause_summary = {}
    for cid, cp in est["causes"].items():
        cause_summary[cid] = {
            "open_on_day0":          cp["open_on_day0"],
            "T_free_days":           cp["T_free_days"],
            "duration_prior_share":  cp["duration_prior_share"],
            "severity_prior_share":  cp["severity_prior_share"],
            "slots":                 slot_counts.get(cid, 0),
            "overflow":              meta["overflow_counts"].get(cid, 0),
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
            n_shipments = sum(1 for _ in fh) - 1
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
        "active_shares":   active_shares,
        "history_shipments": n_shipments,
        "history_episodes":  n_episodes,
        "created_at":      datetime.now(tz=__import__("datetime").timezone.utc).isoformat(),
    }

    record_path = out_dir / "run_record.json"
    with record_path.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    return record


# ---------------------------------------------------------------------------
# build_run
# ---------------------------------------------------------------------------

def build_run(data_dir, out_dir, M: int = 1000, N: int = 200,
              seed: int = 20261109, method: str = "lhs") -> dict:
    """Generate a complete run folder with worlds.csv, result tables, and fingerprint.

    Parameters
    ----------
    data_dir : str or Path
    out_dir  : str or Path  — the run folder to write to
    M        : parameter draws
    N        : worlds per draw
    seed     : master seed
    method   : "lhs" or "plain"

    Returns
    -------
    run_record dict (enriched with result_table info).
    """
    import shutil
    from engine.runs import make_fingerprint, build_result_table, normalised_sha256
    from engine.runs import OUTPUT_FILES, REPO_ROOT

    data_dir = pathlib.Path(data_dir).resolve()
    out_dir = pathlib.Path(out_dir).resolve()

    # Refuse out_dir inside data_dir (same check and message as run()).
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

    # 1. Raise ValueError if data_dir/worlds.csv exists.
    if (data_dir / "worlds.csv").exists():
        raise ValueError(
            "data folder contains worlds.csv; a Monte Carlo run reads base data only"
        )

    # 2. Compute fingerprint BEFORE sampling.
    settings = {"seed": seed, "M": M, "N": N, "method": method}
    fingerprint = make_fingerprint(data_dir, settings)

    # 3. Delete out_dir/fingerprint.json if present.
    out_dir.mkdir(parents=True, exist_ok=True)
    fp_path = out_dir / "fingerprint.json"
    if fp_path.exists():
        fp_path.unlink()

    # 4. Run sampling (writes worlds.csv and run_record.json).
    record = run(data_dir, out_dir, M, N, seed, method)

    # 5. Load a temporary copy of data_dir with the new worlds.csv.
    worlds_path = out_dir / "worlds.csv"
    dst_data = out_dir / "_tmp_data_build"
    shutil.copytree(data_dir, dst_data, dirs_exist_ok=True)
    shutil.copy(worlds_path, dst_data / "worlds.csv")
    try:
        from engine.loader import load_all as _load_all
        db_with_worlds = _load_all(dst_data)
        t_eval_start = time.monotonic()
        rt_info = build_result_table(db_with_worlds, worlds_path, out_dir)
        eval_time = time.monotonic() - t_eval_start
    finally:
        shutil.rmtree(dst_data, ignore_errors=True)

    # 6. Add result_table to the record and rewrite run_record.json.
    if rt_info["distinct_worlds"] != record["distinct_worlds"]:
        raise ValueError(
            f"build_run: result_table distinct_worlds {rt_info['distinct_worlds']} "
            f"differs from run record {record['distinct_worlds']}"
        )

    record["result_table"] = {
        "distinct_worlds": rt_info["distinct_worlds"],
        "scenarios": rt_info["scenarios"],
        "evaluation_time_s": round(eval_time, 3),
    }

    record_path = out_dir / "run_record.json"
    with record_path.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    # 7. Write fingerprint.json LAST with output hashes.
    fingerprint["outputs"] = {
        name: normalised_sha256(out_dir / name)
        for name in OUTPUT_FILES
    }
    with fp_path.open("w", encoding="utf-8") as fh:
        json.dump(fingerprint, fh, indent=2, sort_keys=True)

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
    record = build_run(args.data, args.out, args.M, args.N, args.seed, method)

    print(f"Done in {record['run_time_s']:.1f}s")
    print(f"  rows={record['rows']}, distinct={record['distinct_worlds']}, "
          f"total_samples={record['total_samples']}")
    print(f"  raised={record['raised_count']}, cut={record['cut_count']}")
    for cid, share in record["active_shares"].items():
        print(f"  {cid} share={share:.4f}")
    print(f"  written to {args.out}/")
    rt = record.get("result_table", {})
    print(f"  result_table: distinct_worlds={rt.get('distinct_worlds')}, "
          f"evaluation_time_s={rt.get('evaluation_time_s')}")


if __name__ == "__main__":
    main()
