"""Tests for episode-based shock simulation and evaluation (Stage 2 P3c)."""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date
from fractions import Fraction

from engine.episodes import cause_of, derived_tags, first_overlap_delay, world_identity
from engine.loader import load_all
from engine.worlds import apply_world, evaluate_worlds

_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Header constants
# ---------------------------------------------------------------------------

# Base new-format header: 1 K1 slot, 1 K2 slot
_BASE_HDR = (
    "world_id,draw,weight,"
    "purchase_order.PO01.receipt_date,"
    "offer.OF02.delay_business_days,"
    "lane.LN01.delay_days,"
    "lane.LN02.delay_days,"
    "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
    "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
)

# Extended header: 2 K1 slots, 1 K2 slot
_EXT_HDR = (
    "world_id,draw,weight,"
    "purchase_order.PO01.receipt_date,"
    "offer.OF02.delay_business_days,"
    "lane.LN01.delay_days,"
    "lane.LN02.delay_days,"
    "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
    "cause.K1.ep2_start_date,cause.K1.ep2_end_date,cause.K1.ep2_delay_days,"
    "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
)

# Legacy header (lead_days instead of delay_days, no cause columns)
_LEGACY_HDR = (
    "world_id,draw,weight,"
    "purchase_order.PO01.receipt_date,"
    "offer.OF02.delay_business_days,"
    "lane.LN01.lead_days,"
    "lane.LN02.lead_days"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_data(tmp_dir):
    dest = pathlib.Path(tmp_dir) / "data"
    shutil.copytree(_DATA_DIR, dest, dirs_exist_ok=True)
    return dest


def _copy_data_later_order(tmp_dir):
    """Copy data and modify HYBRID action_date in recovery_purchases to 2026-11-20."""
    dest = _copy_data(tmp_dir)
    rp_path = dest / "recovery_purchases.csv"
    rows = []
    with rp_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            if row["scenario_id"] == "HYBRID":
                row["action_date"] = "2026-11-20"
            rows.append(row)
    with rp_path.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return dest


def _write_worlds(dd, header_line, *row_lines):
    text = "\n".join([header_line] + list(row_lines)) + "\n"
    (dd / "worlds.csv").write_text(text, encoding="utf-8", newline="\n")


def _load_new(dd, header, *rows):
    _write_worlds(dd, header, *rows)
    return load_all(dd)


def _late(result, sid):
    for opt in result["options"]:
        if opt["scenario_id"] == sid:
            return opt["expected_late_orders"]
    raise KeyError(sid)


def _ledger_date(sim, event_type, ref_id):
    """Return the date string of the first ledger entry matching event_type and ref_id."""
    for entry in sim["ledger"]:
        if entry["event_type"] == event_type and entry["reference_id"] == ref_id:
            return entry["date"]
    return None


def _simulate_scenario(db, scenario_id):
    from engine.simulate import build_scenario_actions, simulate
    actions, disruption_id = build_scenario_actions(scenario_id, db)
    return simulate(actions, disruption_id, db)


# ---------------------------------------------------------------------------
# Unit tests for episodes.py
# ---------------------------------------------------------------------------

class TestCauseOf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_all(_DATA_DIR)

    def test_offer_of02_is_k1(self):
        self.assertEqual(cause_of(self.db, "offer", "OF02"), "K1")

    def test_lane_ln01_is_k2(self):
        self.assertEqual(cause_of(self.db, "lane", "LN01"), "K2")

    def test_lane_ln02_is_k2(self):
        self.assertEqual(cause_of(self.db, "lane", "LN02"), "K2")

    def test_offer_of01_is_none(self):
        self.assertIsNone(cause_of(self.db, "offer", "OF01"))

    def test_no_causes_returns_none(self):
        db2 = dict(self.db)
        db2["causes"] = None
        self.assertIsNone(cause_of(db2, "offer", "OF02"))


class TestFirstOverlapDelay(unittest.TestCase):
    def _ep(self, start, end, delay):
        return {"start": date.fromisoformat(start), "end": date.fromisoformat(end), "delay": delay}

    def test_empty_episodes_returns_zero(self):
        self.assertEqual(first_overlap_delay([], date(2026, 11, 9), date(2026, 11, 12)), 0)

    def test_overlapping_episode_returns_delay(self):
        eps = [self._ep("2026-11-10", "2026-11-11", 2)]
        self.assertEqual(first_overlap_delay(eps, date(2026, 11, 9), date(2026, 11, 12)), 2)

    def test_no_overlap_start_after_promised(self):
        eps = [self._ep("2026-11-13", "2026-11-14", 3)]
        self.assertEqual(first_overlap_delay(eps, date(2026, 11, 9), date(2026, 11, 12)), 0)

    def test_no_overlap_end_before_order(self):
        eps = [self._ep("2026-11-05", "2026-11-08", 2)]
        self.assertEqual(first_overlap_delay(eps, date(2026, 11, 9), date(2026, 11, 12)), 0)

    def test_first_episode_wins_over_second(self):
        eps = [
            self._ep("2026-11-09", "2026-11-09", 1),
            self._ep("2026-11-11", "2026-11-12", 4),
        ]
        self.assertEqual(first_overlap_delay(eps, date(2026, 11, 9), date(2026, 11, 12)), 1)

    def test_second_episode_when_first_no_overlap(self):
        eps = [
            self._ep("2026-11-13", "2026-11-14", 3),
            self._ep("2026-11-20", "2026-11-21", 2),
        ]
        self.assertEqual(first_overlap_delay(eps, date(2026, 11, 20), date(2026, 11, 23)), 2)


class TestWorldIdentity(unittest.TestCase):
    def test_same_overrides_same_identity(self):
        w1 = {"overrides": {("purchase_order", "PO01", "receipt_date"): date(2026, 11, 17)}, "episodes": {}}
        w2 = {"overrides": {("purchase_order", "PO01", "receipt_date"): date(2026, 11, 17)}, "episodes": {}}
        self.assertEqual(world_identity(w1), world_identity(w2))

    def test_different_episodes_differ(self):
        w1 = {"overrides": {}, "episodes": {"K1": [{"start": date(2026, 11, 10), "end": date(2026, 11, 11), "delay": 2}]}}
        w2 = {"overrides": {}, "episodes": {"K1": [{"start": date(2026, 11, 13), "end": date(2026, 11, 14), "delay": 3}]}}
        self.assertNotEqual(world_identity(w1), world_identity(w2))

    def test_empty_episodes_match(self):
        w1 = {"overrides": {}, "episodes": {}}
        w2 = {"overrides": {}, "episodes": {}}
        self.assertEqual(world_identity(w1), world_identity(w2))


# ---------------------------------------------------------------------------
# N-series: standard data directory
# ---------------------------------------------------------------------------

class TestNSeriesBase(unittest.TestCase):
    """Base class: creates a fresh tempdir for each test method."""

    def _run(self, header, row, data_dir=None):
        dd_src = data_dir or _DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "data"
            shutil.copytree(dd_src, dest, dirs_exist_ok=True)
            _write_worlds(dest, header, row)
            db = load_all(dest)
            result = evaluate_worlds("D01", db)
            return result, db

    def _assert_lates(self, result, wait, transfer, alt_buy, hybrid):
        self.assertEqual(_late(result, "WAIT"), wait, "WAIT")
        self.assertEqual(_late(result, "TRANSFER"), transfer, "TRANSFER")
        self.assertEqual(_late(result, "ALT_BUY"), alt_buy, "ALT_BUY")
        self.assertEqual(_late(result, "HYBRID"), hybrid, "HYBRID")

    def _receipt_from_result(self, db, scenario_id, event_type, ref_id):
        sim = _simulate_scenario(db, scenario_id)
        return _ledger_date(sim, event_type, ref_id)


class TestN1(TestNSeriesBase):
    """N1: PO01 2026-11-17, OF02 own=0, LN01 own=0, LN02 own=0, no episodes."""

    _ROW = "N1,0,1,2026-11-17,0,0,0,none,none,none,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 3, 1)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-12")

    def test_transfer_ln01_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN01")
        self.assertEqual(receipt, "2026-11-11")

    def test_transfer_ln02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN02")
        self.assertEqual(receipt, "2026-11-13")


