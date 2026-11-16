"""The Monte Carlo engine on data sets other than the demo (docs/montecarlo-engine.md, section 10).

Every case copies data/ to a temporary folder, changes it, and runs the whole
chain: estimate -> sample_worlds -> worlds.csv in the copy -> load_all ->
evaluate_worlds for every disruption. The real data/ is never touched.

Expected values are computed by hand from the closed forms of section 7.1.
"""

import csv
import pathlib
import re
import shutil
import tempfile
import time
import unittest
from datetime import date, timedelta
from unittest import mock

from engine.loader import load_all
from engine.simulate import offer_receipt_date
from engine.worlds import evaluate_worlds
from montecarlo import sample as sample_mod
from montecarlo.estimate import estimate
from montecarlo.sample import sample_worlds

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _append(path, line):
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\n")


def _map_text(folder, fn):
    for p in folder.rglob("*.csv"):
        p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")


def _shift_dates(days):
    def fn(text):
        return re.sub(
            r"\d{4}-\d{2}-\d{2}",
            lambda m: (date.fromisoformat(m.group()) + timedelta(days=days)).isoformat(),
            text,
        )
    return fn


def _counts(est, key):
    v = est["variables"][key]
    return (v["records"], v["n_early"], v["n_ontime"], v["n_late"])


class _VariantCase(unittest.TestCase):
    """Base class: one temporary copy of data/ per test."""

    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())
        self.d = self._tmp / "data"
        shutil.copytree(DATA_DIR, self.d)
        self.h = self.d / "history"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def run_chain(self, M=50, N=40, seed=7):
        """Run the whole chain and return (est, worlds, meta, results)."""
        est = estimate(self.d)
        worlds, meta = sample_worlds(est, load_all(self.d), M, N, seed, "lhs")
        cols = ["world_id", "draw", "weight"] + [
            c for c in worlds[0] if c not in ("world_id", "draw", "weight")
        ]
        _write(self.d / "worlds.csv", worlds, cols)
        db = load_all(self.d)
        results = {did: evaluate_worlds(did, db) for did in db["disruptions"]}
        return est, worlds, meta, results


# ---------------------------------------------------------------------------
# Data sets that must run
# ---------------------------------------------------------------------------

