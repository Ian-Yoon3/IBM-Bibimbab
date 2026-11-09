"""Decision log: the record of what a human approved or rejected.

The agent only creates proposals (status ``pending_approval``).  This module
is the only place where a proposal becomes ``approved`` or ``rejected``, and
it is called by the UI when a person presses a button.  It is NOT offered to
the LLM: it is not in ``agent/tool_specs.TOOL_SPECS`` and ``call_tool`` cannot
reach it.

The log is a JSON Lines file (one decision per line).  The default location
is ``decisions/decision_log.jsonl`` at the repository root, which is
gitignored.  On a hosted app (for example Streamlit Community Cloud) the file
system is not permanent, so the log resets when the app restarts.  That is
acceptable for the demo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "decisions" / "decision_log.jsonl"


def _log_path(log_path) -> Path:
    return Path(log_path) if log_path is not None else DEFAULT_LOG


def list_decisions(log_path=None) -> list[dict]:
    """Return every recorded decision, oldest first.  Empty list if none."""
    path = _log_path(log_path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def record_decision(
    proposal: dict,
    approved: bool,
    decided_by: str,
    note: str = "",
    log_path=None,
) -> dict:
    """Record a human decision on a proposal and return the log entry.

    Parameters
    ----------
    proposal:
        The dict returned by ``propose_action`` (``run_agent(...)["proposal"]``).
        It must have a ``proposal_id`` and status ``pending_approval``.
    approved:
        True for approve, False for reject.  Must be a real bool.
    decided_by:
        Name of the person who pressed the button.  Must not be empty.
    note:
        Optional free-text comment.
    log_path:
        Optional override of the log file (tests use a temporary file).

    Raises
    ------
    ValueError
        If the proposal is malformed, not pending, already decided, or the
        inputs are invalid.  Nothing is written in that case.
    """
    if not isinstance(proposal, dict) or not proposal.get("proposal_id"):
        raise ValueError("proposal must be the dict returned by propose_action")
    if proposal.get("status") != "pending_approval":
        raise ValueError(
            f"proposal status is {proposal.get('status')!r}, expected 'pending_approval'"
        )
    if not isinstance(approved, bool):
        raise ValueError("approved must be True or False")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be a non-empty name")

    path = _log_path(log_path)
    pid = proposal["proposal_id"]
    if any(d["proposal_id"] == pid for d in list_decisions(path)):
        raise ValueError(f"proposal {pid} has already been decided")

    metrics = proposal.get("metrics") or {}
    entry = {
        "proposal_id": pid,
        "decision": "approved" if approved else "rejected",
        "decided_by": decided_by.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "disruption_id": proposal.get("disruption_id"),
        "actions": proposal.get("actions", []),
        "on_time_orders": metrics.get("on_time_orders"),
        "total_orders": metrics.get("total_orders"),
        "total_extra_cost": metrics.get("total_extra_cost"),
        "reason": proposal.get("reason", ""),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry
