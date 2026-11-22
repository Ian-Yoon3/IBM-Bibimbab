"""Tests for the new-format worlds.csv episode loading in engine/loader.py.

Tests cover:
  - Horizon computation for K1 and K2 (base data, with recovery row variants)
  - Accepted world rows (all-none episodes, filled episodes, slot-1 running,
    two slots, negative lane delay)
  - Rejected rows (each rule 4a-4e and 5a-f violation named in the spec)
  - Data rules 6a and 6b
  - Legacy worlds.csv still loads with format="legacy"
"""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date

from engine.loader import load_all

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# Base header for a new-format worlds.csv that covers all cause/target columns.
_BASE_HEADER = (
    "world_id,draw,weight,"
    "purchase_order.PO01.receipt_date,"
    "offer.OF02.delay_business_days,"
    "lane.LN01.delay_days,"
    "lane.LN02.delay_days,"
    "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
    "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
)

# A minimal valid row with all episodes "none"
_NONE_ROW = "W1,0,1,2026-11-17,0,0,0,none,none,none,none,none,none"


def _copy_data(tmp_dir):
    """Copy DATA_DIR into tmp_dir/data and return the path."""
    dest = pathlib.Path(tmp_dir) / "data"
    shutil.copytree(DATA_DIR, dest, dirs_exist_ok=True)
    return dest


def _write_worlds(dd, header_line, *row_lines):
    """Write worlds.csv with the given header and rows."""
    text = "\n".join([header_line] + list(row_lines)) + "\n"
    (dd / "worlds.csv").write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------
# Horizon tests
# ---------------------------------------------------------------------------

class TestCauseHorizons(unittest.TestCase):
    """Verify H and H0 for K1 and K2 on the base data directory."""

    @classmethod
    def setUpClass(cls):
        cls.db = load_all(DATA_DIR)

    def test_k1_H0(self):
        h = self.db["cause_horizons"]["K1"]
        self.assertEqual(h["H0"], date(2026, 11, 17))

    def test_k1_H(self):
        h = self.db["cause_horizons"]["K1"]
        self.assertEqual(h["H"], date(2026, 11, 17))

    def test_k2_H0(self):
        h = self.db["cause_horizons"]["K2"]
        self.assertEqual(h["H0"], date(2026, 11, 13))

    def test_k2_H(self):
        h = self.db["cause_horizons"]["K2"]
        self.assertEqual(h["H"], date(2026, 11, 13))


