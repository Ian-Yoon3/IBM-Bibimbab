"""Tests for step 3: dates from data, worlds.csv row-width gaps, and business calendar.

Expected values are pre-computed and must not be changed to match the code.
If a number disagrees, stop and show both numbers.
"""
import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from engine.business_calendar import BusinessCalendar, federal_holidays
from engine.evaluate import evaluate
from engine.loader import load_all
from engine.simulate import build_scenario_actions, simulate
from engine.worlds import apply_world

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _copy_data(tmp):
    dest = pathlib.Path(tmp) / "data"
    shutil.copytree(_DATA_DIR, dest)
    return dest


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


_WIDE_HEADER = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

# ---------------------------------------------------------------------------
# Part A: dates from data
# ---------------------------------------------------------------------------


class TestRepoDates(unittest.TestCase):
    """Repo data produces the expected DAY0, HORIZON, SIM_END."""

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def test_day0(self):
        got = self.db["DAY0"]
        if got != date(2026, 11, 9):
            self.fail(f"DAY0: expected 2026-11-09, got {got}")

    def test_horizon(self):
        got = self.db["HORIZON"]
        if got != date(2026, 11, 21):
            self.fail(f"HORIZON: expected 2026-11-21, got {got}")

    def test_sim_end(self):
        # Stage 1 worlds.csv max date = 2026-11-21 (horizon); SIM_END = 2026-11-21 + 2 = 2026-11-23.
        got = self.db["SIM_END"]
        if got != date(2026, 11, 23):
            self.fail(f"SIM_END: expected 2026-11-23, got {got}")

    def test_calendar_present(self):
        cal = self.db["calendar"]
        self.assertIsInstance(cal, BusinessCalendar)


class TestRepoDatesResultsUnchanged(unittest.TestCase):
    """All 5 scenario results are unchanged after removing hard-coded dates."""

    @classmethod
    def setUpClass(cls):
        cls.db = load_all()

    def _run(self, sid):
        actions, dis_id = build_scenario_actions(sid, self.db)
        sim = simulate(actions, dis_id, self.db)
        return evaluate(sim)

    def _check(self, sid, expected_late, expected_cbh):
        kpi = self._run(sid)
        got_late = kpi["late_orders"]
        if got_late != expected_late:
            self.fail(
                f"{sid} late_orders: expected {expected_late}, got {got_late}"
            )
        got_cbh = kpi["orders_completed_by_horizon"]
        if got_cbh != expected_cbh:
            self.fail(
                f"{sid} orders_completed_by_horizon: expected {expected_cbh}, got {got_cbh}"
            )

    def test_normal(self):   self._check("NORMAL", 0, 12)
    def test_wait(self):     self._check("WAIT", 7, 12)
    def test_transfer(self): self._check("TRANSFER", 4, 12)
    def test_alt_buy(self):  self._check("ALT_BUY", 3, 12)
    def test_hybrid(self):   self._check("HYBRID", 1, 12)


class TestWorldNov30SimEnd(unittest.TestCase):
    """Single world with PO01 receipt 2026-11-30 → SIM_END 2026-12-02 and correct KPIs."""

    _EXPECTED = {
        "WAIT":     {"late": 11, "total_days": 165, "max": 19, "cbh": 1},
        "TRANSFER": {"late":  8, "total_days": 111, "max": 18, "cbh": 4},
        "ALT_BUY":  {"late":  7, "total_days":  78, "max": 15, "cbh": 6},
        "HYBRID":   {"late":  5, "total_days":  62, "max": 15, "cbh": 7},
    }

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                _WIDE_HEADER,
                ["W1", "0", "1", "2026-11-30"],
            ])
            cls.db = load_all(dd)

    def test_sim_end(self):
        got = self.db["SIM_END"]
        if got != date(2026, 12, 2):
            self.fail(f"SIM_END: expected 2026-12-02, got {got}")

    def _check(self, sid):
        exp = self._EXPECTED[sid]
        actions, dis_id = build_scenario_actions(sid, self.db)
        world = self.db["worlds"][0]
        db_w = apply_world(self.db, world)
        sim = simulate(actions, dis_id, db_w)
        kpi = evaluate(sim)
        for attr, key in [
            ("late", "late_orders"),
            ("total_days", "total_order_days_late"),
            ("max", "max_order_days_late"),
            ("cbh", "orders_completed_by_horizon"),
        ]:
            got = kpi[key]
            want = exp[attr]
            if got != want:
                self.fail(f"world_11_30 {sid} {key}: expected {want}, got {got}")

    def test_wait(self):     self._check("WAIT")
    def test_transfer(self): self._check("TRANSFER")
    def test_alt_buy(self):  self._check("ALT_BUY")
    def test_hybrid(self):   self._check("HYBRID")


