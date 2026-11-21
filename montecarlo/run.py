"""Run command for the Monte Carlo engine.

Writes out_dir/worlds.csv and out_dir/run_record.json.
Refuses an out_dir inside data_dir.

Usage:
    python -m montecarlo.run --data data --out runs/demo [--M 1000] [--N 200]
                             [--seed 20261109] [--plain] [--no-grid]
                             [--grid-only] [--target-se 0.02]
                             [--pilot-M 100] [--max-M 2000]
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


def worlds_columns(est: dict, slot_counts: dict) -> list:
    """Return the worlds.csv header exactly as run() builds it.

    Parameters
    ----------
    est         : estimate dict (from montecarlo.estimate.estimate)
    slot_counts : dict cause_id -> int (e.g. from meta["slot_counts"])
    """
    var_cols = []
    for vkey in est["variables"]:
        ttype, tid = vkey.split(".", 1)
        if ttype == "purchase_order":
            var_cols.append(f"purchase_order.{tid}.receipt_date")
        elif ttype == "offer":
            var_cols.append(f"offer.{tid}.delay_business_days")
        else:
            var_cols.append(f"lane.{tid}.delay_days")

    ep_cols = []
    for cid in est["causes"]:
        for j in range(1, slot_counts.get(cid, 0) + 1):
            ep_cols.append(f"cause.{cid}.ep{j}_start_date")
            ep_cols.append(f"cause.{cid}.ep{j}_end_date")
            ep_cols.append(f"cause.{cid}.ep{j}_delay_days")

    return _WORLDS_HEADER_FIXED + var_cols + ep_cols


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

    # Build column order using worlds_columns
    slot_counts = meta["slot_counts"]
    all_cols = worlds_columns(est, slot_counts)

    # Write worlds.csv
    worlds_path = out_dir / "worlds.csv"
    with worlds_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=all_cols)
        w.writeheader()
        for row in worlds:
            w.writerow(row)

    # Count distinct worlds: distinct value combinations across ALL draws
    value_cols = [c for c in all_cols if c not in _WORLDS_HEADER_FIXED]
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
              seed: int = 20261109, method: str = "lhs",
              grid: bool = False, target_se: float = 0.02,
              pilot_M: int = 100, max_M: int = 2000) -> dict:
    """Generate a complete run folder with worlds.csv, result tables, and fingerprint.

    Parameters
    ----------
    data_dir  : str or Path
    out_dir   : str or Path  — the run folder to write to
    M         : parameter draws
    N         : worlds per draw
    seed      : master seed
    method    : "lhs" or "plain"
    grid      : if True, also build grid.json via build_grid
    target_se : target standard error for grid analysis (passed to build_grid)
    pilot_M   : pilot draws for grid analysis (passed to build_grid)
    max_M     : maximum draws for grid analysis (passed to build_grid)

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

    # 3. Delete out_dir/fingerprint.json and out_dir/grid.json if present.
    out_dir.mkdir(parents=True, exist_ok=True)
    fp_path = out_dir / "fingerprint.json"
    grid_path = out_dir / "grid.json"
    if fp_path.exists():
        fp_path.unlink()
    if grid_path.exists():
        grid_path.unlink()

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

    # 7. Build grid if requested (before fingerprint).
    if grid:
        from montecarlo.grid import build_grid
        build_grid(data_dir, out_dir, N=N, seed=seed, method=method,
                   target_se=target_se, pilot_M=pilot_M, max_M=max_M)

    # 8. Write fingerprint.json LAST with output hashes.
    output_names = list(OUTPUT_FILES)
    if grid:
        output_names = output_names + ["grid.json"]
    fingerprint["outputs"] = {
        name: normalised_sha256(out_dir / name)
        for name in output_names
    }
    with fp_path.open("w", encoding="utf-8") as fh:
        json.dump(fingerprint, fh, indent=2, sort_keys=True)

    return record


# ---------------------------------------------------------------------------
# grid_only
# ---------------------------------------------------------------------------