class TestCauseHorizonsHybridOf02Moved(unittest.TestCase):
    """HYBRID's OF02 row moved to action_date 2026-11-20 extends K1 H."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        dd = _copy_data(cls.tmp)
        # Rewrite recovery_purchases with HYBRID action_date changed to 2026-11-20
        rp_text = (
            "scenario_id,offer_id,warehouse_id,action_date,qty\n"
            "ALT_BUY,OF02,WH01,2026-11-09,65\n"
            "HYBRID,OF02,WH01,2026-11-20,45\n"
        )
        (dd / "recovery_purchases.csv").write_text(
            rp_text, encoding="utf-8", newline="\n"
        )
        cls.db = load_all(dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_k1_H(self):
        h = self.db["cause_horizons"]["K1"]
        self.assertEqual(h["H"], date(2026, 11, 23))

    def test_k1_H0_unchanged(self):
        h = self.db["cause_horizons"]["K1"]
        self.assertEqual(h["H0"], date(2026, 11, 17))

    def test_k2_H_unchanged(self):
        h = self.db["cause_horizons"]["K2"]
        self.assertEqual(h["H"], date(2026, 11, 13))


class TestCauseHorizonsTransferLn02Moved(unittest.TestCase):
    """TRANSFER's LN02 row moved to action_date 2026-11-15 extends K2 H."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        dd = _copy_data(cls.tmp)
        # Rewrite recovery_transfers with TRANSFER LN02 action_date = 2026-11-15
        rt_text = (
            "scenario_id,lane_id,component_id,action_date,qty\n"
            "TRANSFER,LN01,C01,2026-11-09,18\n"
            "TRANSFER,LN02,C01,2026-11-15,14\n"
            "HYBRID,LN01,C01,2026-11-09,18\n"
            "HYBRID,LN02,C01,2026-11-09,14\n"
        )
        (dd / "recovery_transfers.csv").write_text(
            rt_text, encoding="utf-8", newline="\n"
        )
        cls.db = load_all(dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_k2_H(self):
        h = self.db["cause_horizons"]["K2"]
        self.assertEqual(h["H"], date(2026, 11, 19))

    def test_k2_H0_unchanged(self):
        h = self.db["cause_horizons"]["K2"]
        self.assertEqual(h["H0"], date(2026, 11, 13))

    def test_k1_H_unchanged(self):
        h = self.db["cause_horizons"]["K1"]
        self.assertEqual(h["H"], date(2026, 11, 17))


# ---------------------------------------------------------------------------
# Accepted worlds
# ---------------------------------------------------------------------------

class TestAcceptedWorlds(unittest.TestCase):
    """Positive tests for the new format."""

    def _load(self, header, *rows):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_worlds(dd, header, *rows)
            return load_all(dd)

    def test_all_none_episodes_accepted(self):
        """W1 with all-none episodes: format 'new', episodes K1=[], K2=[]."""
        db = self._load(_BASE_HEADER, _NONE_ROW)
        self.assertEqual(db["worlds_format"], "new")
        w = db["worlds"][0]
        self.assertEqual(w["episodes"], {"K1": [], "K2": []})

    def test_k1_slot_filled(self):
        """W2 with K1 slot 2026-11-10..2026-11-12 delay 2."""
        row = "W2,0,1,2026-11-17,0,0,0,2026-11-10,2026-11-12,2,none,none,none"
        db = self._load(_BASE_HEADER, row)
        w = db["worlds"][0]
        ep = w["episodes"]["K1"]
        self.assertEqual(len(ep), 1)
        self.assertEqual(ep[0]["start"], date(2026, 11, 10))
        self.assertEqual(ep[0]["end"], date(2026, 11, 12))
        self.assertEqual(ep[0]["delay"], 2)

    def test_slot1_running_on_day0_accepted(self):
        """W3: slot 1 starts 2026-11-05, ends 2026-11-11 (end >= DAY0)."""
        row = "W3,0,1,2026-11-17,0,0,0,2026-11-05,2026-11-11,2,none,none,none"
        db = self._load(_BASE_HEADER, row)
        ep = db["worlds"][0]["episodes"]["K1"]
        self.assertEqual(ep[0]["start"], date(2026, 11, 5))

    def test_two_k1_slots(self):
        """Two K1 slots: ep1 2026-11-10..2026-11-11 and ep2 2026-11-13..2026-11-14."""
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
            "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        row = (
            "W4,0,1,2026-11-17,0,0,0,"
            "2026-11-10,2026-11-11,1,"
            "2026-11-13,2026-11-14,1,"
            "none,none,none"
        )
        db = self._load(hdr, row)
        ep = db["worlds"][0]["episodes"]["K1"]
        self.assertEqual(len(ep), 2)
        self.assertEqual(ep[0]["start"], date(2026, 11, 10))
        self.assertEqual(ep[1]["start"], date(2026, 11, 13))

    def test_negative_lane_delay_accepted(self):
        """lane.LN01.delay_days = -1 is accepted."""
        row = "W5,0,1,2026-11-17,0,-1,0,none,none,none,none,none,none"
        db = self._load(_BASE_HEADER, row)
        ov = db["worlds"][0]["overrides"]
        self.assertEqual(ov.get(("lane", "LN01", "delay_days")), -1)


# ---------------------------------------------------------------------------
# Rejected rows (rule violations)
# ---------------------------------------------------------------------------

def _assert_worlds_error(test_case, header, *rows):
    """Assert that load_all raises ValueError with 'worlds.csv: ' prefix."""
    with tempfile.TemporaryDirectory() as tmp:
        dd = _copy_data(tmp)
        _write_worlds(dd, header, *rows)
        with test_case.assertRaises(ValueError) as ctx:
            load_all(dd)
        test_case.assertIn("worlds.csv: ", str(ctx.exception))