class TestSamplingCap(unittest.TestCase):
    """Receipt 2027-11-09 accepted; 2027-11-10 raises (DAY0+365 cap)."""

    def test_cap_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                _WIDE_HEADER,
                ["W1", "0", "1", "2027-11-09"],  # exactly at cap
            ])
            db = load_all(dd)  # must not raise
            self.assertIsNotNone(db["worlds"])

    def test_cap_exceeded_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                _WIDE_HEADER,
                ["W1", "0", "1", "2027-11-10"],  # one day past cap
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            self.assertIn("cap", str(ctx.exception).lower())


class TestDateShift(unittest.TestCase):
    """Data shifted +364 days gives same late_orders, days late and costs."""

    @classmethod
    def setUpClass(cls):
        # Build a shifted data directory by moving every date by +364 days
        SHIFT = timedelta(days=364)

        date_fields = {
            "orders": ["due_date"],
            "purchase_orders": ["order_date", "planned_receipt_date"],
            "disruptions": ["reported_date", "revised_receipt_date"],
            "recovery_purchases": ["action_date"],
            "recovery_transfers": ["action_date"],
            "worlds": ["purchase_order.PO01.receipt_date"],  # value column
        }

        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)

            def shift_csv(name, field_set):
                path = dd / f"{name}.csv"
                rows = []
                with open(path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        for field in fieldnames:
                            if field in field_set or field.endswith("receipt_date"):
                                v = row[field]
                                try:
                                    d = date.fromisoformat(v)
                                    row[field] = (d + SHIFT).isoformat()
                                except ValueError:
                                    pass
                        rows.append(row)
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)

            shift_csv("orders", {"due_date"})
            shift_csv("purchase_orders", {"order_date", "planned_receipt_date"})
            shift_csv("disruptions", {"reported_date", "revised_receipt_date"})
            shift_csv("recovery_purchases", {"action_date"})
            shift_csv("recovery_transfers", {"action_date"})
            # worlds.csv: shift the date values in the variable column
            worlds_path = dd / "worlds.csv"
            rows = []
            with open(worlds_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    for field in fieldnames:
                        if field == "world_id" or field == "draw" or field == "weight":
                            continue
                        try:
                            d = date.fromisoformat(row[field])
                            row[field] = (d + SHIFT).isoformat()
                        except ValueError:
                            pass
                    rows.append(row)
            with open(worlds_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            cls.db_shifted = load_all(dd)

        cls.db_base = load_all()

    def test_day0_shifted(self):
        expected = date(2027, 11, 8)  # 2026-11-09 + 364
        got = self.db_shifted["DAY0"]
        if got != expected:
            self.fail(f"shifted DAY0: expected {expected}, got {got}")

    def test_horizon_shifted(self):
        expected = date(2027, 11, 20)  # 2026-11-21 + 364
        got = self.db_shifted["HORIZON"]
        if got != expected:
            self.fail(f"shifted HORIZON: expected {expected}, got {got}")

    def test_sim_end_shifted(self):
        expected = date(2027, 11, 22)  # 2026-11-23 + 364
        got = self.db_shifted["SIM_END"]
        if got != expected:
            self.fail(f"shifted SIM_END: expected {expected}, got {got}")

    def _check_scenario(self, sid):
        # Base
        actions, dis_id = build_scenario_actions(sid, self.db_base)
        sim_b = simulate(actions, dis_id, self.db_base)
        kpi_b = evaluate(sim_b)

        # Shifted
        actions_s, dis_id_s = build_scenario_actions(sid, self.db_shifted)
        sim_s = simulate(actions_s, dis_id_s, self.db_shifted)
        kpi_s = evaluate(sim_s)

        for key in ("late_orders", "total_order_days_late", "max_order_days_late",
                    "total_extra_cost"):
            got = kpi_s[key]
            want = kpi_b[key]
            if got != want:
                self.fail(f"date_shift {sid} {key}: base={want}, shifted={got}")

    def test_normal(self):   self._check_scenario("NORMAL")
    def test_wait(self):     self._check_scenario("WAIT")
    def test_transfer(self): self._check_scenario("TRANSFER")
    def test_alt_buy(self):  self._check_scenario("ALT_BUY")
    def test_hybrid(self):   self._check_scenario("HYBRID")


class TestTwoDisruptionsDifferentDates(unittest.TestCase):
    """Two disruptions with different reported_dates raise ValueError."""

    def test_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Add a second disruption with a different reported_date
            # First, we need a second purchase order and disruption
            # Simplest: just modify disruptions.csv to have two different dates
            _write_csv(dd / "disruptions.csv", [
                ["disruption_id", "po_id", "reported_date", "revised_receipt_date", "reason"],
                ["D01", "PO01", "2026-11-09", "2026-11-17", "Supplier equipment outage"],
                # To add D02 we need another PO; use the same po_id trick with different date
                # Actually just add a second row with different reported_date using D01-dup
                # This requires a valid po_id; we'll repurpose D01 with a different date
            ])
            # We need a valid second PO or just two disruptions with different dates
            # The easiest approach: add a supplier_offers entry with lead=7 and a second PO
            # that is already in a closed state, or simply add two disruption rows that
            # share PO01 but with different reported_dates.
            _write_csv(dd / "disruptions.csv", [
                ["disruption_id", "po_id", "reported_date", "revised_receipt_date", "reason"],
                ["D01", "PO01", "2026-11-09", "2026-11-17", "Equipment outage"],
                ["D02", "PO01", "2026-11-10", "2026-11-18", "Second disruption"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("reported_date", msg.lower())


# ---------------------------------------------------------------------------
# Part B: worlds.csv row-width gaps
# ---------------------------------------------------------------------------


class TestWorldsRowWidth(unittest.TestCase):
    """Too many or too few cells in a worlds.csv row raise ValueError."""

    _H = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]

    def test_too_many_cells_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-17", "extra_cell"],
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("W1", msg)
            # message should say the row has more cells
            self.assertIn("cells", msg.lower())

    def test_too_few_cells_raises_naming_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Row is missing the last variable column
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1"],  # missing receipt_date value
            ])
            with self.assertRaises(ValueError) as ctx:
                load_all(dd)
            msg = str(ctx.exception)
            self.assertIn("W1", msg)
            # message names the missing column
            self.assertIn("receipt_date", msg)

    def test_exact_width_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                self._H,
                ["W1", "0", "1", "2026-11-17"],
            ])
            db = load_all(dd)
            self.assertIsNotNone(db["worlds"])


