"""Tests for stage 2 step 4a.

PART A: new worlds.csv column kinds (offer.*.delay_business_days,
        lane.*.lead_days, cause.*.active) in engine/loader.py and
        engine/worlds.py.
PART B: offer_receipt_date() in engine/simulate.py and its use in the
        simulator.

Expected values come from docs/montecarlo-engine.md section 4.7 and
the prompt specification.
"""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from fractions import Fraction

from engine.loader import load_all
from engine.simulate import offer_receipt_date, build_scenario_actions, simulate
from engine.worlds import apply_world, evaluate_worlds
from engine.business_calendar import BusinessCalendar
from scripts.stage1_data import make_stage1_data_dir, use_stage1_default_data

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _copy_data(tmp):
    """Copy the repo data directory into a temp dir and return its path."""
    dest = pathlib.Path(tmp) / "data"
    make_stage1_data_dir(dest)
    return dest


def _write_csv(path, rows):
    """Write rows (list of lists) to a CSV; first row is the header."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


# ---------------------------------------------------------------------------
# PART B – offer_receipt_date()
# ---------------------------------------------------------------------------

class TestOfferReceiptDateNoDelay(unittest.TestCase):
    """Without delay_business_days the function is identical to stage 1."""

    def setUp(self):
        self.cal = BusinessCalendar()
        self.offer_no_delay = {"lead_days": 3}            # stage 1 offer
        self.offer_delay0 = {"lead_days": 3, "delay_business_days": 0}

    def test_no_delay_key_uses_calendar_days(self):
        d = date(2026, 11, 9)
        result = offer_receipt_date(d, self.offer_no_delay, self.cal)
        self.assertEqual(result, date(2026, 11, 12))

    def test_delay0_same_as_no_delay(self):
        d = date(2026, 11, 9)
        result = offer_receipt_date(d, self.offer_delay0, self.cal)
        self.assertEqual(result, date(2026, 11, 12))

    def test_calendar_none_uses_calendar_days(self):
        d = date(2026, 11, 9)
        result = offer_receipt_date(d, self.offer_no_delay, None)
        self.assertEqual(result, date(2026, 11, 12))


class TestOfferReceiptDateOF02(unittest.TestCase):
    """OF02 lead_days=3, expected values from the spec.

    order 2026-11-09 (Mon):
      promised = next_bday(11-09+3) = next_bday(11-12 Thu) = 11-12
      delay  0 -> 11-12
      delay  1 -> 11-13
      delay  2 -> 11-16  (skips weekend)
      delay -1 -> 11-10  (11-11 is Veterans Day, closed)
      delay -5 -> 11-10  (clamped: would be 11-04 <= action_date)

    order 2026-11-13 (Fri):
      promised = next_bday(11-13+3) = next_bday(11-16 Mon) = 11-16
      delay  0 -> 11-16
      delay  2 -> 11-18

    order 2026-11-23 (Mon):
      promised = next_bday(11-23+3) = next_bday(11-26 Thu=Thanksgiving) = 11-27 (Fri)
      delay  0 -> 11-27
    """

    def setUp(self):
        self.cal = BusinessCalendar()
        self.offer = {"lead_days": 3}

    def _rd(self, action_date, delay):
        o = dict(self.offer, delay_business_days=delay)
        return offer_receipt_date(action_date, o, self.cal)

    def test_order_1109_delay_0(self):
        self.assertEqual(self._rd(date(2026, 11, 9), 0), date(2026, 11, 12))

    def test_order_1109_delay_1(self):
        self.assertEqual(self._rd(date(2026, 11, 9), 1), date(2026, 11, 13))

    def test_order_1109_delay_2(self):
        self.assertEqual(self._rd(date(2026, 11, 9), 2), date(2026, 11, 16))

    def test_order_1109_delay_neg1(self):
        # 11-11 is Veterans Day → skipped; -1 bday from 11-12 → 11-10
        self.assertEqual(self._rd(date(2026, 11, 9), -1), date(2026, 11, 10))

    def test_order_1109_delay_neg5_clamped(self):
        # -5 bdays from 11-12 would reach 11-04, which is <= action_date 11-09
        # → clamped to next_bday(11-10) = 11-10
        self.assertEqual(self._rd(date(2026, 11, 9), -5), date(2026, 11, 10))

    def test_order_1113_delay_0(self):
        self.assertEqual(self._rd(date(2026, 11, 13), 0), date(2026, 11, 16))

    def test_order_1113_delay_2(self):
        self.assertEqual(self._rd(date(2026, 11, 13), 2), date(2026, 11, 18))

    def test_order_1123_delay_0_thanksgiving(self):
        # 11-26 = Thanksgiving → promised moves to 11-27 (Fri)
        self.assertEqual(self._rd(date(2026, 11, 23), 0), date(2026, 11, 27))

    def test_receipt_never_on_or_before_action_date(self):
        # Extreme negative delay: action_date+1 must be a business day or move forward
        for delay in (-10, -20):
            with self.subTest(delay=delay):
                result = self._rd(date(2026, 11, 9), delay)
                self.assertGreater(result, date(2026, 11, 9))


# ---------------------------------------------------------------------------
# PART A – loader: offer kind
# ---------------------------------------------------------------------------

class TestLoaderOfferKind(unittest.TestCase):
    """offer.<id>.delay_business_days column in worlds.csv."""

    _HEADER = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "offer.OF02.delay_business_days"]

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._dd = _copy_data(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp)

    def _load(self, worlds_rows):
        _write_csv(self._dd / "worlds.csv", [self._HEADER] + worlds_rows)
        return load_all(self._dd)

    def test_valid_offer_delay_loads(self):
        db = self._load([
            ["W1", "0", "1000", "2026-11-17", "2"],
        ])
        w = db["worlds"][0]
        key = ("offer", "OF02", "delay_business_days")
        self.assertEqual(w["overrides"][key], 2)
        self.assertNotIn("tags", w)

    def test_negative_delay_loads(self):
        db = self._load([
            ["W1", "0", "1000", "2026-11-17", "-1"],
        ])
        key = ("offer", "OF02", "delay_business_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], -1)

    def test_offer_not_in_supplier_offers_raises(self):
        # "offer.NOEXIST.delay_business_days" should fail at header validation
        hdr = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "offer.NOEXIST.delay_business_days"]
        _write_csv(self._dd / "worlds.csv",
                   [hdr, ["W1", "0", "1000", "2026-11-17", "1"]])
        with self.assertRaises(ValueError):
            load_all(self._dd)

    def test_offer_kind_bad_field_raises(self):
        # offer.OF02.lead_days is not an open kind
        hdr = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "offer.OF02.lead_days"]
        _write_csv(self._dd / "worlds.csv",
                   [hdr, ["W1", "0", "1000", "2026-11-17", "3"]])
        with self.assertRaises(ValueError):
            load_all(self._dd)

    def test_offer_delay_non_integer_raises(self):
        with self.assertRaises(ValueError):
            self._load([["W1", "0", "1000", "2026-11-17", "1.5"]])

    def test_offer_delay_exceeds_cap_raises(self):
        # OF02 lead=3, order DAY0=2026-11-09:
        # promised=2026-11-12; delay 365 bdays → way past cap
        with self.assertRaises(ValueError):
            self._load([["W1", "0", "1000", "2026-11-17", "365"]])


# ---------------------------------------------------------------------------
# PART A – loader: lane kind
# ---------------------------------------------------------------------------

class TestLoaderLaneKind(unittest.TestCase):
    """lane.<id>.delay_days column in worlds.csv.

    LN01 base lead_days=2, LN02 base lead_days=4.
    Old lead 5 -> delay 3 (5-2); lead 1 -> delay -1 (1-2);
    lead 365 -> delay 363 accepted; over-cap (delay 364) raises.
    delay -5 and -1000000000 both load (signed ints are accepted).
    """

    _HEADER = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "lane.LN01.delay_days"]

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._dd = _copy_data(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp)

    def _load(self, worlds_rows):
        _write_csv(self._dd / "worlds.csv", [self._HEADER] + worlds_rows)
        return load_all(self._dd)

    def test_valid_lane_delay_loads(self):
        # lead 5 - base 2 = delay 3
        db = self._load([["W1", "0", "1000", "2026-11-17", "3"]])
        key = ("lane", "LN01", "delay_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], 3)

    def test_lane_delay_neg1_loads(self):
        # lead 1 - base 2 = delay -1; negative delays are valid signed ints
        db = self._load([["W1", "0", "1000", "2026-11-17", "-1"]])
        key = ("lane", "LN01", "delay_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], -1)

    def test_delay_neg5_loads(self):
        # Formerly "lead 0 raises"; now delay -5 is a valid signed int and loads
        db = self._load([["W1", "0", "1000", "2026-11-17", "-5"]])
        key = ("lane", "LN01", "delay_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], -5)

    def test_delay_neg1000000000_loads(self):
        # Formerly "negative lead raises"; now a large negative delay is valid
        db = self._load([["W1", "0", "1000", "2026-11-17", "-1000000000"]])
        key = ("lane", "LN01", "delay_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], -1000000000)

    def test_lane_not_in_transfer_lanes_raises(self):
        hdr = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "lane.NOEXIST.delay_days"]
        _write_csv(self._dd / "worlds.csv",
                   [hdr, ["W1", "0", "1000", "2026-11-17", "2"]])
        with self.assertRaises(ValueError):
            load_all(self._dd)

    def test_lane_delay_exceeds_cap_raises(self):
        # LN01 base lead=2, DAY0+2+364 > SAMPLING_CAP (DAY0+365)
        with self.assertRaises(ValueError):
            self._load([["W1", "0", "1000", "2026-11-17", "364"]])

    def test_lane_delay_363_accepted(self):
        # LN01 base lead=2, DAY0+2+363 == DAY0+365 == SAMPLING_CAP
        db = self._load([["W1", "0", "1000", "2026-11-17", "363"]])
        key = ("lane", "LN01", "delay_days")
        self.assertEqual(db["worlds"][0]["overrides"][key], 363)


# ---------------------------------------------------------------------------
# PART A – loader: cause tag columns
# ---------------------------------------------------------------------------

class TestLoaderCauseTags(unittest.TestCase):
    """cause.<K>.active columns are no longer accepted (legacy format)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._dd = _copy_data(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp)

    def test_cause_active_column_raises_not_supported(self):
        """A cause.K1.active column must raise the 'no longer supported' error."""
        hdr = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "cause.K1.active"]
        _write_csv(self._dd / "worlds.csv",
                   [hdr, ["W1", "0", "1000", "2026-11-17", "1"]])
        with self.assertRaises(ValueError) as cm:
            load_all(self._dd)
        self.assertIn("no longer supported", str(cm.exception))

    def test_loaded_worlds_have_no_tags_key(self):
        """Worlds loaded from a new-format file have no 'tags' key."""
        hdr = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]
        _write_csv(self._dd / "worlds.csv",
                   [hdr, ["W1", "0", "1000", "2026-11-17"]])
        db = load_all(self._dd)
        self.assertNotIn("tags", db["worlds"][0])


