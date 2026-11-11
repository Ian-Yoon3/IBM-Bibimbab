"""Tests for scripts/stage1_triangular_worlds.py.

Expected numbers in test_a_defaults were computed in advance.
If they do not match the function output, this test reports the difference
and stops without modifying the expected values.
"""

import csv
import io
import pathlib
import tempfile
import unittest
from datetime import date

from scripts.stage1_triangular_worlds import triangular_day_weights, write_worlds

_EXPECTED_A = [14, 42, 70, 98, 126, 154, 173, 141, 101, 61, 20]


class TestTriangularDayWeights(unittest.TestCase):

    # ------------------------------------------------------------------
    # (a) Default parameters must match pre-computed expected values.
    # ------------------------------------------------------------------
    def test_a_defaults(self):
        """Weights for 11-11 / mode 11-17 / 11-21, total 1000."""
        result = triangular_day_weights(
            date(2026, 11, 11), date(2026, 11, 17), date(2026, 11, 21), 1000
        )
        got = [w for _, w in result]
        if got != _EXPECTED_A:
            # Report the difference without modifying expected values, then stop.
            lines = [
                "test_a_defaults: weights do not match pre-computed expectation.",
                f"  expected: {_EXPECTED_A}",
                f"  got:      {got}",
                "  diff (got - expected):",
            ]
            for i, (e, g) in enumerate(zip(_EXPECTED_A, got)):
                if e != g:
                    lines.append(f"    index {i}: expected {e}, got {g}")
            self.fail("\n".join(lines))
        self.assertEqual(sum(got), 1000)

    # ------------------------------------------------------------------
    # (b) Symmetric input produces symmetric weights that sum to total.
    #     total=242 divides evenly for this range so no rounding asymmetry.
    # ------------------------------------------------------------------
    def test_b_symmetric(self):
        """Symmetric input (11-11, mode 11-16, 11-21) with total=242."""
        result = triangular_day_weights(
            date(2026, 11, 11), date(2026, 11, 16), date(2026, 11, 21), 242
        )
        weights = [w for _, w in result]
        self.assertEqual(sum(weights), 242)
        self.assertEqual(
            weights, weights[::-1],
            f"weights are not symmetric: {weights}"
        )

    # ------------------------------------------------------------------
    # (c) mode == earliest: function works; first day has the largest weight.
    #     Uses a two-day range where the left-edge peak dominates day 0.
    # ------------------------------------------------------------------
    def test_c_mode_equals_earliest(self):
        """mode == earliest with a two-day range."""
        result = triangular_day_weights(
            date(2026, 11, 11), date(2026, 11, 11), date(2026, 11, 12), 100
        )
        weights = [w for _, w in result]
        self.assertEqual(sum(weights), 100)
        self.assertEqual(
            weights[0], max(weights),
            f"first day should have the largest weight; got {weights}"
        )

    # ------------------------------------------------------------------
    # (d) earliest == mode == latest: single world with weight total.
    # ------------------------------------------------------------------
    def test_d_single_day(self):
        """Degenerate: all three dates equal."""
        result = triangular_day_weights(
            date(2026, 11, 15), date(2026, 11, 15), date(2026, 11, 15), 500
        )
        self.assertEqual(len(result), 1)
        day, weight = result[0]
        self.assertEqual(day, date(2026, 11, 15))
        self.assertEqual(weight, 500)

    # ------------------------------------------------------------------
    # (e) Error cases.
    # ------------------------------------------------------------------
    def test_e_wrong_date_order_raises(self):
        """earliest > mode must raise ValueError."""
        with self.assertRaises(ValueError):
            triangular_day_weights(
                date(2026, 11, 17), date(2026, 11, 11), date(2026, 11, 21), 100
            )

    def test_e_mode_after_latest_raises(self):
        """mode > latest must raise ValueError."""
        with self.assertRaises(ValueError):
            triangular_day_weights(
                date(2026, 11, 11), date(2026, 11, 22), date(2026, 11, 21), 100
            )

    def test_e_zero_total_raises(self):
        """total == 0 must raise ValueError."""
        with self.assertRaises(ValueError):
            triangular_day_weights(
                date(2026, 11, 11), date(2026, 11, 17), date(2026, 11, 21), 0
            )

    def test_e_negative_total_raises(self):
        """total < 0 must raise ValueError."""
        with self.assertRaises(ValueError):
            triangular_day_weights(
                date(2026, 11, 11), date(2026, 11, 17), date(2026, 11, 21), -5
            )

    # ------------------------------------------------------------------
    # (f) Writing to a temporary folder produces correct files.
    # ------------------------------------------------------------------
    def test_f_write_worlds(self):
        """Writing default weights gives exact headers, 11 rows, matching ids."""
        weights = triangular_day_weights(
            date(2026, 11, 11), date(2026, 11, 17), date(2026, 11, 21), 1000
        )
        self.assertEqual(len(weights), 11)

        with tempfile.TemporaryDirectory() as tmp:
            write_worlds(weights, "PO01", tmp)

            worlds_path = pathlib.Path(tmp) / "worlds.csv"
            overrides_path = pathlib.Path(tmp) / "world_overrides.csv"

            self.assertTrue(worlds_path.exists())
            self.assertTrue(overrides_path.exists())

            with open(worlds_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertEqual(reader.fieldnames, ["world_id", "weight"])
                w_rows = list(reader)
            self.assertEqual(len(w_rows), 11)

            with open(overrides_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertEqual(
                    reader.fieldnames,
                    ["world_id", "target_type", "target_id", "field", "value"]
                )
                o_rows = list(reader)
            self.assertEqual(len(o_rows), 11)

            # World ids must be identical in both files, in order
            world_ids_w = [r["world_id"] for r in w_rows]
            world_ids_o = [r["world_id"] for r in o_rows]
            self.assertEqual(world_ids_w, world_ids_o)
            self.assertEqual(world_ids_w[0], "W001")
            self.assertEqual(world_ids_w[-1], "W011")

    # ------------------------------------------------------------------
    # (g) No other file under engine/, agent/, or scripts/ (except this
    #     script itself) contains the text "stage1_triangular_worlds".
    # ------------------------------------------------------------------
    def test_g_no_spurious_imports(self):
        """No file under engine/, agent/, or scripts/ (other than the script
        itself) references 'stage1_triangular_worlds'."""
        root = pathlib.Path(__file__).parent.parent
        script_path = root / "scripts" / "stage1_triangular_worlds.py"
        search_dirs = [root / "engine", root / "agent", root / "scripts"]
        violations = []
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for py_file in search_dir.rglob("*.py"):
                if py_file.resolve() == script_path.resolve():
                    continue
                text = py_file.read_text(encoding="utf-8", errors="replace")
                if "stage1_triangular_worlds" in text:
                    violations.append(str(py_file.relative_to(root)))
        self.assertEqual(
            violations, [],
            f"Unexpected reference(s) to 'stage1_triangular_worlds': {violations}"
        )


if __name__ == "__main__":
    unittest.main()