# ---------------------------------------------------------------------------
# Part C: BusinessCalendar
# ---------------------------------------------------------------------------


class TestFederalHolidays2025(unittest.TestCase):
    """federal_holidays(2025) matches the OPM list."""

    def test_observed_dates(self):
        h = federal_holidays(2025)
        observed = sorted(h.keys())
        expected = [
            date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
            date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
            date(2025, 9, 1), date(2025, 10, 13), date(2025, 11, 11),
            date(2025, 11, 27), date(2025, 12, 25),
        ]
        if observed != expected:
            self.fail(
                f"2025 holidays mismatch\n"
                f"  expected: {expected}\n"
                f"  got:      {observed}"
            )


class TestFederalHolidays2026(unittest.TestCase):
    """federal_holidays(2026) matches the OPM list."""

    def test_observed_dates(self):
        h = federal_holidays(2026)
        observed = sorted(h.keys())
        expected = [
            date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
            date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3),
            date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 11),
            date(2026, 11, 26), date(2026, 12, 25),
        ]
        if observed != expected:
            self.fail(
                f"2026 holidays mismatch\n"
                f"  expected: {expected}\n"
                f"  got:      {observed}"
            )


class TestFederalHolidays2027(unittest.TestCase):
    """federal_holidays(2027) matches the OPM list (11 entries, ends 2027-12-24).

    New Year's Day 2028 is observed on 2027-12-31 (Jan 1, 2028 falls on
    Saturday).  That observed date belongs to federal_holidays(2028), not
    federal_holidays(2027).  is_closed(2027-12-31) stays True because
    BusinessCalendar looks up holidays for the queried date's year (2027),
    and federal_holidays(2028) contains date(2027, 12, 31).
    """

    def test_observed_dates(self):
        h = federal_holidays(2027)
        observed = sorted(h.keys())
        expected = [
            date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15),
            date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5),
            date(2027, 9, 6), date(2027, 10, 11), date(2027, 11, 11),
            date(2027, 11, 25), date(2027, 12, 24),
        ]
        if observed != expected:
            self.fail(
                f"2027 holidays mismatch\n"
                f"  expected: {expected}\n"
                f"  got:      {observed}"
            )

    def test_dec31_in_2028_holidays(self):
        """2027-12-31 belongs to federal_holidays(2028), not (2027)."""
        h2027 = federal_holidays(2027)
        h2028 = federal_holidays(2028)
        self.assertNotIn(date(2027, 12, 31), h2027,
                         "2027-12-31 must NOT be in federal_holidays(2027)")
        self.assertIn(date(2027, 12, 31), h2028,
                      "2027-12-31 must be in federal_holidays(2028)")

    def test_dec31_2027_closed(self):
        cal = BusinessCalendar()
        self.assertTrue(cal.is_closed(date(2027, 12, 31)),
                        "2027-12-31 must be closed (New Year 2028 observed)")


