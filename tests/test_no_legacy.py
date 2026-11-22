"""Tests for P4b no-legacy assertions: lane delay without causes.csv,
legacy-column rejection, and legacy fields removed from estimate output.
"""

import csv
import pathlib
import shutil
import tempfile
import unittest

_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def _copy_data(tmp_dir):
    """Copy the repository data/ into tmp_dir/data and return the path."""
    dest = pathlib.Path(tmp_dir) / "data"
    shutil.copytree(_DATA_DIR, dest, dirs_exist_ok=True)
    return dest


def _write_worlds(dd, header_line, *row_lines):
    text = "\n".join([header_line] + list(row_lines)) + "\n"
    with (dd / "worlds.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# 1. test_lane_delay_applies_without_causes
# ---------------------------------------------------------------------------

class TestLaneDelayWithoutCauses(unittest.TestCase):
    """Lane delay_days is applied even when causes.csv is absent."""

    _HEADER = (
        "world_id,draw,weight,"
        "purchase_order.PO01.receipt_date,"
        "lane.LN01.delay_days,"
        "lane.LN02.delay_days"
    )
    _ROW = "W,0,1,2026-11-17,5,5"

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_all
        from engine.worlds import apply_world
        from engine.simulate import build_scenario_actions, simulate

        cls._tmp = tempfile.mkdtemp()
        dd = _copy_data(cls._tmp)
        (dd / "causes.csv").unlink(missing_ok=True)
        _write_worlds(dd, cls._HEADER, cls._ROW)
        db = load_all(dd)
        w = db["worlds"][0]
        db_w = apply_world(db, w)
        actions, disruption_id = build_scenario_actions("TRANSFER", db_w)
        cls.ledger = simulate(actions, disruption_id, db_w)["ledger"]
        cls._world = w

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _transfer_in_dates(self):
        return [
            (e["reference_id"], e["date"])
            for e in self.ledger
            if e["event_type"] == "TRANSFER_IN"
        ]

    # test 1
    def test_lane_delay_applies_without_causes(self):
        """LN01 delay 5 -> arrival 2026-11-16; LN02 delay 5 -> 2026-11-18."""
        events = self._transfer_in_dates()
        self.assertEqual(events, [("LN01", "2026-11-16"), ("LN02", "2026-11-18")])

    # test 3
    def test_loaded_world_has_no_tags_key(self):
        """Worlds loaded from new-format file must not carry a 'tags' key."""
        self.assertNotIn("tags", self._world)


# ---------------------------------------------------------------------------
# 2. test_lane_delay_zero_without_causes_keeps_base
# ---------------------------------------------------------------------------

class TestLaneDelayZeroWithoutCauses(unittest.TestCase):
    """Zero lane delay keeps base arrival dates."""

    _HEADER = (
        "world_id,draw,weight,"
        "purchase_order.PO01.receipt_date,"
        "lane.LN01.delay_days,"
        "lane.LN02.delay_days"
    )
    _ROW = "W,0,1,2026-11-17,0,0"

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_all
        from engine.worlds import apply_world
        from engine.simulate import build_scenario_actions, simulate

        cls._tmp = tempfile.mkdtemp()
        dd = _copy_data(cls._tmp)
        (dd / "causes.csv").unlink(missing_ok=True)
        _write_worlds(dd, cls._HEADER, cls._ROW)
        db = load_all(dd)
        w = db["worlds"][0]
        db_w = apply_world(db, w)
        actions, disruption_id = build_scenario_actions("TRANSFER", db_w)
        cls.ledger = simulate(actions, disruption_id, db_w)["ledger"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _transfer_in_dates(self):
        return [
            (e["reference_id"], e["date"])
            for e in self.ledger
            if e["event_type"] == "TRANSFER_IN"
        ]

    def test_lane_delay_zero_without_causes_keeps_base(self):
        """Zero delay -> LN01 base 2026-11-11, LN02 base 2026-11-13."""
        events = self._transfer_in_dates()
        self.assertEqual(events, [("LN01", "2026-11-11"), ("LN02", "2026-11-13")])


# ---------------------------------------------------------------------------
# 4. test_lane_cap_without_causes
# ---------------------------------------------------------------------------

class TestLaneCapWithoutCauses(unittest.TestCase):
    """LN01 delay 363 loads; 364 raises ValueError."""

    _HEADER = (
        "world_id,draw,weight,"
        "purchase_order.PO01.receipt_date,"
        "lane.LN01.delay_days"
    )

    def _make_dd(self):
        """Return a fresh temp data dir (no causes.csv)."""
        tmp = tempfile.mkdtemp()
        dd = _copy_data(tmp)
        (dd / "causes.csv").unlink(missing_ok=True)
        return tmp, dd

    def test_lane_cap_363_loads(self):
        from engine.loader import load_all
        tmp, dd = self._make_dd()
        try:
            _write_worlds(dd, self._HEADER, "W,0,1,2026-11-17,363")
            db = load_all(dd)  # must not raise
            self.assertEqual(
                db["worlds"][0]["overrides"][("lane", "LN01", "delay_days")], 363
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_lane_cap_364_raises(self):
        from engine.loader import load_all
        tmp, dd = self._make_dd()
        try:
            _write_worlds(dd, self._HEADER, "W,0,1,2026-11-17,364")
            with self.assertRaises(ValueError):
                load_all(dd)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. test_lane_lead_days_column_rejected
# ---------------------------------------------------------------------------

class TestLaneLegacyColumnRejected(unittest.TestCase):
    """lane.<id>.lead_days column raises ValueError with 'no longer supported'."""

    def test_lane_lead_days_column_rejected(self):
        from engine.loader import load_all
        tmp = tempfile.mkdtemp()
        try:
            dd = _copy_data(tmp)
            (dd / "causes.csv").unlink(missing_ok=True)
            header = (
                "world_id,draw,weight,"
                "purchase_order.PO01.receipt_date,"
                "lane.LN01.lead_days"
            )
            _write_worlds(dd, header, "W,0,1,2026-11-17,3")
            with self.assertRaises(ValueError) as cm:
                load_all(dd)
            self.assertIn("no longer supported", str(cm.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6. test_cause_active_column_rejected
# ---------------------------------------------------------------------------

class TestCauseLegacyColumnRejected(unittest.TestCase):
    """cause.<id>.active column raises ValueError with 'no longer supported'."""

    def test_cause_active_column_rejected(self):
        from engine.loader import load_all
        tmp = tempfile.mkdtemp()
        try:
            dd = _copy_data(tmp)
            (dd / "causes.csv").unlink(missing_ok=True)
            header = (
                "world_id,draw,weight,"
                "purchase_order.PO01.receipt_date,"
                "cause.K1.active"
            )
            _write_worlds(dd, header, "W,0,1,2026-11-17,1")
            with self.assertRaises(ValueError) as cm:
                load_all(dd)
            self.assertIn("no longer supported", str(cm.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 7. test_estimate_has_no_legacy_fields
# ---------------------------------------------------------------------------

class TestEstimateHasNoLegacyFields(unittest.TestCase):
    """estimate() cause records must not contain p_active, w_days or rate_rate."""

    def test_estimate_has_no_legacy_fields(self):
        from montecarlo.estimate import estimate

        tmp = tempfile.mkdtemp()
        try:
            dd = _copy_data(tmp)
            # Use the committed history files (data/history/ already exists)
            result = estimate(dd)
            for cause_id, rec in result["causes"].items():
                for bad_key in ("p_active", "w_days", "rate_rate"):
                    self.assertNotIn(
                        bad_key, rec,
                        msg=(
                            f"cause {cause_id!r}: legacy key {bad_key!r} "
                            f"must not be in estimate output"
                        ),
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
