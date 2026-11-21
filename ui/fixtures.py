"""
ui/fixtures.py — Fixture loading and unique selection for Fixtures mode.

Each fixture entry is assigned a collision-free fixture_id using its
conversation, turn, and index in the loaded file. The same question text
can appear in both a successful result and an error result; the fixture_id
keeps them independent.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path resolution — relative to this file so it works regardless of cwd.
# ---------------------------------------------------------------------------
_FIXTURES_PATH = Path(__file__).parent.parent / "ui_fixtures" / "agent_results.json"


def load_fixtures() -> list[dict]:
    """Load and return all fixture entries from disk (never mutated)."""
    with open(_FIXTURES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def make_fixture_id(entry: dict, index: int) -> str:
    """Return a collision-free ID for a fixture entry.

    Format: ``conv<conversation>_t<turn>_i<index>``

    Using both the entry's own fields and its index in the loaded list
    guarantees uniqueness even when two entries share the same question.
    """
    return f"conv{entry['conversation']}_t{entry['turn']}_i{index}"


def build_fixture_catalog(fixtures: list[dict]) -> dict[str, dict]:
    """Return a mapping {fixture_id: entry} for every entry in *fixtures*."""
    return {make_fixture_id(e, i): e for i, e in enumerate(fixtures)}


def label_for(entry: dict, index: int) -> str:
    """Human-readable label shown in the selector drop-down.

    Includes a short description of the view type and, for error entries,
    an explicit "(error)" marker so they are distinguishable.
    """
    result = entry["result"]
    conv = entry["conversation"]
    turn = entry["turn"]
    question = entry["question"]
    short_q = question[:55] + "…" if len(question) > 55 else question

    # Tag error entries
    if "error" in result:
        tag = " ⚠ error"
    else:
        view = result.get("view")
        vtype = view.get("type") if view else "no_view"
        tag = f" [{vtype}]"

    # Tag multi-turn entries
    turn_label = f" (turn {turn})" if turn > 1 else ""

    return f"Conv {conv}{turn_label}{tag} — {short_q}"


def get_fixture_options(fixtures: list[dict]) -> list[tuple[str, str]]:
    """Return a list of (fixture_id, label) pairs for all fixtures.

    Preserves the order of the loaded file.
    """
    return [
        (make_fixture_id(e, i), label_for(e, i))
        for i, e in enumerate(fixtures)
    ]


def get_result_copy(catalog: dict[str, dict], fixture_id: str) -> Optional[dict]:
    """Return a deep copy of the result for *fixture_id*, or None if unknown."""
    entry = catalog.get(fixture_id)
    if entry is None:
        return None
    return copy.deepcopy(entry["result"])


def is_error_fixture(result: dict) -> bool:
    """Return True when *result* contains an error key."""
    return "error" in result


UNMATCHED_MESSAGE = (
    "This demo uses saved examples. "
    "Choose an example, or use Live agent for a new analysis."
)