class TestMixedLegacyAndNewRaisesError(unittest.TestCase):
    """Mixed legacy and new columns in one file is an error."""

    def test_mixed_raises(self):
        # Base header (new) + cause.K1.active (legacy)
        hdr = (
            _BASE_HEADER + ",cause.K1.active"
        )
        row = _NONE_ROW + ",1"
        _assert_worlds_error(self, hdr, row)


class TestPartialNoneCellsRaisesError(unittest.TestCase):
    """Slot cells partly 'none' (not all-none and not all values)."""

    def test_partial_none_raises(self):
        # start=none but end and delay are values
        row = "W1,0,1,2026-11-17,0,0,0,none,2026-11-12,2,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


class TestEp2FilledWhileEp1NoneRaisesError(unittest.TestCase):
    """ep2 filled while ep1 is none."""

    def test_ep2_before_ep1_raises(self):
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
            "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        # ep1 is none, ep2 is values
        row = (
            "W1,0,1,2026-11-17,0,0,0,"
            "none,none,none,"
            "2026-11-13,2026-11-14,1,"
            "none,none,none"
        )
        _assert_worlds_error(self, hdr, row)


class TestStartAfterHRaisesError(unittest.TestCase):
    """K1 start_date after H=2026-11-17 raises error."""

    def test_start_after_H_raises(self):
        # K1 H = 2026-11-17; start 2026-11-18 is after H
        row = "W1,0,1,2026-11-17,0,0,0,2026-11-18,2026-11-18,1,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


class TestSlot1BeforeDayEndedBeforeDayRaisesError(unittest.TestCase):
    """Slot 1 starts before DAY0 AND ended before DAY0 raises error."""

    def test_slot1_before_day0_ended_before_day0_raises(self):
        # 2026-11-05..2026-11-08: start before DAY0 (2026-11-09), end before DAY0
        row = "W1,0,1,2026-11-17,0,0,0,2026-11-05,2026-11-08,2,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


class TestSlot2StartBeforeDayRaisesError(unittest.TestCase):
    """Slot 2 starting before DAY0 raises error."""

    def test_slot2_before_day0_raises(self):
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
            "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        # ep1 valid; ep2 starts at 2026-11-08 which is before DAY0
        row = (
            "W1,0,1,2026-11-17,0,0,0,"
            "2026-11-09,2026-11-10,1,"
            "2026-11-08,2026-11-11,1,"
            "none,none,none"
        )
        _assert_worlds_error(self, hdr, row)


class TestEndBeforeStartRaisesError(unittest.TestCase):
    """end_date < start_date raises error."""

    def test_end_before_start_raises(self):
        # end 2026-11-10 < start 2026-11-12
        row = "W1,0,1,2026-11-17,0,0,0,2026-11-12,2026-11-10,1,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


class TestDelayZeroRaisesError(unittest.TestCase):
    """delay_days 0 raises error (must be >= 1)."""

    def test_delay_zero_raises(self):
        row = "W1,0,1,2026-11-17,0,0,0,2026-11-10,2026-11-12,0,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


class TestOverlappingSlotsRaisesError(unittest.TestCase):
    """Overlapping slots: ep2 start <= ep1 end raises error."""

    def test_overlapping_slots_raises(self):
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
            "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        # ep1: 2026-11-10..2026-11-12; ep2 starts at 2026-11-12 <= ep1 end
        row = (
            "W1,0,1,2026-11-17,0,0,0,"
            "2026-11-10,2026-11-12,1,"
            "2026-11-12,2026-11-13,1,"
            "none,none,none"
        )
        _assert_worlds_error(self, hdr, row)


class TestRule4bK2ColumnsMissingRaisesError(unittest.TestCase):
    """Rule 4b: K2 has no episode columns while K2 is in causes.csv."""

    def test_k2_missing_raises(self):
        # Header has K1 episodes but NOT K2 episodes
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days"
        )
        row = "W1,0,1,2026-11-17,0,0,0,none,none,none"
        _assert_worlds_error(self, hdr, row)


