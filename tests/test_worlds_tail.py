"""Tests for the new tail/range/ranking summary values added in step 6b-1a.

Known answers (computed independently from data):
  A. Stage 1 (triangular weights, one draw): tail_mean, average_range null, ranking null.
  B. Announced-date fallback (no worlds.csv): tail_mean = that world's late orders.
  C. Hand-made worlds (10 worlds, weights 1..5 x 2 draws, same dates both draws):
     boundary cut in tail, average_range, ranking.
  D. evaluate_run equals evaluate_worlds for all keys including the new ones.
  E. Ranking with two draws where both draws disagree with global order.
"""

import csv
import pathlib
import shutil
import tempfile
import unittest
from fractions import Fraction

from engine.loader import load_all
from engine.worlds import evaluate_worlds
from montecarlo.run import build_run
import engine.runs

from scripts.stage1_data import make_stage1_data_dir, use_stage1_default_data

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

_WIDE_HEADER = ["world_id", "draw", "weight", "purchase_order.PO01.receipt_date"]


def _copy_stage1(dest_dir):
    """Copy stage-1 data to dest_dir/data and return that path."""
    dest = pathlib.Path(dest_dir) / "data"
    make_stage1_data_dir(dest)
    return dest


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for row in rows:
            w.writerow(row)


def _opt(result, sid):
    return next(o for o in result["options"] if o["scenario_id"] == sid)


# ---------------------------------------------------------------------------
# A. Stage 1 data (triangular weights, single draw 0)
#
# Stage1 worlds: dates 11-11..11-21, weights [14,42,70,98,126,154,173,141,101,61,20]
# total_weight = 1000, tail_weight = 100
#
# Late orders per date (from what_if table):
#   WAIT:     [0,1,3,4,5,7,7,8,10,10,11]
#   TRANSFER: [0,0,1,1,2,4,4,5, 7, 7, 8]
#   ALT_BUY:  [0,1,1,1,1,3,3,4, 6, 6, 7]
#   HYBRID:   [0,0,0,0,0,1,1,2, 4, 4, 5]
#
# Tail mean (worst 10%):
#   WAIT:     sorted desc lates: 11(w=20),10(w=101),... take 20 then 80 of 101
#             sum = 11*20 + 10*80 = 220+800 = 1020  tail_mean = 1020/100 = 10.20
#   TRANSFER: sorted: 8(w=20),7(w=101),... take 20 then 80 of 101
#             sum = 8*20 + 7*80 = 160+560 = 720     tail_mean = 720/100 = 7.20
#   ALT_BUY:  sorted: 7(w=20),6(w=101),... take 20 then 80 of 101
#             sum = 7*20 + 6*80 = 140+480 = 620     tail_mean = 620/100 = 6.20
#   HYBRID:   sorted: 5(w=20),4(w=101),... take 20 then 80 of 101
#             sum = 5*20 + 4*80 = 100+320 = 420     tail_mean = 420/100 = 4.20
#
# Single draw: average_range null, ranking null.
#
# Tradeoff tail_mean changes (sorted by cost: WAIT->TRANSFER->ALT_BUY->HYBRID):
#   WAIT->TRANSFER:     7.2 - 10.2 = -3.0
#   TRANSFER->ALT_BUY:  6.2 -  7.2 = -1.0
#   ALT_BUY->HYBRID:    4.2 -  6.2 = -2.0
# ---------------------------------------------------------------------------

_STAGE1_TAIL = {
    "WAIT":     10.2,
    "TRANSFER":  7.2,
    "ALT_BUY":   6.2,
    "HYBRID":    4.2,
}

_STAGE1_TAIL_TRADEOFF = [
    ("WAIT",     "TRANSFER", -3.0),
    ("TRANSFER", "ALT_BUY",  -1.0),
    ("ALT_BUY",  "HYBRID",   -2.0),
]


class TestStage1TailMean(unittest.TestCase):
    """(A) Stage 1 triangular weights: tail_mean, null range/ranking."""

    @classmethod
    def setUpClass(cls):
        cls._ctx = use_stage1_default_data()
        cls._ctx.__enter__()
        cls.db = load_all()
        cls.result = evaluate_worlds("D01", cls.db)

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def _check_tail(self, sid):
        opt = _opt(self.result, sid)
        got = opt["tail_mean_late_orders"]
        want = _STAGE1_TAIL[sid]
        if got != want:
            self.fail(
                f"stage1 tail_mean {sid}: expected {want}, got {got}"
            )

    def test_a_wait_tail(self):         self._check_tail("WAIT")
    def test_a_transfer_tail(self):     self._check_tail("TRANSFER")
    def test_a_alt_buy_tail(self):      self._check_tail("ALT_BUY")
    def test_a_hybrid_tail(self):       self._check_tail("HYBRID")

    def test_a_average_range_null(self):
        for sid in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            self.assertIsNone(
                _opt(self.result, sid)["average_range"],
                f"stage1 average_range {sid} should be null"
            )

    def test_a_ranking_null(self):
        self.assertIsNone(
            self.result["ranking"],
            "stage1 ranking should be null"
        )

    def test_a_tradeoff_tail_change(self):
        steps = self.result["tradeoff_steps"]
        step_map = {(s["from"], s["to"]): s for s in steps}
        for frm, to, want in _STAGE1_TAIL_TRADEOFF:
            key = (frm, to)
            self.assertIn(key, step_map, f"Missing tradeoff step {key}")
            got = step_map[key]["tail_mean_late_change"]
            if got != want:
                self.fail(
                    f"tradeoff {frm}->{to} tail_mean_late_change: "
                    f"expected {want}, got {got}"
                )


# ---------------------------------------------------------------------------
# B. Announced-date fallback (no worlds.csv): tail_mean = that world's late
#
# revised_receipt_date = 2026-11-17 (index 6 in 11-11..11-21)
# Late orders: WAIT=7, TRANSFER=4, ALT_BUY=3, HYBRID=1
# Single synthetic world with draw=None: average_range null, ranking null.
# ---------------------------------------------------------------------------

_ANNOUNCED_TAIL = {
    "WAIT":     7.0,
    "TRANSFER": 4.0,
    "ALT_BUY":  3.0,
    "HYBRID":   1.0,
}


class TestAnnouncedDateTail(unittest.TestCase):
    """(B) Announced-date fallback: tail_mean = single world's late orders."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_stage1(tmp)
            (dd / "worlds.csv").unlink()
            db = load_all(dd)
        cls.result = evaluate_worlds("D01", db)

    def _check_tail(self, sid):
        opt = _opt(self.result, sid)
        got = opt["tail_mean_late_orders"]
        want = _ANNOUNCED_TAIL[sid]
        if got != want:
            self.fail(
                f"announced_date tail_mean {sid}: expected {want}, got {got}"
            )

    def test_b_wait_tail(self):         self._check_tail("WAIT")
    def test_b_transfer_tail(self):     self._check_tail("TRANSFER")
    def test_b_alt_buy_tail(self):      self._check_tail("ALT_BUY")
    def test_b_hybrid_tail(self):       self._check_tail("HYBRID")

    def test_b_average_range_null(self):
        for sid in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            self.assertIsNone(
                _opt(self.result, sid)["average_range"],
                f"announced_date average_range {sid} should be null"
            )

    def test_b_ranking_null(self):
        self.assertIsNone(
            self.result["ranking"],
            "announced_date ranking should be null"
        )


# ---------------------------------------------------------------------------
# C. Hand-made worlds (10 worlds, weights 1..5 x 2 draws, same dates)
#
# Draw 0: W01..W05 (weights 1,2,3,4,5) at dates 11-21,11-19,11-17,11-15,11-13
# Draw 1: W06..W10 (weights 1,2,3,4,5) at dates 11-21,11-19,11-17,11-15,11-13
# (Both draws have identical date/weight assignments.)
# Total weight per draw = 15, grand total = 30.
# Tail weight = 3 (worst 10% = 30 * 1/10).
#
# Late orders at those dates (from what_if table, indices 10,8,6,4,2):
#   WAIT:     11,10, 7, 5, 3
#   TRANSFER:  8, 7, 4, 2, 1
#   ALT_BUY:   7, 6, 3, 1, 1
#   HYBRID:    5, 4, 1, 0, 0
#
# Since both draws are identical, effective combined weights are:
#   WAIT lates: (11,2),(10,4),(7,6),(5,8),(3,10)   total=30
#
# Tail mean (cut falls between first and second group):
#   WAIT:     take (11,2) [sum=22], then need 1 more from (10,4) [sum+=10]
#             tail_mean = 32/3 = 10.6666... -> 10.67
#   TRANSFER: take (8,2) [sum=16], need 1 more from (7,4) [sum+=7]
#             tail_mean = 23/3 = 7.6666... -> 7.67
#   ALT_BUY:  take (7,2) [sum=14], need 1 more from (6,4) [sum+=6]
#             tail_mean = 20/3 = 6.6666... -> 6.67
#   HYBRID:   take (5,2) [sum=10], need 1 more from (4,4) [sum+=4]
#             tail_mean = 14/3 = 4.6666... -> 4.67
#
# Per-draw expected (same for draw 0 and draw 1):
#   WAIT:     (11*1+10*2+7*3+5*4+3*5)/15 = (11+20+21+20+15)/15 = 87/15 = 5.8
#   TRANSFER: (8*1+7*2+4*3+2*4+1*5)/15  = (8+14+12+8+5)/15    = 47/15 = 3.1333
#   ALT_BUY:  (7*1+6*2+3*3+1*4+1*5)/15  = (7+12+9+4+5)/15     = 37/15 = 2.4666
#   HYBRID:   (5*1+4*2+1*3+0*4+0*5)/15  = (5+8+3)/15          = 16/15 = 1.0666
#
# average_range: q(1/20) and q(19/20) of [draw0_exp, draw1_exp] (each weight 1).
#   Both draws give same expected, so both quantiles equal that value.
#   WAIT:     round(87/15, 2) = round(5.8, 2) = 5.8  -> [5.8, 5.8]
#   TRANSFER: round(47/15, 2) = 3.13             -> [3.13, 3.13]
#   ALT_BUY:  round(37/15, 2) = 2.47             -> [2.47, 2.47]
#   HYBRID:   round(16/15, 2) = 1.07             -> [1.07, 1.07]
#
# Ranking: global order same as per-draw order (both draws identical).
#   Global expected: same 87/15, 47/15, 37/15, 16/15 (since equal draws)
#   Order: HYBRID < ALT_BUY < TRANSFER < WAIT
#   same_draws=2, other_orders=[]
# ---------------------------------------------------------------------------

_HAND_TAIL = {
    "WAIT":     10.67,
    "TRANSFER":  7.67,
    "ALT_BUY":   6.67,
    "HYBRID":    4.67,
}

_HAND_AVG_RANGE = {
    "WAIT":     [5.8,  5.8],
    "TRANSFER": [3.13, 3.13],
    "ALT_BUY":  [2.47, 2.47],
    "HYBRID":   [1.07, 1.07],
}

_HAND_WORLDS = (
    [_WIDE_HEADER] +
    [["W01", "0", "1", "2026-11-21"],
     ["W02", "0", "2", "2026-11-19"],
     ["W03", "0", "3", "2026-11-17"],
     ["W04", "0", "4", "2026-11-15"],
     ["W05", "0", "5", "2026-11-13"],
     ["W06", "1", "1", "2026-11-21"],
     ["W07", "1", "2", "2026-11-19"],
     ["W08", "1", "3", "2026-11-17"],
     ["W09", "1", "4", "2026-11-15"],
     ["W10", "1", "5", "2026-11-13"]]
)


class TestHandMadeWorldsTail(unittest.TestCase):
    """(C) Hand-made worlds: boundary cut, average_range, ranking."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_stage1(tmp)
            _write_csv(dd / "worlds.csv", _HAND_WORLDS)
            db = load_all(dd)
        cls.result = evaluate_worlds("D01", db)

    def _check_tail(self, sid):
        opt = _opt(self.result, sid)
        got = opt["tail_mean_late_orders"]
        want = _HAND_TAIL[sid]
        if got != want:
            self.fail(
                f"hand_made tail_mean {sid}: expected {want}, got {got}"
            )

    def test_c_wait_tail(self):         self._check_tail("WAIT")
    def test_c_transfer_tail(self):     self._check_tail("TRANSFER")
    def test_c_alt_buy_tail(self):      self._check_tail("ALT_BUY")
    def test_c_hybrid_tail(self):       self._check_tail("HYBRID")

    def _check_avg_range(self, sid):
        opt = _opt(self.result, sid)
        got = opt["average_range"]
        want = _HAND_AVG_RANGE[sid]
        if got != want:
            self.fail(
                f"hand_made average_range {sid}: expected {want}, got {got}"
            )

    def test_c_wait_avg_range(self):    self._check_avg_range("WAIT")
    def test_c_transfer_avg_range(self): self._check_avg_range("TRANSFER")
    def test_c_alt_buy_avg_range(self): self._check_avg_range("ALT_BUY")
    def test_c_hybrid_avg_range(self):  self._check_avg_range("HYBRID")

    def test_c_ranking_same_draws(self):
        r = self.result["ranking"]
        self.assertIsNotNone(r, "ranking should not be null")
        self.assertEqual(r["draws"], 2)
        self.assertEqual(r["same_draws"], 2,
                         f"expected same_draws=2, got {r['same_draws']}")
        self.assertEqual(r["other_orders"], [],
                         f"expected no other_orders, got {r['other_orders']}")

    def test_c_ranking_order(self):
        r = self.result["ranking"]
        self.assertIsNotNone(r)
        # Sorted ascending by per-draw expected late: HYBRID < ALT_BUY < TRANSFER < WAIT
        self.assertEqual(r["order"], ["HYBRID", "ALT_BUY", "TRANSFER", "WAIT"],
                         f"ranking order: {r['order']}")


# ---------------------------------------------------------------------------
# D. evaluate_run equals evaluate_worlds for all keys including new ones.
#
# Build a run on a data copy (M=20, N=10), then compare evaluate_run to
# evaluate_worlds on a copy with the run's worlds.csv.  Every key must match
# except weights_source (which is "run") and "run" (extra key).
# ---------------------------------------------------------------------------

class TestRunEqualsWorlds(unittest.TestCase):
    """(D) evaluate_run equals evaluate_worlds for all keys."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data_copy = base / "data_copy"
        shutil.copytree(_DATA_DIR, cls.data_copy, dirs_exist_ok=True)
        cls.run_dir = base / "runs" / "td"
        build_run(cls.data_copy, cls.run_dir, M=20, N=10, seed=7)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_d_run_equals_worlds(self):
        base = pathlib.Path(self._tmp)
        direct_copy = base / "data_copy2"
        shutil.copytree(_DATA_DIR, direct_copy, dirs_exist_ok=True)
        shutil.copy(self.run_dir / "worlds.csv", direct_copy / "worlds.csv")
        try:
            db_direct = load_all(direct_copy)
            direct = evaluate_worlds("D01", db_direct)
            db_base = load_all(self.data_copy)
            run_result = engine.runs.evaluate_run("D01", db_base, self.run_dir)
        finally:
            shutil.rmtree(direct_copy, ignore_errors=True)

        new_keys = ["tail_mean_late_orders", "average_range", "ranking",
                    "tail_mean_late_change"]
        # Check options.
        for opt_d, opt_r in zip(direct["options"], run_result["options"]):
            sid = opt_d["scenario_id"]
            for key in new_keys[:2]:  # option-level keys
                self.assertEqual(
                    opt_r[key], opt_d[key],
                    msg=f"[D01] option {sid} {key!r}: "
                        f"expected {opt_d[key]!r}, got {opt_r[key]!r}"
                )
        # Check tradeoff steps.
        for step_d, step_r in zip(direct["tradeoff_steps"], run_result["tradeoff_steps"]):
            self.assertEqual(
                step_r["tail_mean_late_change"],
                step_d["tail_mean_late_change"],
                msg=f"tradeoff {step_d['from']}->{step_d['to']} "
                    f"tail_mean_late_change: "
                    f"expected {step_d['tail_mean_late_change']!r}, "
                    f"got {step_r['tail_mean_late_change']!r}"
            )
        # Check top-level ranking.
        self.assertEqual(
            run_result["ranking"], direct["ranking"],
            msg=f"ranking: expected {direct['ranking']!r}, "
                f"got {run_result['ranking']!r}"
        )


# ---------------------------------------------------------------------------
# E. Ranking with two draws where both draws disagree with global order.
#
# Draw 0: W1(date 11-12, weight 1)
# Draw 1: W2(date 11-21, weight 1)
# (Equal totals: 1 each.)
#
# Late orders at 11-12: WAIT=1, TRANSFER=0, ALT_BUY=1, HYBRID=0
# Late orders at 11-21: WAIT=11, TRANSFER=8, ALT_BUY=7, HYBRID=5
#
# Global expected (total_w=2):
#   WAIT:     (1+11)/2 = 6.0
#   TRANSFER: (0+8)/2  = 4.0
#   ALT_BUY:  (1+7)/2  = 4.0
#   HYBRID:   (0+5)/2  = 2.5
#
# Global order (by (exp, scenarios.csv pos)):
#   HYBRID(2.5,pos3) < TRANSFER(4.0,pos1) < ALT_BUY(4.0,pos2) < WAIT(6.0,pos0)
#   = [HYBRID, TRANSFER, ALT_BUY, WAIT]
#
# Draw 0 expected (W1 only, weight=1):
#   WAIT=1, TRANSFER=0, ALT_BUY=1, HYBRID=0
#   Draw 0 order: TRANSFER(0,1) < HYBRID(0,3) < WAIT(1,0) < ALT_BUY(1,2)
#   = [TRANSFER, HYBRID, WAIT, ALT_BUY]
#
# Draw 1 expected (W2 only, weight=1):
#   WAIT=11, TRANSFER=8, ALT_BUY=7, HYBRID=5
#   Draw 1 order: HYBRID(5,3) < ALT_BUY(7,2) < TRANSFER(8,1) < WAIT(11,0)
#   = [HYBRID, ALT_BUY, TRANSFER, WAIT]
#
# Neither draw matches global order:
#   same_draws = 0
#   other_orders (both n=1, sorted by order list asc):
#     [HYBRID, ALT_BUY, TRANSFER, WAIT] (draws=1)   <- 'H' < 'T'
#     [TRANSFER, HYBRID, WAIT, ALT_BUY] (draws=1)
# ---------------------------------------------------------------------------

_TWO_DRAW_RANKING_WORLDS = [
    _WIDE_HEADER,
    ["W1", "0", "1", "2026-11-12"],
    ["W2", "1", "1", "2026-11-21"],
]


class TestRankingDrawsDisagree(unittest.TestCase):
    """(E) Two draws where both draws disagree with global ranking order."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_stage1(tmp)
            _write_csv(dd / "worlds.csv", _TWO_DRAW_RANKING_WORLDS)
            db = load_all(dd)
        cls.result = evaluate_worlds("D01", db)

    def test_e_ranking_not_null(self):
        self.assertIsNotNone(self.result["ranking"])

    def test_e_global_order(self):
        r = self.result["ranking"]
        got = r["order"]
        want = ["HYBRID", "TRANSFER", "ALT_BUY", "WAIT"]
        self.assertEqual(got, want,
                         f"global order: expected {want}, got {got}")

    def test_e_draws(self):
        self.assertEqual(self.result["ranking"]["draws"], 2)

    def test_e_same_draws(self):
        got = self.result["ranking"]["same_draws"]
        self.assertEqual(got, 0,
                         f"same_draws: expected 0, got {got}")

    def test_e_other_orders(self):
        other = self.result["ranking"]["other_orders"]
        self.assertEqual(len(other), 2,
                         f"expected 2 other_orders, got {len(other)}: {other}")
        # Both have draws=1.
        for entry in other:
            self.assertEqual(entry["draws"], 1,
                             f"other_order draws: expected 1, got {entry['draws']}")
        # First entry (sorted by order list asc): [HYBRID, ALT_BUY, TRANSFER, WAIT]
        self.assertEqual(other[0]["order"], ["HYBRID", "ALT_BUY", "TRANSFER", "WAIT"],
                         f"other_orders[0]: {other[0]['order']}")
        # Second entry: [TRANSFER, HYBRID, WAIT, ALT_BUY]
        self.assertEqual(other[1]["order"], ["TRANSFER", "HYBRID", "WAIT", "ALT_BUY"],
                         f"other_orders[1]: {other[1]['order']}")


if __name__ == "__main__":
    unittest.main()