class TestN2(TestNSeriesBase):
    """N2: PO01 2026-11-19, K1 ep1 2026-11-10..2026-11-11 delay 2."""

    _ROW = "N2,0,1,2026-11-19,0,0,0,2026-11-10,2026-11-11,2,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 10, 7, 10, 7)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-16")


class TestN2b(TestNSeriesBase):
    """N2b: as N2 with OF02 own=-1."""

    _ROW = "N2b,0,1,2026-11-19,-1,0,0,2026-11-10,2026-11-11,2,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 10, 7, 8, 5)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-13")


class TestN3(TestNSeriesBase):
    """N3: PO01 2026-11-19, K1 ep1 2026-11-13..2026-11-14 delay 3; no overlap for OF02."""

    _ROW = "N3,0,1,2026-11-19,0,0,0,2026-11-13,2026-11-14,3,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 10, 7, 6, 4)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-12")


class TestN4(TestNSeriesBase):
    """N4: PO01 2026-11-17, K2 ep1 2026-11-12..2026-11-12 delay 2; LN01 no overlap, LN02 overlaps."""

    _ROW = "N4,0,1,2026-11-17,0,0,0,none,none,none,2026-11-12,2026-11-12,2"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 5, 3, 1)

    def test_transfer_ln01_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN01")
        self.assertEqual(receipt, "2026-11-11")

    def test_transfer_ln02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN02")
        self.assertEqual(receipt, "2026-11-15")