class TestRule4cUnknownCauseK3RaisesError(unittest.TestCase):
    """Rule 4c: cause K3 columns while K3 is not in causes.csv."""

    def test_unknown_cause_raises(self):
        hdr = (
            _BASE_HEADER
            + ",cause.K3.ep1_start_date,cause.K3.ep1_end_date,cause.K3.ep1_delay_days"
        )
        row = _NONE_ROW + ",none,none,none"
        _assert_worlds_error(self, hdr, row)


class TestRule4dLnO2DelayMissingRaisesError(unittest.TestCase):
    """Rule 4d: lane.LN02.delay_days column missing while LN02 is in causes.csv."""

    def test_ln02_missing_raises(self):
        # Header has LN01 delay but not LN02 delay
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        row = "W1,0,1,2026-11-17,0,0,none,none,none,none,none,none"
        _assert_worlds_error(self, hdr, row)


class TestRule4eEp2WithoutEp1RaisesError(unittest.TestCase):
    """Rule 4e: ep2 columns without ep1 columns raises error."""

    def test_ep2_without_ep1_raises(self):
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        row = "W1,0,1,2026-11-17,0,0,0,none,none,none,none,none,none"
        _assert_worlds_error(self, hdr, row)


class TestRule4eEp1MissingDelayDaysRaisesError(unittest.TestCase):
    """Rule 4e: ep1 without its delay_days column raises error."""

    def test_ep1_missing_delay_days_raises(self):
        hdr = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days,"
            "cause.K1.ep1_start_date,cause.K1.ep1_end_date,"
            "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
        )
        row = "W1,0,1,2026-11-17,0,0,0,none,none,none,none,none"
        _assert_worlds_error(self, hdr, row)


class TestRule4aEpisodeColumnsNoCausesRaisesError(unittest.TestCase):
    """Rule 4a: episode columns with causes.csv removed raises error."""

    def test_no_causes_csv_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "causes.csv").unlink()
            _write_worlds(dd, _BASE_HEADER, _NONE_ROW)
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("worlds.csv: ", str(ctx.exception))


class TestCapCheckOfferDelayRaisesError(unittest.TestCase):
    """Rule 5f: OF02 delay 248 with K1 slot delay 1 exceeds cap."""

    def test_offer_delay_cap_raises(self):
        # OF02 delay_business_days = 248, K1 slot delay = 1
        # 248 + 1 = 249 business days after promised on DAY0 -> far past cap
        row = "W1,0,1,2026-11-17,248,0,0,2026-11-10,2026-11-12,1,none,none,none"
        _assert_worlds_error(self, _BASE_HEADER, row)


# ---------------------------------------------------------------------------
# Data rules
# ---------------------------------------------------------------------------

class TestDataRule6a(unittest.TestCase):
    """Rule 6a: recovery row with action_date before DAY0 raises ValueError."""

    def test_recovery_purchase_before_day0_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            rp_text = (
                "scenario_id,offer_id,warehouse_id,action_date,qty\n"
                "ALT_BUY,OF02,WH01,2026-11-09,65\n"
                "HYBRID,OF02,WH01,2026-11-09,45\n"
                "WAIT,OF02,WH01,2026-11-08,20\n"
            )
            (dd / "recovery_purchases.csv").write_text(
                rp_text, encoding="utf-8", newline="\n"
            )
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("2026-11-08", str(ctx.exception))