def grid_only(data_dir, out_dir, target_se: float = 0.02,
              pilot_M: int = 100, max_M: int = 2000) -> dict:
    """Build (or rebuild) grid.json for an existing run folder.

    1. Reads fingerprint.json; verifies inputs, code and the three main outputs.
    2. Removes old grid.json and "grid.json" from fingerprint["outputs"].
    3. Calls build_grid with settings from fingerprint.
    4. Adds "grid.json" to fingerprint["outputs"] and rewrites fingerprint.json.
    Main outputs (results.csv, row_map.csv, run_record.json) are not touched.
    On a failed verification nothing on disk changes.

    Returns the grid dict.
    """
    from engine.runs import normalised_sha256, check_run

    data_dir = pathlib.Path(data_dir).resolve()
    out_dir = pathlib.Path(out_dir).resolve()

    fp_path = out_dir / "fingerprint.json"
    if not fp_path.exists():
        raise ValueError(
            f"run folder {out_dir} has no fingerprint.json; the run did not finish"
        )

    with fp_path.open(encoding="utf-8") as fh:
        fingerprint = json.load(fh)

    outputs = fingerprint.get("outputs", {})
    grid_path = out_dir / "grid.json"
    grid_was_in_fp = "grid.json" in outputs
    grid_was_on_disk = grid_path.exists()

    # --- Verification phase: check inputs, code, and the three main outputs.
    # We must NOT let check_run see the grid.json file (it would fire the
    # "not covered" guard) and must NOT let it check the grid.json hash
    # from fingerprint outputs.
    # Strategy: temporarily move grid.json away and strip its fingerprint
    # entry, do the check, then restore everything if it fails.

    # Save original fingerprint bytes for rollback.
    orig_fp_bytes = fp_path.read_bytes()

    # Save grid.json bytes for rollback (if it exists).
    orig_grid_bytes = grid_path.read_bytes() if grid_was_on_disk else None

    # Write a temporary fingerprint without the grid entry.
    fp_no_grid = dict(fingerprint)
    fp_no_grid["outputs"] = {k: v for k, v in outputs.items() if k != "grid.json"}
    with fp_path.open("w", encoding="utf-8") as fh:
        json.dump(fp_no_grid, fh, indent=2, sort_keys=True)

    # Temporarily remove grid.json from disk so check_run won't see it.
    if grid_was_on_disk:
        grid_path.unlink()

    try:
        check_run(out_dir, data_dir)
    except ValueError:
        # Restore fingerprint and grid.json exactly as they were.
        fp_path.write_bytes(orig_fp_bytes)
        if orig_grid_bytes is not None:
            grid_path.write_bytes(orig_grid_bytes)
        raise

    # Verification passed.  grid.json is already gone from disk.
    # Fingerprint is already written without grid.json entry.
    # Build the new grid.
    settings = fingerprint["settings"]
    N = settings["N"]
    seed = settings["seed"]
    method = settings["method"]

    from montecarlo.grid import build_grid
    grid_dict = build_grid(data_dir, out_dir, N=N, seed=seed, method=method,
                           target_se=target_se, pilot_M=pilot_M, max_M=max_M)

    # Add "grid.json" to fingerprint["outputs"] and rewrite.
    fp_no_grid["outputs"]["grid.json"] = normalised_sha256(out_dir / "grid.json")
    with fp_path.open("w", encoding="utf-8") as fh:
        json.dump(fp_no_grid, fh, indent=2, sort_keys=True)

    return grid_dict


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
    p.add_argument("--no-grid", action="store_true", help="skip grid analysis")
    p.add_argument("--grid-only", action="store_true",
                   help="build only grid.json for an existing run folder")
    p.add_argument("--target-se", type=float, default=0.02,
                   help="target SE for grid analysis (default 0.02)")
    p.add_argument("--pilot-M", type=int, default=100,
                   help="pilot draws for grid analysis (default 100)")
    p.add_argument("--max-M", type=int, default=2000,
                   help="max draws for grid analysis (default 2000)")
    args = p.parse_args()

    if args.grid_only and args.no_grid:
        p.error("--grid-only and --no-grid are mutually exclusive")

    method = "plain" if args.plain else "lhs"

    if args.grid_only:
        t0 = time.monotonic()
        grid_dict = grid_only(args.data, args.out,
                              target_se=args.target_se,
                              pilot_M=args.pilot_M,
                              max_M=args.max_M)
        elapsed = time.monotonic() - t0
        _print_grid_summary(grid_dict, elapsed)
        return

    do_grid = not args.no_grid
    record = build_run(args.data, args.out, args.M, args.N, args.seed, method,
                       grid=do_grid,
                       target_se=args.target_se,
                       pilot_M=args.pilot_M,
                       max_M=args.max_M)

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


def _print_grid_summary(grid_dict: dict, total_time: float):
    """Print per-family summary to console (never written to files)."""
    cache_hits = 0
    for fam in grid_dict.get("families", []):
        name = fam["family"]
        M_used = fam["M"]
        req_M = fam["required_M"]
        target_met = fam["target_met"]
        n_points = len(fam["points"])
        n_crossings = len(fam["crossings"])
        print(f"  family={name} M={M_used} required_M={req_M} "
              f"target_met={target_met} points={n_points} crossings={n_crossings}")
    print(f"  grid total_time={total_time:.2f}s")


if __name__ == "__main__":
    main()