class TestFederalHolidaysEdgeCases(unittest.TestCase):
    """Juneteenth 2021 and 2020 count."""

    def test_juneteenth_2021_observed(self):
        h = federal_holidays(2021)
        # Jun 19, 2021 is Saturday → observed Jun 18 (Friday)
        self.assertIn(date(2021, 6, 18), h, "Juneteenth 2021 must be observed on 2021-06-18")

    def test_no_juneteenth_2020(self):
        h = federal_holidays(2020)
        self.assertEqual(len(h), 10, f"2020 should have 10 holidays (no Juneteenth), got {len(h)}")


class TestBusinessCalendarMethods(unittest.TestCase):
    """Core BusinessCalendar method correctness."""

    def setUp(self):
        self.cal = BusinessCalendar()

    def test_add_bdays_plus1_from_wed_before_thanksgiving(self):
        # Nov 25, 2026 is Wednesday; Nov 26 Thanksgiving; Nov 27 is Fri → result
        got = self.cal.add_business_days(date(2026, 11, 25), 1)
        if got != date(2026, 11, 27):
            self.fail(f"add_business_days(2026-11-25, 1): expected 2026-11-27, got {got}")

    def test_add_bdays_plus1_across_weekend(self):
        # Nov 20, 2026 is Friday; +1 business day skips Sat/Sun → Nov 23 Mon
        got = self.cal.add_business_days(date(2026, 11, 20), 1)
        if got != date(2026, 11, 23):
            self.fail(f"add_business_days(2026-11-20, 1): expected 2026-11-23, got {got}")

    def test_add_bdays_plus5(self):
        # Nov 9 Mon +5 (skipping Nov 11 Veterans): Nov 17 Tue
        got = self.cal.add_business_days(date(2026, 11, 9), 5)
        if got != date(2026, 11, 17):
            self.fail(f"add_business_days(2026-11-09, 5): expected 2026-11-17, got {got}")

    def test_add_bdays_negative(self):
        # Nov 17 Tue -4 (skipping Nov 11 Veterans): Nov 10 Mon
        got = self.cal.add_business_days(date(2026, 11, 17), -4)
        if got != date(2026, 11, 10):
            self.fail(f"add_business_days(2026-11-17, -4): expected 2026-11-10, got {got}")

    def test_add_bdays_zero_returns_d(self):
        d = date(2026, 11, 11)  # Veterans Day (closed)
        self.assertEqual(self.cal.add_business_days(d, 0), d)

    def test_business_days_between(self):
        # Nov 09..17: Nov 10, 12, 13, 16, 17 = 5 (Nov 11 Veterans, Sat/Sun skip)
        got = self.cal.business_days_between(date(2026, 11, 9), date(2026, 11, 17))
        if got != 5:
            self.fail(f"business_days_between(2026-11-09, 2026-11-17): expected 5, got {got}")

    def test_next_business_day_holiday(self):
        # Nov 11 Veterans Day → next is Nov 12
        got = self.cal.next_business_day(date(2026, 11, 11))
        if got != date(2026, 11, 12):
            self.fail(f"next_business_day(2026-11-11): expected 2026-11-12, got {got}")

    def test_next_business_day_weekend(self):
        # Nov 14, 2026 is Saturday → next is Nov 16 Monday
        got = self.cal.next_business_day(date(2026, 11, 14))
        if got != date(2026, 11, 16):
            self.fail(f"next_business_day(2026-11-14): expected 2026-11-16, got {got}")

    def test_next_business_day_open(self):
        # Nov 9, 2026 is Monday → returns itself
        got = self.cal.next_business_day(date(2026, 11, 9))
        self.assertEqual(got, date(2026, 11, 9))