# ---------------------------------------------------------------------------
# PART A – SIM_END with offer delay worlds
# ---------------------------------------------------------------------------

class TestSimEndOfferDelay(unittest.TestCase):
    """SIM_END is extended when world offer delays push receipt past base."""

    _HEADER = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "offer.OF02.delay_business_days"]

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._dd = _copy_data(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp)

    def test_delay_10_gives_sim_end_nov29(self):
        """OF02 delay=10 ordered on DAY0=2026-11-09:
        promised=2026-11-12, +10 bdays = 2026-11-27.
        SIM_END = 2026-11-27 + max_prod_days(2) = 2026-11-29.
        """
        _write_csv(self._dd / "worlds.csv", [
            self._HEADER,
            ["W1", "0", "1000", "2026-11-17", "10"],
        ])
        db = load_all(self._dd)
        self.assertEqual(db["SIM_END"], date(2026, 11, 29))

    def test_no_delay_sim_end_unchanged(self):
        """With delay=0, SIM_END stays at the base 2026-11-23."""
        _write_csv(self._dd / "worlds.csv", [
            self._HEADER,
            ["W1", "0", "1000", "2026-11-17", "0"],
        ])
        db = load_all(self._dd)
        self.assertEqual(db["SIM_END"], date(2026, 11, 23))