class TestVariantsRun(_VariantCase):

    def test_v01_renamed_ids_and_dates_two_years_later(self):
        ren = {"PO01": "PA77", "OF01": "OQ3", "OF02": "OX9", "LN01": "LZ1",
               "LN02": "LY2", "K1": "GATE", "K2": "ROAD", "D01": "DX5"}

        def fn(text):
            text = _shift_dates(728)(text)   # 104 weeks, same weekdays
            for a, b in ren.items():
                text = re.sub(r"\b" + a, b, text)
            return text
        _map_text(self.d, fn)
        est, _, _, results = self.run_chain()
        self.assertEqual(_counts(est, "purchase_order.PA77"), (12, 4, 0, 8))
        self.assertEqual(_counts(est, "offer.OX9"), (6, 1, 3, 2))
        self.assertEqual(_counts(est, "lane.LZ1"), (15, 1, 10, 4))
        self.assertEqual(_counts(est, "lane.LY2"), (10, 0, 6, 4))
        self.assertAlmostEqual(est["causes"]["GATE"]["p_active"], 0.083070, places=6)
        self.assertAlmostEqual(est["causes"]["ROAD"]["p_active"], 0.083501, places=6)
        self.assertIn("DX5", results)

    def test_v02_two_variables_share_one_source(self):
        _append(self.h / "causes.csv", "K1,business,offer,OF01")
        est, _, _, _ = self.run_chain()
        self.assertEqual(_counts(est, "purchase_order.PO01"), (12, 4, 0, 8))
        self.assertEqual(_counts(est, "offer.OF01"), (12, 4, 0, 8))

    def test_v03_one_cause_only(self):
        _write(self.h / "causes.csv",
               [r for r in _read(self.h / "causes.csv") if r["cause_id"] == "K1"])
        _write(self.h / "episodes.csv",
               [r for r in _read(self.h / "episodes.csv") if r["cause_id"] == "K1"])
        _write(self.h / "shipments.csv",
               [r for r in _read(self.h / "shipments.csv")
                if r["source_id"] in ("OF01", "OF02")])
        _, worlds, _, _ = self.run_chain()
        value_cols = [c for c in worlds[0] if c not in ("world_id", "draw", "weight")]
        self.assertEqual(value_cols, ["purchase_order.PO01.receipt_date",
                                      "offer.OF02.delay_business_days",
                                      "cause.K1.active"])

    def test_v04_cause_with_no_episodes(self):
        _write(self.h / "episodes.csv",
               [r for r in _read(self.h / "episodes.csv") if r["cause_id"] != "K1"])
        rows = _read(self.h / "shipments.csv")
        for r in rows:
            if r["episode_id"].startswith("K1"):
                r["episode_id"] = ""
        _write(self.h / "shipments.csv", rows)
        est, _, _, _ = self.run_chain()
        # 1 - (1 + 8/365)^-1
        self.assertAlmostEqual(est["causes"]["K1"]["p_active"], 0.021448, places=6)

    def test_v05_source_with_no_records(self):
        _write(self.h / "shipments.csv",
               [r for r in _read(self.h / "shipments.csv") if r["source_id"] != "LN02"])
        est, _, _, _ = self.run_chain()
        self.assertEqual(_counts(est, "lane.LN02"), (0, 0, 0, 0))
        self.assertEqual(est["variables"]["lane.LN02"]["prior_share"], 1.0)

    def _check_k2_certain(self):
        est, worlds, _, _ = self.run_chain()
        self.assertEqual(est["causes"]["K2"]["p_active"], 1.0)
        self.assertTrue(all(w["cause.K2.active"] == "1" for w in worlds))

    def test_v06a_episode_open_with_empty_end(self):
        _append(self.h / "episodes.csv", "K2E999,K2,2026-11-08,,2")
        self._check_k2_certain()

    def test_v06b_episode_ending_after_decision_day(self):
        _append(self.h / "episodes.csv", "K2E999,K2,2026-11-08,2026-11-11,2")
        self._check_k2_certain()

    def test_v07_third_cause_on_an_unused_offer(self):
        _append(self.h / "causes.csv", "K3,business,offer,OF03")
        est, _, _, _ = self.run_chain()
        # w = 2026-11-09 to 2026-11-16 (11-14 is a Saturday) = 7 days. 1 - (1 + 7/365)^-1
        self.assertAlmostEqual(est["causes"]["K3"]["p_active"], 0.018817, places=6)

    def test_v08_decision_day_on_a_saturday(self):
        _map_text(self.d, _shift_dates(5))
        _, _, _, results = self.run_chain()
        self.assertEqual(load_all(self.d)["DAY0"].weekday(), 5)
        self.assertIn("D01", results)

    def test_v09_second_disruption(self):
        _append(self.d / "purchase_orders.csv", "PO02,OF03,WH01,2026-11-05,50,2026-11-10")
        _append(self.d / "disruptions.csv", "D02,PO02,2026-11-09,2026-11-13,test")
        _append(self.h / "causes.csv", "K1,business,purchase_order,PO02")
        _, worlds, _, results = self.run_chain()
        self.assertIn("purchase_order.PO02.receipt_date", worlds[0])
        self.assertEqual(set(results), {"D01", "D02"})

    def test_v12_history_of_two_years(self):
        (self.h / "period.csv").write_text(
            "start_date,end_date\n2024-11-09,2026-11-08\n", encoding="utf-8")
        est, _, _, _ = self.run_chain()
        # T = 730. 1 - (1 + 8/730)^-4 and 1 - (1 + 4/730)^-8
        self.assertAlmostEqual(est["causes"]["K1"]["p_active"], 0.042660, places=6)
        self.assertAlmostEqual(est["causes"]["K2"]["p_active"], 0.042774, places=6)