class TestN5(TestNSeriesBase):
    """N5: PO01 2026-11-17, LN01 own=-1, K2 ep1 2026-11-05..2026-11-10 delay 1."""

    _ROW = "N5,0,1,2026-11-17,0,-1,0,none,none,none,2026-11-05,2026-11-10,1"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 5, 3, 1)

    def test_transfer_ln01_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN01")
        self.assertEqual(receipt, "2026-11-11")

    def test_transfer_ln02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN02")
        self.assertEqual(receipt, "2026-11-14")


class TestN6(TestNSeriesBase):
    """N6: PO01 2026-11-17, LN01 own=-5; arrival pushed to action_date+1."""

    _ROW = "N6,0,1,2026-11-17,0,-5,0,none,none,none,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 3, 1)

    def test_transfer_ln01_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "TRANSFER", "TRANSFER_IN", "LN01")
        self.assertEqual(receipt, "2026-11-10")


class TestN7(TestNSeriesBase):
    """N7: PO01 2026-11-17, K1 ep1 2026-11-09..2026-11-09 delay 1 and ep2 2026-11-11..2026-11-12 delay 4.

    First overlap for OF02 (promised 2026-11-12) is ep1 (start=11-09 <= 11-12, end=11-09 >= 11-09).
    """

    _ROW = "N7,0,1,2026-11-17,0,0,0,2026-11-09,2026-11-09,1,2026-11-11,2026-11-12,4,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_EXT_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 5, 2)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_EXT_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-13")


# ---------------------------------------------------------------------------
# L-series: later-order data set (HYBRID action_date = 2026-11-20)
# ---------------------------------------------------------------------------

class TestLSeriesBase(unittest.TestCase):
    """Base class for L-series tests using the later-order data set."""

    def _run(self, header, row):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data_later_order(tmp)
            _write_worlds(dd, header, row)
            db = load_all(dd)
            result = evaluate_worlds("D01", db)
            return result, db

    def _assert_lates(self, result, wait, transfer, alt_buy, hybrid):
        self.assertEqual(_late(result, "WAIT"), wait, "WAIT")
        self.assertEqual(_late(result, "TRANSFER"), transfer, "TRANSFER")
        self.assertEqual(_late(result, "ALT_BUY"), alt_buy, "ALT_BUY")
        self.assertEqual(_late(result, "HYBRID"), hybrid, "HYBRID")

    def _receipt_from_result(self, db, scenario_id, event_type, ref_id):
        sim = _simulate_scenario(db, scenario_id)
        return _ledger_date(sim, event_type, ref_id)


class TestL1(TestLSeriesBase):
    """L1: K1 ep1 2026-11-20..2026-11-21 delay 2.

    ALT_BUY OF02 promised=2026-11-12 (no overlap). HYBRID OF02 promised=2026-11-23 (overlap, shock=2).
    """

    _ROW = "L1,0,1,2026-11-17,0,0,0,2026-11-20,2026-11-21,2,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 3, 4)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-12")

    def test_hybrid_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "HYBRID", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-25")


