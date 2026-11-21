"""Run folder management: fingerprinting, result tables, and run selection."""

import csv
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

from engine.worlds import aggregate_options, world_result

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

SELECTION_PATH = REPO_ROOT / "run_selection.json"  # None means "no run selected"

INPUT_FILES = {
    "required": [
        "bom.csv",
        "components.csv",
        "disruptions.csv",
        "inventory.csv",
        "orders.csv",
        "products.csv",
        "purchase_orders.csv",
        "recovery_purchases.csv",
        "recovery_transfers.csv",
        "scenarios.csv",
        "supplier_offers.csv",
        "suppliers.csv",
        "transfer_lanes.csv",
        "warehouses.csv",
        "history/shipments.csv",
        "history/episodes.csv",
        "history/period.csv",
    ],
    "optional": [
        "causes.csv",
        "closed_days.csv",
        "worlds.csv",
        "world_overrides.csv",
    ],
}

OUTPUT_FILES = ["results.csv", "row_map.csv", "run_record.json"]

# grid.json is optional — listed in OUTPUT_FILES only when built
_GRID_FILE = "grid.json"


# ---------------------------------------------------------------------------
# 1. normalised_sha256
# ---------------------------------------------------------------------------

def normalised_sha256(path) -> str:
    """Read bytes, strip BOM and normalise CRLF, return SHA-256 hex digest."""
    data = Path(path).read_bytes()
    # Remove leading UTF-8 BOM if present
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    # Normalise CRLF to LF
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 2. code_files
# ---------------------------------------------------------------------------

def code_files() -> list:
    """Return sorted list of every *.py under engine/ and montecarlo/ (recursive)."""
    result = []
    for folder in (REPO_ROOT / "engine", REPO_ROOT / "montecarlo"):
        for p in folder.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            result.append(p.as_posix().replace(
                REPO_ROOT.as_posix() + "/", ""
            ))
    return sorted(result)


# ---------------------------------------------------------------------------
# 3. make_fingerprint
# ---------------------------------------------------------------------------

def make_fingerprint(data_dir, settings: dict) -> dict:
    """Build a fingerprint dict for the given data folder and settings."""
    data_dir = Path(data_dir).resolve()

    # Represent data_dir relative to REPO_ROOT if inside it, else absolute.
    try:
        rel = data_dir.relative_to(REPO_ROOT)
        data_dir_str = rel.as_posix()
    except ValueError:
        data_dir_str = data_dir.as_posix()

    inputs = {}
    for name in INPUT_FILES["required"]:
        p = data_dir / name
        if not p.exists():
            raise ValueError(f"make_fingerprint: required input missing: {name}")
        inputs[name] = normalised_sha256(p)
    for name in INPUT_FILES["optional"]:
        p = data_dir / name
        if p.exists():
            inputs[name] = normalised_sha256(p)
        else:
            inputs[name] = "absent"

    code = {}
    for rel_path in code_files():
        code[rel_path] = normalised_sha256(REPO_ROOT / rel_path)

    return {
        "version": 1,
        "data_dir": data_dir_str,
        "settings": {
            "seed": settings["seed"],
            "M": settings["M"],
            "N": settings["N"],
            "method": settings["method"],
        },
        "inputs": inputs,
        "code": code,
    }


# ---------------------------------------------------------------------------
# 4. build_result_table
# ---------------------------------------------------------------------------