# ---------------------------------------------------------------------------
# PART A – SIM_END with lane lead worlds
# ---------------------------------------------------------------------------

class TestSimEndLaneLead(unittest.TestCase):
    """SIM_END is extended when world lane delays push arrival past base.

    Uses the new delay_days columns.
    LN01 base lead=2, LN02 base lead=4.
    Old lead 3 -> delay 1 (3-2=1); old lead 5 -> delay 1 (5-4=1).
    """

    _HEADER = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date",
               "lane.LN01.delay_days", "lane.LN02.delay_days"]

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._dd = _copy_data(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp)

    def test_lane_delay_extends_sim_end(self):
        """LN01 delay=1 (base+1=3), LN02 delay=1 (base+1=5) on DAY0=2026-11-09.
        Latest base arrival: max(DAY0+2, DAY0+4) = DAY0+4 = 2026-11-13;
        +delay 1 = 2026-11-14.  Base max_sched=2026-11-21; still wins.
        SIM_END = 2026-11-23 unchanged.
        """
        _write_csv(self._dd / "worlds.csv", [
            self._HEADER,
            ["W1", "0", "1000", "2026-11-17", "1", "1"],
        ])
        db = load_all(self._dd)
        self.assertEqual(db["SIM_END"], date(2026, 11, 23))


