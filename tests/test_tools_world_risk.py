"""Tests for engine/tools.py get_world_risk()."""

import json
import pathlib
import shutil
import tempfile
import unittest

from engine.loader import load_all
from engine.tools import compare_scenarios, get_disruption, get_world_risk
from engine.worlds import evaluate_worlds

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

_SCOPE_NOTE_FILE = (
    "Weights come from data/worlds.csv. Each world is one possible receipt"
    " date of the delayed PO. Time and cost are shown side by side."
    " The engine does not pick an option."
)
_SCOPE_NOTE_ANNOUNCED = (
    "No world files. The announced receipt date has full weight."
    " Time and cost are shown side by side."
    " The engine does not pick an option."
)


def _copy_data(tmp):
    dest = pathlib.Path(tmp) / "data"
    shutil.copytree(_DATA_DIR, dest)
    return dest


class TestGetWorldRisk(unittest.TestCase):

    # (a) Result is JSON-serialisable without a custom default.
    def test_a_json_serialisable(self):
        result = get_world_risk("D01")
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            self.fail(f"get_world_risk result is not JSON-serialisable: {exc}")

    # (b) Every key of evaluate_worlds("D01", load_all()) is present with the
    #     same value, plus "scope_note".
    def test_b_all_evaluate_worlds_keys_present(self):
        db = load_all()
        expected = evaluate_worlds("D01", db)
        result = get_world_risk("D01")

        for key, val in expected.items():
            self.assertIn(key, result, msg=f"Key {key!r} missing from result")
            self.assertEqual(result[key], val,
                             msg=f"Key {key!r}: expected {val!r}, got {result[key]!r}")

        self.assertIn("scope_note", result)

    # (c) Repo data: weights_source "file" and the "file" scope_note.
    def test_c_repo_data_source_file(self):
        result = get_world_risk("D01")
        self.assertEqual(result["weights_source"], "file")
        self.assertEqual(result["scope_note"], _SCOPE_NOTE_FILE)

    # (d) Without world files: weights_source "announced_date", other scope_note,
    #     and per-option single-world numbers equal compare_scenarios late_orders.
    def test_d_no_world_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()

            result = get_world_risk("D01", data_dir=dd)
            cs = compare_scenarios(data_dir=dd)

        self.assertEqual(result["weights_source"], "announced_date")
        self.assertEqual(result["scope_note"], _SCOPE_NOTE_ANNOUNCED)

        cs_by_sid = {o["scenario_id"]: o for o in cs["ranked"]}
        for opt in result["options"]:
            sid = opt["scenario_id"]
            expected_late = cs_by_sid[sid]["late_orders"]
            for key in ("expected_late_orders", "worst_late_orders",
                        "p90_late_orders"):
                self.assertEqual(
                    opt[key], expected_late,
                    msg=f"{sid} {key}: expected {expected_late}, got {opt[key]}"
                )

    # (e) Unknown disruption_id raises ValueError.
    def test_e_unknown_disruption_id(self):
        with self.assertRaises(ValueError):
            get_world_risk("D99")

    # (f) Calling twice returns equal results; get_disruption still shows
    #     revised_receipt_date 2026-11-17 afterwards.
    def test_f_idempotent_and_no_mutation(self):
        r1 = get_world_risk("D01")
        r2 = get_world_risk("D01")
        self.assertEqual(r1, r2)

        dis = get_disruption("D01")
        self.assertEqual(dis["revised_receipt_date"], "2026-11-17")

    # (g) TOOL_SPECS still has exactly 8 entries; none is named get_world_risk.
    def test_g_tool_specs_unchanged(self):
        from agent.tool_specs import TOOL_SPECS
        self.assertEqual(len(TOOL_SPECS), 8)
        names = {spec["function"]["name"] for spec in TOOL_SPECS}
        self.assertNotIn("get_world_risk", names)


if __name__ == "__main__":
    unittest.main()
