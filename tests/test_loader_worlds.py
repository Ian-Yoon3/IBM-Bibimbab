"""Tests for world file loading in engine/loader.py (wide format, ADR 0004).

Each numbered rule from the prompt has at least one positive and one
negative test.  Rule numbering matches the loader rules 1-8.
"""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date

from engine.loader import load_all

# Path to the repo data directory
_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _copy_data(tmp):
    """Copy the repo data directory into a temp directory and return the path."""
    dest = pathlib.Path(tmp) / "data"
    shutil.copytree(_DATA_DIR, dest)
    return dest


def _write_csv(path, rows):
    """Write rows (list of lists) to a CSV file; first row is the header."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# (a) Repo data as-is
# ---------------------------------------------------------------------------

class TestLoaderWorldsRepo(unittest.TestCase):
    """(a) Tests against the repo data files in the new wide format."""

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def test_a_world_count(self):
        worlds = self.db["worlds"]
        self.assertIsNotNone(worlds)
        self.assertEqual(len(worlds), 11)

    def test_a_world_ids(self):
        ids = [w["world_id"] for w in self.db["worlds"]]
        self.assertEqual(ids, [f"W{i:03d}" for i in range(1, 12)])

    def test_a_weights(self):
        weights = [w["weight"] for w in self.db["worlds"]]
        self.assertEqual(weights, [14, 42, 70, 98, 126, 154, 173, 141, 101, 61, 20])

    def test_a_all_draw_zero(self):
        for w in self.db["worlds"]:
            with self.subTest(world_id=w["world_id"]):
                self.assertEqual(w["draw"], 0)

    def test_a_each_world_has_one_override(self):
        for w in self.db["worlds"]:
            with self.subTest(world_id=w["world_id"]):
                self.assertEqual(len(w["overrides"]), 1)

    def test_a_override_key(self):
        key = ("purchase_order", "PO01", "receipt_date")
        for w in self.db["worlds"]:
            with self.subTest(world_id=w["world_id"]):
                self.assertIn(key, w["overrides"])

    def test_a_override_dates(self):
        key = ("purchase_order", "PO01", "receipt_date")
        expected_dates = [date(2026, 11, d) for d in range(11, 22)]
        actual_dates = [w["overrides"][key] for w in self.db["worlds"]]
        self.assertEqual(actual_dates, expected_dates)

    def test_a_weights_sum_1000(self):
        self.assertEqual(sum(w["weight"] for w in self.db["worlds"]), 1000)


# ---------------------------------------------------------------------------
# Rule 1: worlds.csv absent → db["worlds"] is None; other keys unchanged
# ---------------------------------------------------------------------------

class TestRule1Absent(unittest.TestCase):
    """Rule 1: worlds.csv absent -> db['worlds'] = None."""

    def test_rule1_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()

            db_no = load_all(dd)
            db_with = load_all()

            self.assertIsNone(db_no["worlds"])

            for key in db_with:
                if key == "worlds":
                    continue
                with self.subTest(key=key):
                    self.assertEqual(db_no[key], db_with[key])


# ---------------------------------------------------------------------------
# Rule 2: world_overrides.csv exists → error naming the file
# ---------------------------------------------------------------------------

class TestRule2OverridesRetired(unittest.TestCase):
    """Rule 2: world_overrides.csv still exists -> ValueError."""

    def test_rule2_overrides_alone_raises(self):
        """world_overrides.csv without worlds.csv still raises."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Create a world_overrides.csv (worlds.csv not present in this copy
            # because we start from a tmp that has worlds.csv; remove it)
            (dd / "worlds.csv").unlink()
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("world_overrides.csv", msg)
            self.assertIn("ADR 0004", msg)

    def test_rule2_overrides_with_worlds_raises(self):
        """world_overrides.csv alongside worlds.csv also raises."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # worlds.csv already exists; plant an overrides file too
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("world_overrides.csv", str(ctx.exception))


# ---------------------------------------------------------------------------
# Rule 3: header validation
# ---------------------------------------------------------------------------

class TestRule3Header(unittest.TestCase):
    """Rule 3: first three names must be world_id, draw, weight; at least one
    variable column; duplicate column names raise."""

    def _minimal_worlds(self, dd, header, row_values):
        """Write a minimal valid-or-invalid worlds.csv."""
        _write_csv(dd / "worlds.csv", [header, row_values])

    def test_rule3_valid_header_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._minimal_worlds(
                dd,
                ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            )
            db = load_all(dd)  # must not raise
            self.assertIsNotNone(db["worlds"])

    def test_rule3_missing_draw_column_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._minimal_worlds(
                dd,
                ["world_id", "weight", "purchase_order.PO01.receipt_date"],
                ["W1", "1", "2026-11-17"],
            )
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule3_no_variable_column_raises(self):
        """Only world_id, draw, weight — no variable column."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._minimal_worlds(
                dd,
                ["world_id", "draw", "weight"],
                ["W1", "0", "1"],
            )
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule3_duplicate_column_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            col = "purchase_order.PO01.receipt_date"
            self._minimal_worlds(
                dd,
                ["world_id", "draw", "weight", col, col],
                ["W1", "0", "1", "2026-11-17", "2026-11-17"],
            )
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("duplicate", str(ctx.exception).lower())

    def test_rule3_wrong_first_three_names_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._minimal_worlds(
                dd,
                ["world_id", "draw", "mass", "purchase_order.PO01.receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            )
            with self.assertRaises(ValueError):
                load_all(dd)


# ---------------------------------------------------------------------------
# Rule 4: variable column validation
# ---------------------------------------------------------------------------

class TestRule4VariableColumns(unittest.TestCase):
    """Rule 4: column name must split into 3 parts; kind must be in _OPEN_KINDS;
    for purchase_order, target_id must be a PO in disruptions."""

    def test_rule4_col_too_few_parts_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "draw", "weight", "PO01.receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule4_col_empty_part_raises(self):
        """Name like 'purchase_order..receipt_date' has an empty middle part."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "draw", "weight", "purchase_order..receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule4_unsupported_kind_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "draw", "weight", "offer.OF02.lead_days"],
                ["W1", "0", "1", "5"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("not supported", str(ctx.exception))

    def test_rule4_po_not_in_disruptions_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "draw", "weight", "purchase_order.PO99.receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule4_valid_kind_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"],
                ["W1", "0", "1", "2026-11-17"],
            ])
            db = load_all(dd)
            self.assertIsNotNone(db["worlds"])


# ---------------------------------------------------------------------------
# Rule 5: row-level field validation
# ---------------------------------------------------------------------------

class TestRule5RowFields(unittest.TestCase):
    """Rule 5: world_id non-empty; world_id unique; draw integer >= 0;
    weight integer >= 1; no empty cells."""

    def _w(self, dd, header, *data_rows):
        _write_csv(dd / "worlds.csv", [header, *data_rows])

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_rule5_empty_world_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["", "0", "1", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_duplicate_world_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H,
                    ["W001", "0", "50", "2026-11-15"],
                    ["W001", "0", "50", "2026-11-17"])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("W001", str(ctx.exception))

    def test_rule5_draw_negative_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "-1", "1", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_draw_float_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0.5", "1", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_draw_empty_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "", "1", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_weight_zero_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "0", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_weight_negative_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "-1", "2026-11-17"])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_weight_float_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "1.5", "2026-11-17"])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W1", msg)

    def test_rule5_weight_one_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "1", "2026-11-17"])
            db = load_all(dd)
            self.assertEqual(db["worlds"][0]["weight"], 1)

    def test_rule5_draw_zero_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "1", "2026-11-17"])
            db = load_all(dd)
            self.assertEqual(db["worlds"][0]["draw"], 0)

    def test_rule5_empty_variable_cell_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            self._w(dd, self._H, ["W1", "0", "1", ""])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule5_header_only_no_rows_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H])
            with self.assertRaises(ValueError):
                load_all(dd)


# ---------------------------------------------------------------------------
# Rule 6: receipt_date bounds
# ---------------------------------------------------------------------------

class TestRule6DateBounds(unittest.TestCase):
    """Rule 6: receipt_date >= planned_receipt_date; receipt_date <= horizon."""

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_rule6_date_before_planned_raises(self):
        """2026-11-10 < planned_receipt_date 2026-11-11."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W1", "0", "1", "2026-11-10"]])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_rule6_date_after_horizon_raises(self):
        """2026-11-22 > horizon 2026-11-21."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W1", "0", "1", "2026-11-22"]])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("stage 2", str(ctx.exception))

    def test_rule6_invalid_iso_date_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W1", "0", "1", "2026-13-01"]])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W1", msg)

    def test_rule6_planned_date_valid(self):
        """Exactly at planned_receipt_date (2026-11-11) is valid."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W1", "0", "1", "2026-11-11"]])
            db = load_all(dd)
            self.assertIsNotNone(db["worlds"])

    def test_rule6_horizon_date_valid(self):
        """Exactly at the horizon (2026-11-21) is valid."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W1", "0", "1", "2026-11-21"]])
            db = load_all(dd)
            self.assertIsNotNone(db["worlds"])


# ---------------------------------------------------------------------------
# Rule 7: every draw must have the same total weight
# ---------------------------------------------------------------------------

class TestRule7DrawWeights(unittest.TestCase):
    """Rule 7: unequal draw totals raise ValueError naming the draws."""

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_rule7_equal_totals_valid(self):
        """draw 0 total 2, draw 1 total 2 -> valid."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-11"],
                ["W2", "0", "1", "2026-11-17"],
                ["W3", "1", "2", "2026-11-21"],
            ])
            db = load_all(dd)
            self.assertEqual(len(db["worlds"]), 3)

    def test_rule7_unequal_totals_raises(self):
        """draw 0 total 2, draw 1 total 3 -> error."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-11"],
                ["W2", "0", "1", "2026-11-17"],
                ["W3", "1", "3", "2026-11-21"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            # Must name both draws and their totals
            self.assertIn("draw 0", msg)
            self.assertIn("draw 1", msg)

    def test_rule7_single_draw_valid(self):
        """Single draw is always valid (rule 7 trivially holds)."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "14", "2026-11-11"],
                ["W2", "0", "42", "2026-11-17"],
            ])
            db = load_all(dd)
            self.assertIsNotNone(db["worlds"])

    def test_rule7_error_names_worlds_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-11"],
                ["W2", "1", "2", "2026-11-17"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("worlds.csv", str(ctx.exception))


# ---------------------------------------------------------------------------
# Rule 8: duplicate value combinations are allowed
# ---------------------------------------------------------------------------

class TestRule8DuplicateValues(unittest.TestCase):
    """Rule 8: same date in two rows with different world_ids is allowed."""

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_rule8_duplicate_values_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-17"],
                ["W2", "0", "2", "2026-11-17"],  # same date, different world
            ])
            db = load_all(dd)
            self.assertEqual(len(db["worlds"]), 2)
            # Both rows must carry the same date
            key = ("purchase_order", "PO01", "receipt_date")
            dates = [w["overrides"][key] for w in db["worlds"]]
            self.assertEqual(dates[0], dates[1])


# ---------------------------------------------------------------------------
# Error messages must name worlds.csv and world_id
# ---------------------------------------------------------------------------

class TestErrorMessages(unittest.TestCase):
    """Error messages from row parsing must contain 'worlds.csv' and world_id."""

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_weight_error_names_file_and_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W003", "0", "1.5", "2026-11-17"]])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W003", msg)

    def test_date_error_names_file_and_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W005", "0", "1", "bad-date"]])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W005", msg)

    def test_draw_error_names_file_and_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [self._H, ["W007", "x", "1", "2026-11-17"]])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W007", msg)


if __name__ == "__main__":
    unittest.main()
