"""Overview module: no-LLM entry point for the world-risk view.

get_overview() and get_data_overview() are functions the UI may call, alongside
run_agent, record_decision and list_decisions.  They make no network calls
and use no watsonx.ai credits.
"""

from agent.render import world_risk_view


def get_overview(disruption_id: str = "D01") -> dict:
    """Return the world_risk overview view for a disruption.

    No LLM call, no network.  Uses the engine cache after the first call.

    Parameters
    ----------
    disruption_id : str
        The disruption to summarise (default "D01").

    Returns
    -------
    world_risk_view("overview") dict.
    """
    return world_risk_view("overview", disruption_id=disruption_id)


def get_data_overview(data_dir=None) -> dict:
    """What the numbers are computed from: the data files and the selected
    Monte Carlo run.  No LLM call, no network, nothing is changed.

    Parameters
    ----------
    data_dir : path or None
        The data folder to describe (default: the folder the engine loads).

    Returns
    -------
    {
      "data_dir": "data",
      "files": [{"name": "orders.csv", "group": "inputs", "rows": 12}, ...],
      "run": {"status": "match" | "stale" | "invalid" | "none",
              "name": "runs/demo" | None, "message": str, "detail": str,
              "settings": {"M": .., "N": .., "seed": .., "method": ..} | None,
              "grid": "present" | "absent" | None, "created_at": str | None},
      "synthetic_history": bool,
      "upload": {"enabled": False, "note": str},
    }
    ``rows`` counts the data rows of a CSV file (the header is not counted).
    ``status`` is the result of the same check as ``python -m engine.runs --check``.
    """
    import csv
    import json
    from pathlib import Path

    import engine.loader as _loader
    import engine.runs as _runs
    from agent.render import _synthetic_history

    root = Path(data_dir) if data_dir is not None else Path(_loader._DEFAULT_DATA_DIR)

    files = []
    for path in sorted(root.rglob("*.csv"), key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            n_lines = sum(1 for row in csv.reader(fh) if row)
        files.append({
            "name": rel.as_posix(),
            "group": "history" if rel.parts[0] == "history" else "inputs",
            "rows": max(n_lines - 1, 0),
        })

    try:
        shown_dir = root.resolve().relative_to(_runs.REPO_ROOT).as_posix()
    except ValueError:
        shown_dir = str(root)

    run = {"status": "none", "name": None,
           "message": "No Monte Carlo run is selected. The risk numbers use the "
                      "weights in the data folder.",
           "detail": "", "settings": None, "grid": None, "created_at": None}
    try:
        run_dir = _runs.selected_run_for(root)
    except ValueError as exc:
        run_dir = None
        run.update(status="invalid", message="The run selection file cannot be read.",
                   detail=str(exc))
    if run_dir is not None:
        try:
            run["name"] = run_dir.relative_to(_runs.REPO_ROOT).as_posix()
        except ValueError:
            run["name"] = str(run_dir)
        try:
            fingerprint = _runs.check_run(run_dir, root)
        except ValueError as exc:
            run.update(status="stale",
                       message=f"The Monte Carlo run {run['name']} does not match the "
                               "current data or code. Its numbers must not be used "
                               "until the run is rebuilt.",
                       detail=str(exc))
        else:
            run.update(status="match",
                       message=f"Monte Carlo run {run['name']}: inputs, code and "
                               "outputs match.",
                       settings=dict(fingerprint["settings"]),
                       grid=_runs.grid_status(run_dir))
            record_path = run_dir / "run_record.json"
            if record_path.exists():
                with record_path.open(encoding="utf-8") as fh:
                    run["created_at"] = json.load(fh).get("created_at")

    return {
        "data_dir": shown_dir,
        "files": files,
        "run": run,
        "synthetic_history": _synthetic_history(),
        "upload": {
            "enabled": False,
            "note": "Not connected in this demo. A new data set needs a new Monte "
                    "Carlo run before any number in this app can change. Today the "
                    "files in the data folder are replaced and the run is rebuilt "
                    "with: python -m montecarlo.run",
        },
    }
