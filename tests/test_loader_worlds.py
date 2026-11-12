"""Tests for world file loading in engine/loader.py."""

import csv
import os
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


class TestLoaderWorldsRepo(unittest.TestCase):
    """(a) Tests against the repo data files as-is."""

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
        expected_dates = [
            date(2026, 11, d) for d in range(11, 22)
        ]
        actual_dates = [w["overrides"][key] for w in self.db["worlds"]]
        self.assertEqual(actual_dates, expected_dates)


class TestLoaderWorldsBothAbsent(unittest.TestCase):
    """(b) Both world files removed: db["worlds"] is None; all other keys unchanged."""

    def test_b_both_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()
            (dd / "world_overrides.csv").unlink()

            db_no_worlds = load_all(dd)
            db_with_worlds = load_all()

            self.assertIsNone(db_no_worlds["worlds"])

            # Every other db key must equal the repo load
            for key in db_with_worlds:
                if key == "worlds":
                    continue
                with self.subTest(key=key):
                    self.assertEqual(db_no_worlds[key], db_with_worlds[key])


class TestLoaderWorldsOnlyOne(unittest.TestCase):
    """(c) Only one world file present raises ValueError."""

    def test_c_only_worlds_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "world_overrides.csv").unlink()
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_c_only_overrides_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()
            with self.assertRaises(ValueError):
                load_all(dd)


class TestLoaderWorldsValidationErrors(unittest.TestCase):
    """(d) One ValueError test for each bad-data scenario."""

    # --- worlds.csv bad header ---
    def test_d_wrong_header_worlds(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "mass"],   # wrong column name
                ["W001", "100"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- world_overrides.csv bad header ---
    def test_d_wrong_header_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value", "extra"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17", "x"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- empty world_id ---
    def test_d_empty_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["", "100"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- duplicate world_id ---
    def test_d_duplicate_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "50"],
                ["W001", "50"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- weight 0 ---
    def test_d_weight_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "0"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- weight -1 ---
    def test_d_weight_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "-1"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- weight 1.5 (not an integer) ---
    def test_d_weight_float(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "1.5"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- weight 1 is valid (boundary: should load without error) ---
    def test_d_weight_one_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "1"],
            ])
            # overrides must still have a row for W001
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            db = load_all(dd)   # must not raise
            self.assertEqual(db["worlds"][0]["weight"], 1)

    # --- header only, no worlds ---
    def test_d_header_only_no_worlds(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- unknown world_id in overrides ---
    def test_d_unknown_world_id_in_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W999", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- world without overrides ---
    def test_d_world_without_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
                ["W002", "100"],
            ])
            # only W001 has an override; W002 has none
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- unsupported kind: offer / lead_days ---
    def test_d_unsupported_kind_offer_lead_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "offer", "OF02", "lead_days", "5"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("not supported", str(ctx.exception))

    # --- target_id PO99 not in disruptions ---
    def test_d_target_id_not_in_disruptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO99", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- same target twice in one world ---
    def test_d_same_target_twice_in_one_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-15"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- invalid ISO date value ---
    def test_d_invalid_date_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-13-01"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- receipt_date before the PO's planned_receipt_date (2026-11-10 < 2026-11-11) ---
    def test_d_date_before_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-10"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    # --- receipt_date after the horizon (2026-11-22 > 2026-11-21) ---
    def test_d_date_after_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W001", "purchase_order", "PO01", "receipt_date", "2026-11-22"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("stage 2", str(ctx.exception))


class TestLoaderWorldsErrorMessages(unittest.TestCase):
    """(e) Error messages name both the file and the world_id."""

    def test_e_error_names_file_and_world_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W001", "100"],
            ])
            # world_id W002 in overrides does not exist in worlds.csv
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W002", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("world_overrides.csv", msg)
            self.assertIn("W002", msg)


class TestLoaderWorldsMessagePrefix(unittest.TestCase):
    """Error messages from _int and kind parsers must be prefixed with file+world_id."""

    def test_weight_float_message_has_file_and_world_id(self):
        """weight '1.5': message contains 'worlds.csv' and the world_id."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W003", "1.5"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv", msg)
            self.assertIn("W003", msg)

    def test_invalid_date_message_has_file_and_world_id(self):
        """receipt_date '2026-13-01': message contains 'world_overrides.csv' and world_id."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W005", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W005", "purchase_order", "PO01", "receipt_date", "2026-13-01"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("world_overrides.csv", msg)
            self.assertIn("W005", msg)

    def test_empty_date_message_has_file_and_world_id(self):
        """Empty receipt_date value: message contains 'world_overrides.csv' and world_id."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W007", "100"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W007", "purchase_order", "PO01", "receipt_date", ""],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("world_overrides.csv", msg)
            self.assertIn("W007", msg)


if __name__ == "__main__":
    unittest.main()