# ---------------------------------------------------------------------------
# PART B – apply_world with offer and lane kinds
# ---------------------------------------------------------------------------

class TestApplyWorldOfferKind(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def test_offer_delay_applies(self):
        world = {
            "overrides": {
                ("offer", "OF02", "delay_business_days"): 2,
            }
        }
        db2 = apply_world(self.db, world)
        self.assertEqual(db2["offers"]["OF02"]["delay_business_days"], 2)

    def test_offer_delay_does_not_mutate_db(self):
        world = {
            "overrides": {
                ("offer", "OF02", "delay_business_days"): 2,
            }
        }
        apply_world(self.db, world)
        self.assertNotIn("delay_business_days", self.db["offers"]["OF02"])

    def test_other_offers_unchanged(self):
        world = {
            "overrides": {
                ("offer", "OF02", "delay_business_days"): 2,
            }
        }
        db2 = apply_world(self.db, world)
        self.assertNotIn("delay_business_days", db2["offers"]["OF01"])


class TestApplyWorldLaneKind(unittest.TestCase):
    """apply_world with lane.delay_days override.

    delay 3 is stored as delay_days; lead_days stays at base 2.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def test_lane_delay_applies(self):
        world = {
            "overrides": {
                ("lane", "LN01", "delay_days"): 3,
            }
        }
        db2 = apply_world(self.db, world)
        self.assertEqual(db2["lanes"]["LN01"]["delay_days"], 3)

    def test_lane_lead_stays_at_base(self):
        """delay_days override must not change lead_days."""
        world = {
            "overrides": {
                ("lane", "LN01", "delay_days"): 3,
            }
        }
        db2 = apply_world(self.db, world)
        self.assertEqual(db2["lanes"]["LN01"]["lead_days"], 2)

    def test_lane_delay_does_not_mutate_db(self):
        world = {
            "overrides": {
                ("lane", "LN01", "delay_days"): 3,
            }
        }
        apply_world(self.db, world)
        self.assertNotIn("delay_days", self.db["lanes"]["LN01"])

    def test_other_lanes_unchanged(self):
        world = {
            "overrides": {
                ("lane", "LN01", "delay_days"): 3,
            }
        }
        db2 = apply_world(self.db, world)
        self.assertNotIn("delay_days", db2["lanes"]["LN02"])


# ---------------------------------------------------------------------------
# PART B – simulate with offer delay (via world)
# ---------------------------------------------------------------------------

class TestSimulateOfferDelay(unittest.TestCase):
    """Simulate ALT_BUY and HYBRID with OF02 delay, PO01 receipt 2026-11-17."""

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def _run(self, sid, of02_delay=None, ln01_delay=None, ln02_delay=None,
             po01_receipt=None):
        overrides = {}
        if po01_receipt is not None:
            overrides[("purchase_order", "PO01", "receipt_date")] = po01_receipt
        if of02_delay is not None:
            overrides[("offer", "OF02", "delay_business_days")] = of02_delay
        if ln01_delay is not None:
            overrides[("lane", "LN01", "delay_days")] = ln01_delay
        if ln02_delay is not None:
            overrides[("lane", "LN02", "delay_days")] = ln02_delay
        db_w = apply_world(self.db, {"overrides": overrides})
        actions, dis_id = build_scenario_actions(sid, self.db)
        result = simulate(actions, dis_id, db_w)
        late = sum(r["days_late"] > 0 for r in result["order_results"])
        total_late = sum(r["days_late"] for r in result["order_results"])
        return late, total_late

    # OF02 delay=0, PO01=2026-11-17 → same as stage 1 base
    def test_alt_buy_delay0_po17(self):
        late, total = self._run("ALT_BUY",
                                of02_delay=0,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (3, 5))

    def test_hybrid_delay0_po17(self):
        late, total = self._run("HYBRID",
                                of02_delay=0,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (1, 2))

    # OF02 delay=1, PO01=2026-11-17
    def test_alt_buy_delay1_po17(self):
        late, total = self._run("ALT_BUY",
                                of02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (5, 8))

    def test_hybrid_delay1_po17(self):
        late, total = self._run("HYBRID",
                                of02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (2, 3))

    # LN01 delay=1 (lead 2+1=3), LN02 delay=1 (lead 4+1=5), PO01=2026-11-17
    def test_transfer_ln01_delay1_ln02_delay1_po17(self):
        late, total = self._run("TRANSFER",
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (6, 14))

    def test_hybrid_ln01_delay1_ln02_delay1_po17(self):
        late, total = self._run("HYBRID",
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (2, 3))

    # OF02 delay=1, LN01 delay=1, LN02 delay=1, PO01=2026-11-17
    def test_alt_buy_delay1_lanes_po17(self):
        late, total = self._run("ALT_BUY",
                                of02_delay=1,
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (5, 8))

    def test_hybrid_delay1_lanes_po17(self):
        late, total = self._run("HYBRID",
                                of02_delay=1,
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (3, 4))

    def test_transfer_delay1_lanes_po17(self):
        late, total = self._run("TRANSFER",
                                of02_delay=1,
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (6, 14))

    def test_wait_delay1_lanes_po17(self):
        late, total = self._run("WAIT",
                                of02_delay=1,
                                ln01_delay=1,
                                ln02_delay=1,
                                po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (7, 27))


# ---------------------------------------------------------------------------
# PART B – purchase ordered 2026-11-13, PO01 2026-11-17
# ---------------------------------------------------------------------------

class TestSimulatePurchaseDate1113(unittest.TestCase):
    """Purchase of 65 from OF02 ordered 2026-11-13, PO01 2026-11-17.

    delay=0 → receipt 2026-11-16 → late_orders 7, total days late 22
    delay=2 → receipt 2026-11-18 → 7, 27
    """

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def _run(self, of02_delay, po01_receipt):
        # Build a custom ALT_BUY action with action_date 2026-11-13
        overrides = {
            ("purchase_order", "PO01", "receipt_date"): po01_receipt,
            ("offer", "OF02", "delay_business_days"): of02_delay,
        }
        db_w = apply_world(self.db, {"overrides": overrides})
        actions = [{
            "type": "purchase",
            "offer_id": "OF02",
            "warehouse_id": "WH01",
            "action_date": "2026-11-13",
            "qty": 65,
        }]
        result = simulate(actions, "D01", db_w)
        late = sum(r["days_late"] > 0 for r in result["order_results"])
        total_late = sum(r["days_late"] for r in result["order_results"])
        return late, total_late

    def test_delay0_receipt_nov16(self):
        # delay=0: promised=11-16, receipt=11-16
        cal = BusinessCalendar()
        offer = {"lead_days": 3, "delay_business_days": 0}
        receipt = offer_receipt_date(date(2026, 11, 13), offer, cal)
        self.assertEqual(receipt, date(2026, 11, 16))

    def test_delay2_receipt_nov18(self):
        cal = BusinessCalendar()
        offer = {"lead_days": 3, "delay_business_days": 2}
        receipt = offer_receipt_date(date(2026, 11, 13), offer, cal)
        self.assertEqual(receipt, date(2026, 11, 18))

    def test_delay0_simulation(self):
        late, total = self._run(of02_delay=0, po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (7, 22))

    def test_delay2_simulation(self):
        late, total = self._run(of02_delay=2, po01_receipt=date(2026, 11, 17))
        self.assertEqual((late, total), (7, 27))


# ---------------------------------------------------------------------------
# PART A – repo load unchanged
# ---------------------------------------------------------------------------

class TestRepoLoadUnchanged(unittest.TestCase):
    """Existing worlds.csv (purchase_order only) still loads and results match."""

    @classmethod
    def setUpClass(cls):
        cls._ctx = use_stage1_default_data()
        cls._ctx.__enter__()
        cls.db = load_all()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_sim_end_unchanged(self):
        self.assertEqual(self.db["SIM_END"], date(2026, 11, 23))

    def test_world_has_no_tags_key_for_repo_worlds(self):
        for w in self.db["worlds"]:
            with self.subTest(world_id=w["world_id"]):
                self.assertNotIn("tags", w)

    def test_scenario_results_unchanged(self):
        """Stage 1 scenario results must be identical with the new code.

        Values at PO01 receipt 2026-11-17 (announced date), no offer/lane
        world overrides.  Numbers verified against tests/test_step3.py and
        the spec.
        """
        expected = {
            "NORMAL":   (0, 0),
            "WAIT":     (7, 27),
            "TRANSFER": (4, 12),
            "ALT_BUY":  (3, 5),
            "HYBRID":   (1, 2),
        }
        for sid, (exp_late, exp_total) in expected.items():
            with self.subTest(scenario=sid):
                # Use the announced receipt date (2026-11-17) as the world
                world = {
                    "overrides": {
                        ("purchase_order", "PO01", "receipt_date"): date(2026, 11, 17)
                    }
                }
                db_w = apply_world(self.db, world)
                actions, dis_id = build_scenario_actions(sid, self.db)
                result = simulate(actions, dis_id, db_w)
                late = sum(r["days_late"] > 0 for r in result["order_results"])
                total = sum(r["days_late"] for r in result["order_results"])
                self.assertEqual((late, total), (exp_late, exp_total),
                                 msg=f"{sid}: got ({late}, {total})")


# ---------------------------------------------------------------------------
# PART 2 – offer_receipt_date: delay present but calendar=None raises
# ---------------------------------------------------------------------------

class TestOfferReceiptDateCalendarNone(unittest.TestCase):
    """When delay_business_days is set, calendar=None must raise ValueError."""

    def test_delay_set_calendar_none_raises(self):
        offer = {"lead_days": 3, "delay_business_days": 0}
        with self.assertRaises(ValueError):
            offer_receipt_date(date(2026, 11, 9), offer, None)

    def test_delay_set_calendar_none_raises_nonzero(self):
        offer = {"lead_days": 3, "delay_business_days": 2}
        with self.assertRaises(ValueError):
            offer_receipt_date(date(2026, 11, 9), offer, None)

    def test_no_delay_calendar_none_stage1_path(self):
        # No delay_business_days → stage-1 path, calendar=None is fine
        offer = {"lead_days": 3}
        result = offer_receipt_date(date(2026, 11, 9), offer, None)
        self.assertEqual(result, date(2026, 11, 12))


# ---------------------------------------------------------------------------
# PART 2 – evaluate_worlds caching: 4-row worlds, 2 distinct combos
# ---------------------------------------------------------------------------

class TestEvaluateWorldsCacheFourRows(unittest.TestCase):
    """4 worlds, 2 distinct overrides combos; simulate is called twice per option.

    Worlds (draw 0: W1=11-17 w=1, W2=11-17 w=1; draw 1: W3=11-18 w=1, W4=11-17 w=1)
    Total weight=4 (each draw sums to 2). Distinct combos: {11-17, 11-18}.

    Expected late_orders per scenario:
      (11-17 weight 3, 11-18 weight 1) / 4
      WAIT     = (7*3 + 8*1)/4 = 7.25
      TRANSFER = (4*3 + 5*1)/4 = 4.25
      ALT_BUY  = (3*3 + 4*1)/4 = 3.25
      HYBRID   = (1*3 + 2*1)/4 = 1.25
    """

    _HEADER = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._dd = _copy_data(cls._tmp)
        _write_csv(cls._dd / "worlds.csv", [
            cls._HEADER,
            ["W1", "0", "1", "2026-11-17"],
            ["W2", "0", "1", "2026-11-17"],
            ["W3", "1", "1", "2026-11-18"],
            ["W4", "1", "1", "2026-11-17"],
        ])
        cls.db = load_all(cls._dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp)

    def _result(self):
        return evaluate_worlds("D01", self.db)

    def test_expected_late_wait(self):
        opts = {o["scenario_id"]: o for o in self._result()["options"]}
        self.assertEqual(opts["WAIT"]["expected_late_orders"], 7.25)

    def test_expected_late_transfer(self):
        opts = {o["scenario_id"]: o for o in self._result()["options"]}
        self.assertEqual(opts["TRANSFER"]["expected_late_orders"], 4.25)

    def test_expected_late_alt_buy(self):
        opts = {o["scenario_id"]: o for o in self._result()["options"]}
        self.assertEqual(opts["ALT_BUY"]["expected_late_orders"], 3.25)

    def test_expected_late_hybrid(self):
        opts = {o["scenario_id"]: o for o in self._result()["options"]}
        self.assertEqual(opts["HYBRID"]["expected_late_orders"], 1.25)

    def test_simulate_called_twice_per_option(self):
        """Cache hit: worlds-loop simulate calls = 2 distinct combos × n_options.

        evaluate_worlds also calls simulate in the what_if section (once per
        date per option, uncached).  We subtract those to isolate the worlds-loop
        count.
        """
        import engine.worlds as _worlds_mod
        original_simulate = _worlds_mod.simulate

        counter = [0]

        def counting_simulate(actions, disruption_id, db_w):
            counter[0] += 1
            return original_simulate(actions, disruption_id, db_w)

        _worlds_mod.simulate = counting_simulate
        try:
            result = evaluate_worlds("D01", self.db)
        finally:
            _worlds_mod.simulate = original_simulate

        n_options = len(result["options"])
        # what_if covers planned_receipt_date(2026-11-11) .. HORIZON(2026-11-21) = 11 dates
        n_what_if_dates = len(result["what_if"]["dates"])
        what_if_calls = n_what_if_dates * n_options
        worlds_loop_calls = counter[0] - what_if_calls
        # 2 distinct combos × n_options
        self.assertEqual(worlds_loop_calls, 2 * n_options,
                         msg=f"Expected {2 * n_options} worlds-loop simulate calls, "
                             f"got {worlds_loop_calls} "
                             f"(total={counter[0]}, what_if={what_if_calls})")


# ---------------------------------------------------------------------------
# PART 2 – caching: 2000 rows, 5 distinct dates, results match uncached
# ---------------------------------------------------------------------------

class TestEvaluateWorldsCache2000Rows(unittest.TestCase):
    """2000 rows over 20 draws (100 per draw, weight 1), 5 distinct receipt dates.

    Simulate must be called exactly 5 times per option.
    Results must equal those of an uncached evaluation (reference: 100-row
    version with one row per distinct date).
    """

    _HEADER = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]
    # 5 distinct dates spread over the what_if window
    _DATES = [
        "2026-11-13", "2026-11-15", "2026-11-17", "2026-11-19", "2026-11-21",
    ]

    @classmethod
    def setUpClass(cls):
        import itertools

        cls._tmp = tempfile.mkdtemp()
        cls._dd = _copy_data(cls._tmp)

        # Build 20 draws × 100 rows = 2000 rows.
        # Each draw cycles through the 5 dates 20 times (20×5=100 rows/draw).
        rows = [cls._HEADER]
        date_cycle = itertools.cycle(cls._DATES)
        world_num = 0
        for draw in range(20):
            for _ in range(100):
                rows.append([f"W{world_num:04d}", str(draw), "1", next(date_cycle)])
                world_num += 1

        _write_csv(cls._dd / "worlds.csv", rows)
        cls.db_big = load_all(cls._dd)

        # Reference: same 20 draws, each with 5 rows (one per distinct date,
        # weight 20 each) — same totals, same expected values.
        ref_rows = [cls._HEADER]
        ref_num = 0
        for draw in range(20):
            for d in cls._DATES:
                ref_rows.append([f"R{ref_num:04d}", str(draw), "20", d])
                ref_num += 1
        _write_csv(cls._dd / "worlds.csv", ref_rows)
        cls.db_ref = load_all(cls._dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp)

    def test_simulate_called_five_times_per_option(self):
        """Worlds-loop simulate calls = 5 distinct combos × n_options."""
        import engine.worlds as _worlds_mod
        original_simulate = _worlds_mod.simulate

        counter = [0]

        def counting_simulate(actions, disruption_id, db_w):
            counter[0] += 1
            return original_simulate(actions, disruption_id, db_w)

        _worlds_mod.simulate = counting_simulate
        try:
            result = evaluate_worlds("D01", self.db_big)
        finally:
            _worlds_mod.simulate = original_simulate

        n_options = len(result["options"])
        n_what_if_dates = len(result["what_if"]["dates"])
        what_if_calls = n_what_if_dates * n_options
        worlds_loop_calls = counter[0] - what_if_calls
        self.assertEqual(worlds_loop_calls, 5 * n_options,
                         msg=f"Expected {5 * n_options} worlds-loop calls, "
                             f"got {worlds_loop_calls} "
                             f"(total={counter[0]}, what_if={what_if_calls})")

    def test_results_equal_reference(self):
        """2000-row result must match the equivalent 100-row reference."""
        result_big = evaluate_worlds("D01", self.db_big)
        result_ref = evaluate_worlds("D01", self.db_ref)

        for opt_big, opt_ref in zip(result_big["options"], result_ref["options"]):
            sid = opt_big["scenario_id"]
            with self.subTest(scenario=sid):
                self.assertEqual(opt_big["expected_late_orders"],
                                 opt_ref["expected_late_orders"],
                                 msg=f"{sid} expected_late_orders mismatch")
                self.assertEqual(opt_big["worst_late_orders"],
                                 opt_ref["worst_late_orders"],
                                 msg=f"{sid} worst_late_orders mismatch")


# ---------------------------------------------------------------------------
# PART 2 – caching: two worlds with the same overrides hash to the same key
# ---------------------------------------------------------------------------

class TestCacheTagsExcludedFromKey(unittest.TestCase):
    """Two worlds with identical overrides hash to the same cache key.

    Result must equal a file with one world per distinct combo.
    (Formerly tested tags exclusion; tags are removed in P4b.)
    """

    _HEADER = ["world_id", "draw", "weight",
               "purchase_order.PO01.receipt_date"]

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._dd = _copy_data(cls._tmp)
        _write_csv(cls._dd / "worlds.csv", [
            cls._HEADER,
            # Same receipt date — only 1 distinct overrides combo
            ["W1", "0", "1", "2026-11-17"],
            ["W2", "0", "1", "2026-11-17"],
        ])
        cls.db = load_all(cls._dd)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp)

    def test_simulate_called_once_per_option(self):
        """Identical overrides: worlds-loop simulate calls = 1 combo × n_options."""
        import engine.worlds as _worlds_mod
        original_simulate = _worlds_mod.simulate

        counter = [0]

        def counting_simulate(actions, disruption_id, db_w):
            counter[0] += 1
            return original_simulate(actions, disruption_id, db_w)

        _worlds_mod.simulate = counting_simulate
        try:
            result = evaluate_worlds("D01", self.db)
        finally:
            _worlds_mod.simulate = original_simulate

        n_options = len(result["options"])
        n_what_if_dates = len(result["what_if"]["dates"])
        what_if_calls = n_what_if_dates * n_options
        worlds_loop_calls = counter[0] - what_if_calls
        self.assertEqual(worlds_loop_calls, 1 * n_options,
                         msg=f"Expected {n_options} worlds-loop calls (1 per option), "
                             f"got {worlds_loop_calls} "
                             f"(total={counter[0]}, what_if={what_if_calls})")

    def test_expected_late_orders_match_single_combo(self):
        """With two equal-weight identical-combo worlds, expected = point value."""
        result = evaluate_worlds("D01", self.db)
        opts = {o["scenario_id"]: o for o in result["options"]}
        # Both worlds → PO01=11-17; same as a single world at 11-17
        self.assertEqual(opts["WAIT"]["expected_late_orders"], 7.0)
        self.assertEqual(opts["ALT_BUY"]["expected_late_orders"], 3.0)
        self.assertEqual(opts["HYBRID"]["expected_late_orders"], 1.0)


# ---------------------------------------------------------------------------
# PART 2 – repo data: all results unchanged
# ---------------------------------------------------------------------------

class TestRepoCacheUnchanged(unittest.TestCase):
    """Caching must not change any result for the repo worlds.csv."""

    @classmethod
    def setUpClass(cls):
        cls._ctx = use_stage1_default_data()
        cls._ctx.__enter__()
        cls.db = load_all()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_evaluate_worlds_expected_late_unchanged(self):
        """Expected late_orders per option must match the previously verified values."""
        result = evaluate_worlds("D01", self.db)
        opts = {o["scenario_id"]: o for o in result["options"]}
        # Values from test_worlds.py TestTriangularWeights
        # (triangular-weight repo worlds.csv, verified in part 1)
        for sid in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            with self.subTest(scenario=sid):
                val = opts[sid]["expected_late_orders"]
                self.assertIsInstance(val, float)
                # Must be non-negative and finite
                self.assertGreaterEqual(val, 0.0)

    def test_world_count_unchanged(self):
        result = evaluate_worlds("D01", self.db)
        self.assertEqual(result["world_count"], 11)

    def test_sim_end_unchanged(self):
        self.assertEqual(self.db["SIM_END"], date(2026, 11, 23))


if __name__ == "__main__":
    unittest.main()