class TestL2(TestLSeriesBase):
    """L2: K1 ep1 2026-11-10..2026-11-11 delay 2.

    ALT_BUY OF02 promised=2026-11-12 (overlap, shock=2 -> 2026-11-16).
    HYBRID OF02 promised=2026-11-23 (end=11-11 < order_date=11-20: no overlap -> 2026-11-23).
    """

    _ROW = "L2,0,1,2026-11-17,0,0,0,2026-11-10,2026-11-11,2,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_BASE_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 7, 4)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-16")

    def test_hybrid_of02_receipt(self):
        result, db = self._run(_BASE_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "HYBRID", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-23")


class TestL3(TestLSeriesBase):
    """L3: as L2 plus K1 ep2 2026-11-22..2026-11-22 delay 3.

    ALT_BUY OF02: first overlap ep1 (shock=2) -> 2026-11-16.
    HYBRID OF02: ep1 no overlap, ep2 overlaps (shock=3) -> add_biz(11-23, 3)=2026-11-27.
    """

    _ROW = "L3,0,1,2026-11-17,0,0,0,2026-11-10,2026-11-11,2,2026-11-22,2026-11-22,3,none,none,none"

    def test_late_orders(self):
        result, _ = self._run(_EXT_HDR, self._ROW)
        self._assert_lates(result, 7, 4, 7, 4)

    def test_alt_buy_of02_receipt(self):
        result, db = self._run(_EXT_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "ALT_BUY", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-16")

    def test_hybrid_of02_receipt(self):
        result, db = self._run(_EXT_HDR, self._ROW)
        db_w = apply_world(db, db["worlds"][0])
        receipt = self._receipt_from_result(db_w, "HYBRID", "ALT_RECEIPT", "OF02")
        self.assertEqual(receipt, "2026-11-27")


# ---------------------------------------------------------------------------
# Cache test: two worlds with different episodes, same overrides
# ---------------------------------------------------------------------------

class TestCacheTwoWorlds(unittest.TestCase):
    """N2 and N3 as two rows (draw 0, weight 1 each): average late orders."""

    # N2: WAIT=10, TRANSFER=7, ALT_BUY=10, HYBRID=7
    # N3: WAIT=10, TRANSFER=7, ALT_BUY=6,  HYBRID=4
    # Averages: WAIT=10, TRANSFER=7, ALT_BUY=8.0, HYBRID=5.5

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        dd = _copy_data(cls._tmp)
        row_n2 = "N2,0,1,2026-11-19,0,0,0,2026-11-10,2026-11-11,2,none,none,none"
        row_n3 = "N3,0,1,2026-11-19,0,0,0,2026-11-13,2026-11-14,3,none,none,none"
        _write_worlds(dd, _BASE_HDR, row_n2, row_n3)
        cls.db = load_all(dd)
        cls.result = evaluate_worlds("D01", cls.db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _opt(self, sid):
        return next(o for o in self.result["options"] if o["scenario_id"] == sid)

    def test_wait_expected_late(self):
        self.assertEqual(self._opt("WAIT")["expected_late_orders"], 10.0)

    def test_transfer_expected_late(self):
        self.assertEqual(self._opt("TRANSFER")["expected_late_orders"], 7.0)

    def test_alt_buy_expected_late(self):
        self.assertEqual(self._opt("ALT_BUY")["expected_late_orders"], 8.0)

    def test_hybrid_expected_late(self):
        self.assertEqual(self._opt("HYBRID")["expected_late_orders"], 5.5)


# ---------------------------------------------------------------------------
# Horizon check test
# ---------------------------------------------------------------------------

class TestHorizonCheck(unittest.TestCase):
    """Action with promised date > H raises ValueError on new-format world.

    A world with no episodes (episode columns all 'none') has world_episodes=None,
    so the H check is not done and the same action does not raise.
    """

    # Explicit purchase of OF02 on 2026-11-25:
    #   promised = next_biz(2026-11-25 + 3) = next_biz(2026-11-28)
    #   Nov 28=Sat, Nov 29=Sun, Nov 30=Mon (business). next_biz(Nov 28)=Nov 30.
    # K1 H in standard data = 2026-11-17. Nov 30 > Nov 17 -> ValueError.

    _ACTION = {
        "type": "purchase",
        "offer_id": "OF02",
        "warehouse_id": "WH01",
        "action_date": "2026-11-25",
        "qty": 65,
    }

    def _new_world_row(self):
        return "N1,0,1,2026-11-17,0,0,0,none,none,none,none,none,none"

    def test_new_format_raises_value_error(self):
        from engine.simulate import simulate
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_worlds(dd, _BASE_HDR, self._new_world_row())
            db = load_all(dd)
            db_w = apply_world(db, db["worlds"][0])
            with self.assertRaises(ValueError):
                simulate([self._ACTION], "D01", db_w)

    def test_no_causes_csv_world_no_error(self):
        """Without causes.csv there are no episode columns; world_episodes=None skips H check."""
        from engine.simulate import simulate
        _NO_CAUSE_HDR = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days"
        )
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Remove causes.csv so episode columns are not required
            (dd / "causes.csv").unlink(missing_ok=True)
            _write_worlds(dd, _NO_CAUSE_HDR, "W1,0,1,2026-11-17,0,0,0")
            db = load_all(dd)
            db_w = apply_world(db, db["worlds"][0])
            # world_episodes is None (no episodes dict) -> no H check -> no raise
            simulate([self._ACTION], "D01", db_w)


# ---------------------------------------------------------------------------
# derived_tags tests (using the later-order data set for K1 H=2026-11-23, H0=2026-11-17)
# ---------------------------------------------------------------------------

class TestDerivedTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.dd = _copy_data_later_order(cls._tmp)
        # Load db without worlds file to get cause_horizons
        (cls.dd / "worlds.csv").unlink(missing_ok=True)
        cls.db = load_all(cls.dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _make_world(self, episodes):
        return {"overrides": {}, "episodes": episodes}

    def test_k1_ep_after_h0_gives_zero(self):
        """K1 episode 2026-11-18..2026-11-18: start(11-18) > H0(11-17) -> K1=0."""
        w = self._make_world({
            "K1": [{"start": date(2026, 11, 18), "end": date(2026, 11, 18), "delay": 1}],
            "K2": [],
        })
        tags = derived_tags(w, self.db)
        self.assertEqual(tags.get("K1"), 0)

    def test_k1_ep_on_h0_gives_one(self):
        """K1 episode 2026-11-17..2026-11-17: start=H0 and end >= DAY0 -> K1=1."""
        w = self._make_world({
            "K1": [{"start": date(2026, 11, 17), "end": date(2026, 11, 17), "delay": 1}],
            "K2": [],
        })
        tags = derived_tags(w, self.db)
        self.assertEqual(tags.get("K1"), 1)

    def test_k2_ep_before_day0_gives_one(self):
        """K2 episode 2026-11-05..2026-11-10: start <= H0(K2=11-13) and end >= DAY0 -> K2=1."""
        w = self._make_world({
            "K1": [],
            "K2": [{"start": date(2026, 11, 5), "end": date(2026, 11, 10), "delay": 1}],
        })
        tags = derived_tags(w, self.db)
        self.assertEqual(tags.get("K2"), 1)

    def test_no_episodes_gives_all_zero(self):
        """No episodes: both K1 and K2 get tag 0."""
        w = self._make_world({"K1": [], "K2": []})
        tags = derived_tags(w, self.db)
        self.assertEqual(tags.get("K1"), 0)
        self.assertEqual(tags.get("K2"), 0)

    def test_world_without_episodes_returns_empty(self):
        """A world without episodes (empty dict) returns {} (legacy tags no longer used)."""
        w = {"overrides": {}, "episodes": {}}
        tags = derived_tags(w, self.db)
        self.assertEqual(tags, {})


# ---------------------------------------------------------------------------
# Equivalence: new-format vs legacy for N1-N7
# ---------------------------------------------------------------------------

class TestEquivalenceNewVsLegacy(unittest.TestCase):
    """For N1-N7, the new-format world with equivalent delay_days gives same late counts
    as the equivalent world computed directly (formerly compared against legacy format).

    LN01 base lead=2, LN02 base lead=4.
    old lead X -> new delay = X - base.
    """

    def _late_new(self, header, new_row):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_worlds(dd, header, new_row)
            db = load_all(dd)
            return evaluate_worlds("D01", db)

    def _late_equiv(self, po01_date, of02_delay, ln01_delay, ln02_delay):
        """Build new-format world with given delays (no episodes) and evaluate.

        Uses _BASE_HDR but with causes.csv removed, since without causes there
        are no episode columns required.  ln01_delay = old_lead - 2 (base LN01),
        ln02_delay = old_lead - 4 (base LN02).
        """
        # Use a header without episode columns (no causes.csv)
        _NO_CAUSE_HDR = (
            "world_id,draw,weight,"
            "purchase_order.PO01.receipt_date,"
            "offer.OF02.delay_business_days,"
            "lane.LN01.delay_days,"
            "lane.LN02.delay_days"
        )
        row = f"WL,0,1,{po01_date},{of02_delay},{ln01_delay},{ln02_delay}"
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "causes.csv").unlink(missing_ok=True)
            _write_worlds(dd, _NO_CAUSE_HDR, row)
            db = load_all(dd)
            return evaluate_worlds("D01", db)

    def _lates(self, result):
        return {
            "WAIT": _late(result, "WAIT"),
            "TRANSFER": _late(result, "TRANSFER"),
            "ALT_BUY": _late(result, "ALT_BUY"),
            "HYBRID": _late(result, "HYBRID"),
        }

    def _check(self, header, new_row, po01_date, of02_delay, ln01_delay, ln02_delay):
        new_result = self._late_new(header, new_row)
        equiv_result = self._late_equiv(po01_date, of02_delay, ln01_delay, ln02_delay)
        self.assertEqual(self._lates(new_result), self._lates(equiv_result))

    def test_n1_equiv(self):
        """N1: no shock; OF02 delay=0, LN01 delay=0 (lead 2→delay 0), LN02 delay=0 (lead 4→delay 0)."""
        self._check(
            _BASE_HDR,
            "N1,0,1,2026-11-17,0,0,0,none,none,none,none,none,none",
            "2026-11-17", 0, 0, 0,
        )

    def test_n2_equiv(self):
        """N2: K1 shock=2 for OF02; of02_delay=0, LN1 delay=0, LN2 delay=0."""
        self._check(
            _BASE_HDR,
            "N2,0,1,2026-11-19,0,0,0,2026-11-10,2026-11-11,2,none,none,none",
            "2026-11-19", 2, 0, 0,
        )

    def test_n2b_equiv(self):
        """N2b: K1 shock=2, own=-1; of02_delay=-1, LN1 delay=0, LN2 delay=0."""
        self._check(
            _BASE_HDR,
            "N2b,0,1,2026-11-19,-1,0,0,2026-11-10,2026-11-11,2,none,none,none",
            "2026-11-19", 1, 0, 0,
        )

    def test_n3_equiv(self):
        """N3: K1 ep no overlap for OF02; delay=0; LN1 delay=0, LN2 delay=0."""
        self._check(
            _BASE_HDR,
            "N3,0,1,2026-11-19,0,0,0,2026-11-13,2026-11-14,3,none,none,none",
            "2026-11-19", 0, 0, 0,
        )

    def test_n4_equiv(self):
        """N4: K2 shock=2 for LN02; LN01 no overlap.
        LN01 delay=0 (lead 2→delay 0); LN02 delay=2 (lead 4+2=6→delay 2)."""
        self._check(
            _BASE_HDR,
            "N4,0,1,2026-11-17,0,0,0,none,none,none,2026-11-12,2026-11-12,2",
            "2026-11-17", 0, 0, 2,
        )

    def test_n5_equiv(self):
        """N5: LN01 own=-1, K2 shock=1; LN01 delay=-1, LN02 delay=1."""
        self._check(
            _BASE_HDR,
            "N5,0,1,2026-11-17,0,-1,0,none,none,none,2026-11-05,2026-11-10,1",
            "2026-11-17", 0, -1, 1,
        )

    def test_n6_equiv(self):
        """N6: LN01 own=-5, no shock; LN01 delay=-5, LN02 delay=0."""
        self._check(
            _BASE_HDR,
            "N6,0,1,2026-11-17,0,-5,0,none,none,none,none,none,none",
            "2026-11-17", 0, -5, 0,
        )

    def test_n7_equiv(self):
        """N7: K1 ep1 overlaps OF02 (shock=1); delay=0+1=1; LN1 delay=0, LN2 delay=0."""
        self._check(
            _EXT_HDR,
            "N7,0,1,2026-11-17,0,0,0,2026-11-09,2026-11-09,1,2026-11-11,2026-11-12,4,none,none,none",
            "2026-11-17", 1, 0, 0,
        )


if __name__ == "__main__":
    unittest.main()