def build_result_table(db_with_worlds, worlds_csv_path, out_dir) -> dict:
    """Write results.csv and row_map.csv to out_dir."""
    out_dir = Path(out_dir)
    worlds_csv_path = Path(worlds_csv_path)

    with worlds_csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        value_cols = header[3:]  # everything after world_id, draw, weight

        raw_rows = list(reader)

    # Identify distinct worlds by value-cell tuples (exact strings).
    # world_index = 0-based order of first appearance.
    world_index_map = {}  # value_tuple -> world_index
    world_index_first_row = {}  # world_index -> raw row

    for raw_row in raw_rows:
        value_cells = tuple(raw_row[3:])
        if value_cells not in world_index_map:
            idx = len(world_index_map)
            world_index_map[value_cells] = idx
            world_index_first_row[idx] = raw_row

    # Disrupted scenarios from db["scenarios"] in scenarios.csv order.
    # db["scenarios"] is an ordered dict (insertion order = CSV order).
    scenario_sids = []
    for sid, s in db_with_worlds["scenarios"].items():
        dis_id = s.get("disruption_id", "")
        if dis_id and dis_id in db_with_worlds["disruptions"]:
            scenario_sids.append((dis_id, sid))

    # Validate that world rows in db_with_worlds match data rows in worlds_csv.
    for i, raw_row in enumerate(raw_rows):
        wid_csv = raw_row[0]
        wid_db = db_with_worlds["worlds"][i]["world_id"]
        if wid_csv != wid_db:
            raise ValueError(
                f"build_result_table: worlds mismatch at row {i}: "
                f"worlds.csv has {wid_csv!r}, db has {wid_db!r}"
            )

    # Simulate each (distinct world, scenario) pair.
    # Find the first db world row for each distinct world.
    db_world_for_index = {}
    for i, raw_row in enumerate(raw_rows):
        value_cells = tuple(raw_row[3:])
        idx = world_index_map[value_cells]
        if idx not in db_world_for_index:
            db_world_for_index[idx] = db_with_worlds["worlds"][i]

    # Build result rows: one per distinct world.
    result_rows = []
    for idx in range(len(world_index_map)):
        world = db_world_for_index[idx]
        first_raw = world_index_first_row[idx]
        row = {"world_index": str(idx)}
        # Copy value cells verbatim from the first occurrence.
        for col, val in zip(value_cols, first_raw[3:]):
            row[col] = val
        # Simulate each disrupted scenario.
        for dis_id, sid in scenario_sids:
            late, cost = world_result(db_with_worlds, dis_id, sid, world)
            row[f"late_orders.{sid}"] = str(late)
            row[f"extra_cost.{sid}"] = str(cost)
        result_rows.append(row)

    # Build results.csv header.
    results_header = ["world_index"] + value_cols
    for _, sid in scenario_sids:
        results_header.append(f"late_orders.{sid}")
        results_header.append(f"extra_cost.{sid}")

    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=results_header, lineterminator="\n")
        w.writeheader()
        w.writerows(result_rows)

    # Build row_map.csv: world_id, draw, weight, world_index per data row.
    row_map_header = ["world_id", "draw", "weight", "world_index"]
    row_map_rows = []
    for i, raw_row in enumerate(raw_rows):
        value_cells = tuple(raw_row[3:])
        idx = world_index_map[value_cells]
        row_map_rows.append({
            "world_id": raw_row[0],
            "draw": raw_row[1],
            "weight": raw_row[2],
            "world_index": str(idx),
        })

    with (out_dir / "row_map.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=row_map_header, lineterminator="\n")
        w.writeheader()
        w.writerows(row_map_rows)

    return {
        "distinct_worlds": len(world_index_map),
        "scenarios": [sid for _, sid in scenario_sids],
    }


# ---------------------------------------------------------------------------
# 5. rebuild_worlds_csv
# ---------------------------------------------------------------------------

def rebuild_worlds_csv(run_dir, out_path):
    """Reconstruct worlds.csv from results.csv + row_map.csv in run_dir."""
    run_dir = Path(run_dir)

    # Read row_map to get world_id, draw, weight, world_index per row.
    with (run_dir / "row_map.csv").open(encoding="utf-8", newline="") as fh:
        row_map_rows = list(csv.DictReader(fh))

    # Read results to get value columns per world_index.
    with (run_dir / "results.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        results_header = reader.fieldnames
        results_by_index = {}
        for row in reader:
            results_by_index[row["world_index"]] = row

    # Value columns are results header columns after world_index, excluding
    # late_orders.* and extra_cost.* columns.
    value_cols = [
        c for c in results_header[1:]
        if not c.startswith("late_orders.") and not c.startswith("extra_cost.")
    ]

    # Build worlds.csv header = ["world_id", "draw", "weight"] + value_cols.
    worlds_header = ["world_id", "draw", "weight"] + value_cols

    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=worlds_header)
        w.writeheader()
        for rm in row_map_rows:
            idx = rm["world_index"]
            result_row = results_by_index[idx]
            row = {
                "world_id": rm["world_id"],
                "draw": rm["draw"],
                "weight": rm["weight"],
            }
            for col in value_cols:
                row[col] = result_row[col]
            w.writerow(row)


# ---------------------------------------------------------------------------
# 6. check_run
# ---------------------------------------------------------------------------

def check_run(run_dir, data_dir) -> dict:
    """Verify that run_dir's fingerprint matches the current data and code."""
    run_dir = Path(run_dir).resolve()
    data_dir = Path(data_dir).resolve()

    fp_path = run_dir / "fingerprint.json"
    if not fp_path.exists():
        raise ValueError(
            f"run folder {run_dir} has no fingerprint.json; the run did not finish"
        )

    with fp_path.open(encoding="utf-8") as fh:
        fp = json.load(fh)

    settings = fp["settings"]
    diffs = []

    # Check inputs.
    current_inputs = {}
    for name in INPUT_FILES["required"]:
        p = data_dir / name
        if not p.exists():
            current_inputs[name] = "absent"
        else:
            current_inputs[name] = normalised_sha256(p)
    for name in INPUT_FILES["optional"]:
        p = data_dir / name
        if p.exists():
            current_inputs[name] = normalised_sha256(p)
        else:
            current_inputs[name] = "absent"

    for name, expected in fp["inputs"].items():
        got = current_inputs.get(name, "absent")
        if got != expected:
            diffs.append(("changed", name))

    # Check code files.
    current_code_files = set(code_files())
    fp_code = fp.get("code", {})
    fp_code_files = set(fp_code.keys())

    changed_code = []
    for rel_path in fp_code_files & current_code_files:
        cur_hash = normalised_sha256(REPO_ROOT / rel_path)
        if cur_hash != fp_code[rel_path]:
            changed_code.append(rel_path)
    added_code = sorted(current_code_files - fp_code_files)
    removed_code = sorted(fp_code_files - current_code_files)

    for f in sorted(changed_code):
        diffs.append(("changed", f))
    for f in added_code:
        diffs.append(("added", f))
    for f in removed_code:
        diffs.append(("removed", f))

    # Check outputs.
    fp_outputs = fp.get("outputs", {})
    for name, expected in fp_outputs.items():
        p = run_dir / name
        if not p.exists():
            diffs.append(("removed", name))
        else:
            got = normalised_sha256(p)
            if got != expected:
                diffs.append(("changed", name))

    # Check for a grid.json that exists but is not covered by the fingerprint.
    grid_path = run_dir / _GRID_FILE
    if grid_path.exists() and _GRID_FILE not in fp_outputs:
        # Format --out: POSIX-relative to REPO_ROOT if inside it, else absolute.
        try:
            out_posix = run_dir.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            out_posix = str(run_dir)
        rerun = (
            f"python -m montecarlo.run"
            f" --data {fp['data_dir']}"
            f" --out {out_posix}"
            f" --M {settings['M']}"
            f" --N {settings['N']}"
            f" --seed {settings['seed']}"
        )
        if settings.get("method") == "plain":
            rerun += " --plain"
        raise ValueError(
            f"grid.json is not covered by the fingerprint\n{rerun}"
        )

    if diffs:
        changed = sorted(f for cat, f in diffs if cat == "changed")
        added = sorted(f for cat, f in diffs if cat == "added")
        removed = sorted(f for cat, f in diffs if cat == "removed")

        lines = []
        if changed:
            lines.append("changed: " + ", ".join(changed))
        if added:
            lines.append("added: " + ", ".join(added))
        if removed:
            lines.append("removed: " + ", ".join(removed))

        # Format --out: POSIX-relative to REPO_ROOT if inside it, else absolute.
        try:
            out_posix = run_dir.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            out_posix = str(run_dir)

        rerun = (
            f"python -m montecarlo.run"
            f" --data {fp['data_dir']}"
            f" --out {out_posix}"
            f" --M {settings['M']}"
            f" --N {settings['N']}"
            f" --seed {settings['seed']}"
        )
        if settings.get("method") == "plain":
            rerun += " --plain"
        lines.append(rerun)
        raise ValueError("\n".join(lines))

    return fp


# ---------------------------------------------------------------------------
# 7. grid_status and load_grid
# ---------------------------------------------------------------------------

def grid_status(run_dir) -> str:
    """Return "present" or "absent" based on fingerprint outputs."""
    run_dir = Path(run_dir).resolve()
    fp_path = run_dir / "fingerprint.json"
    if not fp_path.exists():
        return "absent"
    with fp_path.open(encoding="utf-8") as fh:
        fp = json.load(fh)
    if _GRID_FILE in fp.get("outputs", {}):
        return "present"
    return "absent"


def load_grid(run_dir, data_dir) -> dict:
    """Load grid.json from run_dir.

    Calls check_run first (raises ValueError if fingerprint invalid).
    Raises ValueError if grid.json is not listed in fingerprint outputs.
    Returns the parsed grid dict.
    """
    run_dir = Path(run_dir).resolve()
    data_dir = Path(data_dir).resolve()
    fp = check_run(run_dir, data_dir)
    if _GRID_FILE not in fp.get("outputs", {}):
        raise ValueError(
            f"run folder {run_dir} has no grid.json in its fingerprint outputs; "
            "run with --grid to build it"
        )
    grid_path = run_dir / _GRID_FILE
    with grid_path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 8. evaluate_run
# ---------------------------------------------------------------------------

# Cache for parsed result tables: (resolved_run_dir_str, results_hash, row_map_hash) -> parsed data
_RUN_CACHE: dict = {}


def evaluate_run(disruption_id: str, db: dict, run_dir,
                 level: Fraction = Fraction(9, 10)) -> dict:
    """Evaluate worlds from a run folder."""
    if disruption_id not in db["disruptions"]:
        raise ValueError(f"evaluate_run: unknown disruption_id {disruption_id!r}")

    run_dir = Path(run_dir).resolve()

    # Derive data_dir from the fingerprint (the fingerprint records which folder
    # was used; that is the folder we validate against).
    fp_path = run_dir / "fingerprint.json"
    if not fp_path.exists():
        raise ValueError(
            f"run folder {run_dir} has no fingerprint.json; the run did not finish"
        )
    with fp_path.open(encoding="utf-8") as fh:
        _fp_tmp = json.load(fh)
    _fp_data_str = _fp_tmp.get("data_dir", "")
    _fp_data_path = Path(_fp_data_str)
    if not _fp_data_path.is_absolute():
        _fp_data_path = (REPO_ROOT / _fp_data_path).resolve()
    else:
        _fp_data_path = _fp_data_path.resolve()

    # Always check first.
    fp = check_run(run_dir, _fp_data_path)

    results_path = run_dir / "results.csv"
    row_map_path = run_dir / "row_map.csv"

    # Cache key based on resolved run dir and output hashes.
    results_hash = normalised_sha256(results_path)
    row_map_hash = normalised_sha256(row_map_path)
    cache_key = (str(run_dir), results_hash, row_map_hash)

    if cache_key not in _RUN_CACHE:
        # Parse results.csv.
        with results_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            results_rows = list(reader)

        # Parse row_map.csv.
        with row_map_path.open(encoding="utf-8", newline="") as fh:
            row_map_rows = list(csv.DictReader(fh))

        _RUN_CACHE[cache_key] = (results_rows, row_map_rows)
    else:
        results_rows, row_map_rows = _RUN_CACHE[cache_key]

    # Build results lookup: world_index -> results row.
    results_by_index = {row["world_index"]: row for row in results_rows}

    # Sum integer weights per world_index.
    weight_by_index: dict = {}
    for rm in row_map_rows:
        idx = rm["world_index"]
        weight_by_index[idx] = weight_by_index.get(idx, 0) + int(rm["weight"])

    total_rows = len(row_map_rows)

    # Find scenario columns for this disruption.
    disrupted_scenario_ids = [
        sid for sid, s in db["scenarios"].items()
        if s.get("disruption_id", "") == disruption_id
    ]

    # Build weighted_results: one entry per distinct world with weight > 0.
    weighted_results = []
    for idx_str, weight in weight_by_index.items():
        if weight <= 0:
            continue
        result_row = results_by_index[idx_str]
        results = {}
        for sid in disrupted_scenario_ids:
            late = int(result_row[f"late_orders.{sid}"])
            cost = int(result_row[f"extra_cost.{sid}"])
            results[sid] = (late, cost)
        weighted_results.append((weight, results))

    result = aggregate_options(disruption_id, db, weighted_results, "run",
                               total_rows, level)

    # Add run path.
    try:
        run_rel = Path(run_dir).relative_to(REPO_ROOT)
        result["run"] = run_rel.as_posix()
    except ValueError:
        result["run"] = str(run_dir)

    return result


# ---------------------------------------------------------------------------
# 8. selected_run_for
# ---------------------------------------------------------------------------

def selected_run_for(data_dir) -> "Path | None":
    """Return the selected run folder for data_dir, or None."""
    if SELECTION_PATH is None or not Path(SELECTION_PATH).exists():
        return None

    with open(SELECTION_PATH, encoding="utf-8") as fh:
        try:
            obj = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{SELECTION_PATH}: invalid JSON: {exc}"
            ) from exc

    if not isinstance(obj, dict) or list(obj.keys()) != ["run"]:
        raise ValueError(
            f"{SELECTION_PATH}: must be a JSON object with exactly one key \"run\""
        )

    run_val = obj["run"]
    if not isinstance(run_val, str) or not run_val:
        raise ValueError(
            f"{SELECTION_PATH}: \"run\" must be a non-empty string"
        )

    # Resolve the run path.
    run_path = Path(run_val)
    if not run_path.is_absolute():
        run_path = (REPO_ROOT / run_path).resolve()
    else:
        run_path = run_path.resolve()

    if not run_path.exists():
        raise ValueError(
            f"{SELECTION_PATH}: run folder does not exist: {run_path}"
        )
    if not (run_path / "fingerprint.json").exists():
        raise ValueError(
            f"{SELECTION_PATH}: run folder has no fingerprint.json: {run_path}"
        )

    # Read fingerprint to find data_dir.
    with (run_path / "fingerprint.json").open(encoding="utf-8") as fh:
        fp = json.load(fh)

    fp_data_dir_str = fp.get("data_dir", "")
    fp_data_path = Path(fp_data_dir_str)
    if not fp_data_path.is_absolute():
        fp_data_path = (REPO_ROOT / fp_data_path).resolve()
    else:
        fp_data_path = fp_data_path.resolve()

    data_dir_resolved = Path(data_dir).resolve()

    if fp_data_path != data_dir_resolved:
        return None

    # Same folder: check for worlds.csv conflict.
    if (data_dir_resolved / "worlds.csv").exists():
        raise ValueError(
            f"run_selection.json selects {run_path} but "
            f"{data_dir_resolved}/worlds.csv also exists; remove one of them"
        )

    return run_path


# ---------------------------------------------------------------------------
# 9. CLI
# ---------------------------------------------------------------------------

def main():
    from engine.loader import _DEFAULT_DATA_DIR

    if "--check" not in sys.argv:
        print("Usage: python -m engine.runs --check", file=sys.stderr)
        sys.exit(1)

    if SELECTION_PATH is None or not Path(SELECTION_PATH).exists():
        print("no run selected")
        sys.exit(0)

    try:
        run_dir = selected_run_for(_DEFAULT_DATA_DIR)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if run_dir is None:
        print("no run selected")
        sys.exit(0)

    try:
        check_run(run_dir, _DEFAULT_DATA_DIR)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Format run_dir for display: POSIX-relative to REPO_ROOT if inside it, else absolute.
    try:
        run_display = run_dir.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        run_display = str(run_dir)
    print(f"run {run_display}: inputs, code and outputs match")
    gs = grid_status(run_dir)
    print(f"grid: {gs}")
    sys.exit(0)


if __name__ == "__main__":
    main()