# ---------------------------------------------------------------------------
# Inputs that must stop with an error naming the problem
# ---------------------------------------------------------------------------

class TestVariantsReject(_VariantCase):

    def _assert_error(self, *words):
        with self.assertRaises(ValueError) as ctx:
            estimate(self.d)
        msg = str(ctx.exception)
        for w in words:
            self.assertIn(w, msg)

    def test_e1_offer_with_calendar_days(self):
        _append(self.h / "causes.csv", "K3,calendar,offer,OF03")
        self._assert_error("business", "OF03")

    def test_e2_source_in_two_causes(self):
        _append(self.d / "purchase_orders.csv", "PO02,OF02,WH01,2026-11-07,20,2026-11-10")
        _append(self.d / "disruptions.csv", "D02,PO02,2026-11-09,2026-11-13,test")
        _append(self.h / "causes.csv", "K3,business,purchase_order,PO02")
        self._assert_error("OF02", "K1", "K3")

    def test_e3_repeated_row(self):
        _append(self.h / "causes.csv", "K2,calendar,lane,LN01")
        self._assert_error("LN01", "more than once")

    def test_e4_no_period_file(self):
        (self.h / "period.csv").unlink()
        self._assert_error("period.csv")

    def test_e5_episode_starting_after_decision_day(self):
        _append(self.h / "episodes.csv", "K2E998,K2,2026-11-10,2026-11-11,1")
        self._assert_error("K2E998")


# ---------------------------------------------------------------------------
# Extreme tail values stay fast and give the bounded result
# ---------------------------------------------------------------------------

class TestExtremeTails(_VariantCase):

    def test_offer_far_early_is_floored_at_once(self):
        cal = load_all(DATA_DIR)["calendar"]
        offer = {"lead_days": 3, "delay_business_days": -10**9}
        t0 = time.monotonic()
        got = offer_receipt_date(date(2026, 11, 9), offer, cal)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(got, date(2026, 11, 10))

    def test_huge_shocks_and_early_values_run_end_to_end(self):
        # Every severity is 10^9 days and every cause is active: receipts and
        # leads are cut at the cap, offer delays at their cap.
        rows = _read(self.h / "episodes.csv")
        rows.append({"episode_id": "K1E999", "cause_id": "K1", "start_date": "2026-11-08",
                     "end_date": "", "delay_days": "1"})
        rows.append({"episode_id": "K2E999", "cause_id": "K2", "start_date": "2026-11-08",
                     "end_date": "", "delay_days": "1"})
        _write(self.h / "episodes.csv", rows)
        with mock.patch.object(sample_mod, "_inv_severity", return_value=10**9):
            t0 = time.monotonic()
            _, worlds, meta, _ = self.run_chain(M=2, N=5)
            self.assertLess(time.monotonic() - t0, 60)
        for w in worlds:
            self.assertEqual(w["purchase_order.PO01.receipt_date"], "2027-11-09")
            self.assertEqual(w["offer.OF02.delay_business_days"], "248")
            self.assertEqual(w["lane.LN01.lead_days"], "365")
        self.assertEqual(meta["cut_count"], 2 * 5 * 4)

    def test_huge_early_values_run_end_to_end(self):
        with mock.patch.object(sample_mod, "_inv_own_delay", return_value=-10**9):
            t0 = time.monotonic()
            _, worlds, meta, _ = self.run_chain(M=2, N=5)
            self.assertLess(time.monotonic() - t0, 60)
        for w in worlds:
            self.assertEqual(w["purchase_order.PO01.receipt_date"], "2026-11-12")
            self.assertEqual(w["lane.LN02.lead_days"], "1")
        self.assertEqual(meta["raised_count"], 2 * 5)


if __name__ == "__main__":
    unittest.main()