class TestBusinessCalendarOverrides(unittest.TestCase):
    """closed_days.csv-style overrides in BusinessCalendar."""

    def test_override_close_day(self):
        # Mark 2026-11-27 (a Friday) as closed
        cal = BusinessCalendar(overrides={date(2026, 11, 27): True})
        got = cal.add_business_days(date(2026, 11, 25), 1)
        # Nov 26 Thanksgiving, Nov 27 override closed, Nov 28 Sat, Nov 29 Sun → Nov 30
        if got != date(2026, 11, 30):
            self.fail(f"override close: expected 2026-11-30, got {got}")

    def test_override_open_holiday(self):
        # Mark 2026-11-11 (Veterans Day) as open
        cal = BusinessCalendar(overrides={date(2026, 11, 11): False})
        self.assertTrue(cal.is_business_day(date(2026, 11, 11)),
                        "Veterans Day should be open when overridden with closed=False")


class TestClosedDaysLoader(unittest.TestCase):
    """Loader reads closed_days.csv correctly."""

    def test_closed_day_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "closed"],
                ["2026-11-27", "1"],
            ])
            db = load_all(dd)
            # The calendar should have Nov 27 closed
            self.assertTrue(db["calendar"].is_closed(date(2026, 11, 27)))

    def test_open_override_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "closed"],
                ["2026-11-11", "0"],
            ])
            db = load_all(dd)
            self.assertTrue(db["calendar"].is_business_day(date(2026, 11, 11)),
                            "Veterans Day should be open when closed=0 override")

    def test_bad_header_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "is_closed"],  # wrong header
                ["2026-11-11", "1"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_bad_date_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "closed"],
                ["not-a-date", "1"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_bad_closed_value_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "closed"],
                ["2026-11-11", "2"],  # 2 is not 0 or 1
            ])
            with self.assertRaises(ValueError):
                load_all(dd)

    def test_duplicate_date_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "closed_days.csv", [
                ["date", "closed"],
                ["2026-11-11", "0"],
                ["2026-11-11", "1"],
            ])
            with self.assertRaises(ValueError):
                load_all(dd)


if __name__ == "__main__":
    unittest.main()