class TestDataRule6b(unittest.TestCase):
    """Rule 6b: recovery purchase ordering PO01's offer (OF01) must be a
    cause target if PO01 is a cause target."""

    def test_of01_not_cause_target_raises(self):
        """WAIT,OF01 in recovery_purchases while OF01 is not a K1 target."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            rp_text = (
                "scenario_id,offer_id,warehouse_id,action_date,qty\n"
                "ALT_BUY,OF02,WH01,2026-11-09,65\n"
                "HYBRID,OF02,WH01,2026-11-09,45\n"
                "WAIT,OF01,WH01,2026-11-09,5\n"
            )
            (dd / "recovery_purchases.csv").write_text(
                rp_text, encoding="utf-8", newline="\n"
            )
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_of01_added_to_causes_no_error(self):
        """With K1,business,offer,OF01 in causes.csv the error is gone."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            causes_text = (
                "cause_id,day_unit,target_type,target_id\n"
                "K1,business,purchase_order,PO01\n"
                "K1,business,offer,OF02\n"
                "K1,business,offer,OF01\n"
                "K2,calendar,lane,LN01\n"
                "K2,calendar,lane,LN02\n"
            )
            (dd / "causes.csv").write_text(
                causes_text, encoding="utf-8", newline="\n"
            )
            rp_text = (
                "scenario_id,offer_id,warehouse_id,action_date,qty\n"
                "ALT_BUY,OF02,WH01,2026-11-09,65\n"
                "HYBRID,OF02,WH01,2026-11-09,45\n"
                "WAIT,OF01,WH01,2026-11-09,5\n"
            )
            (dd / "recovery_purchases.csv").write_text(
                rp_text, encoding="utf-8", newline="\n"
            )
            db = load_all(dd)  # must not raise
            self.assertIsNotNone(db)


# ---------------------------------------------------------------------------
# Legacy worlds.csv still loads as before
# ---------------------------------------------------------------------------

class TestLegacyWorldsFormat(unittest.TestCase):
    """Legacy worlds.csv columns (lane.*.lead_days, cause.*.active) are rejected."""

    def test_legacy_format_detected(self):
        """lane.LN01.lead_days raises the 'no longer supported' error."""
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Remove causes.csv (legacy format doesn't require it)
            causes = dd / "causes.csv"
            if causes.exists():
                causes.unlink()
            # Write a legacy-format worlds.csv (lane.LN01.lead_days is a legacy column)
            hdr = (
                "world_id,draw,weight,"
                "purchase_order.PO01.receipt_date,"
                "lane.LN01.lead_days"
            )
            row = "W1,0,1,2026-11-17,2"
            _write_worlds(dd, hdr, row)
            with self.assertRaises(ValueError) as cm:
                load_all(dd)
            self.assertIn("no longer supported", str(cm.exception))


# ---------------------------------------------------------------------------
# Rule 4b applies even when no cause columns are present (correction)
# ---------------------------------------------------------------------------

class TestRule4bNoCauseColumnsWithCausesFileRaises(unittest.TestCase):
    """Rule 4b: causes.csv present + new-format worlds.csv with no episode
    columns at all must raise, naming the missing cause."""

    def test_no_episode_columns_raises_naming_cause(self):
        # Header has only PO01 receipt_date — no cause episode columns at all
        hdr = "world_id,draw,weight,purchase_order.PO01.receipt_date"
        row = "W1,0,1,2026-11-17"
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_worlds(dd, hdr, row)
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("worlds.csv: ", msg)
            # Error must name at least one cause from causes.csv
            self.assertTrue(
                "K1" in msg or "K2" in msg,
                f"Expected cause name in error: {msg}",
            )

    def test_no_episode_columns_no_causes_file_loads(self):
        """Same worlds.csv but causes.csv removed → loads fine, format 'new',
        episodes {} for the single world."""
        hdr = "world_id,draw,weight,purchase_order.PO01.receipt_date"
        row = "W1,0,1,2026-11-17"
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "causes.csv").unlink()
            _write_worlds(dd, hdr, row)
            db = load_all(dd)
            self.assertEqual(db["worlds_format"], "new")
            self.assertEqual(len(db["worlds"]), 1)
            self.assertEqual(db["worlds"][0]["episodes"], {})


# ---------------------------------------------------------------------------
# compute_cause_horizons requires calendar in db
# ---------------------------------------------------------------------------

class TestComputeCauseHorizonsRequiresCalendar(unittest.TestCase):
    """compute_cause_horizons raises ValueError when db has no 'calendar'."""

    def test_no_calendar_raises(self):
        from engine.causes import compute_cause_horizons
        from engine.loader import load_all as _load_all
        db = _load_all(DATA_DIR)
        causes = db["causes"]
        db_no_cal = {k: v for k, v in db.items() if k != "calendar"}
        with self.assertRaises(ValueError) as ctx:
            compute_cause_horizons(causes, db_no_cal)
        self.assertIn("calendar", str(ctx.exception))
