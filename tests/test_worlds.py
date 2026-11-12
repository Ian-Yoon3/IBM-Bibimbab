"""Tests for engine/worlds.py.

Expected numbers were computed in advance. If one does not match, the test
reports the difference and stops without modifying the expected values.
"""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from fractions import Fraction

from engine.loader import load_all
from engine.simulate import build_scenario_actions, simulate
from engine.evaluate import evaluate
from engine.tools import compare_scenarios
from engine.worlds import (
    apply_world,
    evaluate_worlds,
    quantile,
    round_half_away,
    worlds_for,
)

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


# ---------------------------------------------------------------------------
# (a) No world files: source "announced_date", results match compare_scenarios
# ---------------------------------------------------------------------------

class TestNoWorldFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()
            (dd / "world_overrides.csv").unlink()
            cls.db = load_all(dd)
        cls.result = evaluate_worlds("D01", cls.db)
        cls.cs = compare_scenarios()

    def test_a_weights_source(self):
        self.assertEqual(self.result["weights_source"], "announced_date")

    def _opt(self, sid):
        return next(o for o in self.result["options"] if o["scenario_id"] == sid)

    def _cs_kpi(self, sid):
        for o in self.cs["options"]:
            if o["scenario_id"] == sid:
                return o
        return None

    def _assert_match(self, sid, expected_late, expected_cost):
        opt = self._opt(sid)
        if opt["expected_late_orders"] != expected_late:
            self.fail(
                f"{sid} expected_late_orders: expected {expected_late}, "
                f"got {opt['expected_late_orders']}"
            )
        if opt["worst_late_orders"] != expected_late:
            self.fail(
                f"{sid} worst_late_orders: expected {expected_late}, "
                f"got {opt['worst_late_orders']}"
            )
        if opt["p90_late_orders"] != expected_late:
            self.fail(
                f"{sid} p90_late_orders: expected {expected_late}, "
                f"got {opt['p90_late_orders']}"
            )
        self.assertEqual(opt["p_no_late_pct"], 0.0)
        if opt["extra_cost"] != expected_cost:
            self.fail(
                f"{sid} extra_cost: expected {expected_cost}, "
                f"got {opt['extra_cost']}"
            )

    def test_a_wait(self):
        self._assert_match("WAIT", 7, 0)

    def test_a_transfer(self):
        self._assert_match("TRANSFER", 4, 416)

    def test_a_alt_buy(self):
        self._assert_match("ALT_BUY", 3, 1250)

    def test_a_hybrid(self):
        self._assert_match("HYBRID", 1, 1306)


# ---------------------------------------------------------------------------
# (b) One world on 2026-11-17, weight 5: same numbers, source "file"
# ---------------------------------------------------------------------------

class TestOneWorldFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W1", "5"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W1", "purchase_order", "PO01", "receipt_date", "2026-11-17"],
            ])
            cls.db = load_all(dd)
        cls.result = evaluate_worlds("D01", cls.db)

    def test_b_weights_source(self):
        self.assertEqual(self.result["weights_source"], "file")

    def _opt(self, sid):
        return next(o for o in self.result["options"] if o["scenario_id"] == sid)

    def _check(self, sid, late, cost):
        opt = self._opt(sid)
        for key in ("expected_late_orders", "worst_late_orders", "p90_late_orders"):
            got = opt[key]
            if got != late:
                self.fail(f"{sid} {key}: expected {late}, got {got}")
        self.assertEqual(opt["p_no_late_pct"], 0.0)
        self.assertEqual(opt["extra_cost"], cost)

    def test_b_wait(self):
        self._check("WAIT", 7, 0)

    def test_b_transfer(self):
        self._check("TRANSFER", 4, 416)

    def test_b_alt_buy(self):
        self._check("ALT_BUY", 3, 1250)

    def test_b_hybrid(self):
        self._check("HYBRID", 1, 1306)


# ---------------------------------------------------------------------------
# (c) WAIT on 2026-11-11 equals evaluate() result of NORMAL
# ---------------------------------------------------------------------------

class TestWaitOnEarliestEqualsNormal(unittest.TestCase):
    def test_c_wait_on_1111_equals_normal(self):
        db = load_all()
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            _write_csv(dd / "worlds.csv", [
                ["world_id", "weight"],
                ["W1", "1"],
            ])
            _write_csv(dd / "world_overrides.csv", [
                ["world_id", "target_type", "target_id", "field", "value"],
                ["W1", "purchase_order", "PO01", "receipt_date", "2026-11-11"],
            ])
            db_one = load_all(dd)

        result = evaluate_worlds("D01", db_one)
        wait_opt = next(o for o in result["options"] if o["scenario_id"] == "WAIT")

        # NORMAL
        normal_actions, normal_dis = build_scenario_actions("NORMAL", db)
        normal_sim = simulate(normal_actions, normal_dis, db)
        normal_ev = evaluate(normal_sim)

        self.assertEqual(wait_opt["worst_late_orders"], normal_ev["late_orders"])
        self.assertEqual(wait_opt["expected_late_orders"],
                         float(normal_ev["late_orders"]))


# ---------------------------------------------------------------------------
# (d) Equal weights (11 worlds, weight 1 each)
# ---------------------------------------------------------------------------

_EQUAL_EXPECTED = {
    "WAIT":     {"expected": 6.0,  "worst": 11, "p90": 10, "p_no": 9.1,  "cost": 0},
    "TRANSFER": {"expected": 3.55, "worst": 8,  "p90": 7,  "p_no": 18.2, "cost": 416},
    "ALT_BUY":  {"expected": 3.0,  "worst": 7,  "p90": 6,  "p_no": 9.1,  "cost": 1250},
    "HYBRID":   {"expected": 1.55, "worst": 5,  "p90": 4,  "p_no": 45.5, "cost": 1306},
}

class TestEqualWeights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            dates = [date(2026, 11, 11) + timedelta(days=i) for i in range(11)]
            worlds_rows = [["world_id", "weight"]] + [[f"W{i+1:03d}", "1"] for i in range(11)]
            _write_csv(dd / "worlds.csv", worlds_rows)
            overrides_rows = [["world_id", "target_type", "target_id", "field", "value"]]
            for i, d in enumerate(dates):
                overrides_rows.append([f"W{i+1:03d}", "purchase_order", "PO01",
                                       "receipt_date", d.isoformat()])
            _write_csv(dd / "world_overrides.csv", overrides_rows)
            db = load_all(dd)
        cls.result = evaluate_worlds("D01", db)

    def _opt(self, sid):
        return next(o for o in self.result["options"] if o["scenario_id"] == sid)

    def _check(self, sid):
        exp = _EQUAL_EXPECTED[sid]
        opt = self._opt(sid)
        for attr, key in [("expected", "expected_late_orders"),
                          ("worst", "worst_late_orders"),
                          ("p90", "p90_late_orders"),
                          ("p_no", "p_no_late_pct"),
                          ("cost", "extra_cost")]:
            got = opt[key]
            want = exp[attr]
            if got != want:
                self.fail(
                    f"test_d: {sid} {key}: expected {want}, got {got}"
                )

    def test_d_wait(self):      self._check("WAIT")
    def test_d_transfer(self):  self._check("TRANSFER")
    def test_d_alt_buy(self):   self._check("ALT_BUY")
    def test_d_hybrid(self):    self._check("HYBRID")


# ---------------------------------------------------------------------------
# (e) Repo data (triangular weights)
# ---------------------------------------------------------------------------

_TRI_EXPECTED = {
    "WAIT":     {"expected": 6.53, "worst": 11, "p90": 10, "p_no": 1.4,  "cost": 0},
    "TRANSFER": {"expected": 3.73, "worst": 8,  "p90": 7,  "p_no": 5.6,  "cost": 416},
    "ALT_BUY":  {"expected": 2.99, "worst": 7,  "p90": 6,  "p_no": 1.4,  "cost": 1250},
    "HYBRID":   {"expected": 1.36, "worst": 5,  "p90": 4,  "p_no": 35.0, "cost": 1306},
}

_TRI_TRADEOFF = [
    # from, to, cost_chg, exp_chg, worst_chg, p90_chg, p_no_chg
    ("WAIT",     "TRANSFER", 416,  -2.8,  -3, -3, 4.2),
    ("TRANSFER", "ALT_BUY",  834,  -0.73, -1, -1, -4.2),
    ("ALT_BUY",  "HYBRID",    56,  -1.64, -2, -2, 33.6),
]

class TestTriangularWeights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_all()
        cls.result = evaluate_worlds("D01", cls.db)

    def _opt(self, sid):
        return next(o for o in self.result["options"] if o["scenario_id"] == sid)

    def _check_option(self, sid):
        exp = _TRI_EXPECTED[sid]
        opt = self._opt(sid)
        for attr, key in [("expected", "expected_late_orders"),
                          ("worst", "worst_late_orders"),
                          ("p90", "p90_late_orders"),
                          ("p_no", "p_no_late_pct"),
                          ("cost", "extra_cost")]:
            got = opt[key]
            want = exp[attr]
            if got != want:
                self.fail(
                    f"test_e: {sid} {key}: expected {want}, got {got}"
                )

    def test_e_wait(self):      self._check_option("WAIT")
    def test_e_transfer(self):  self._check_option("TRANSFER")
    def test_e_alt_buy(self):   self._check_option("ALT_BUY")
    def test_e_hybrid(self):    self._check_option("HYBRID")

    def test_e_tradeoff_steps(self):
        steps = self.result["tradeoff_steps"]
        self.assertEqual(len(steps), len(_TRI_TRADEOFF))
        for step, (frm, to, cost_chg, exp_chg, worst_chg, p90_chg, p_no_chg) in \
                zip(steps, _TRI_TRADEOFF):
            if step["from"] != frm or step["to"] != to:
                self.fail(
                    f"tradeoff step from/to: expected ({frm},{to}), "
                    f"got ({step['from']},{step['to']})"
                )
            for attr, key, want in [
                ("extra_cost_change",    "extra_cost_change",    cost_chg),
                ("expected_late_change", "expected_late_change", exp_chg),
                ("worst_late_change",    "worst_late_change",    worst_chg),
                ("p90_late_change",      "p90_late_change",      p90_chg),
                ("p_no_late_pct_change", "p_no_late_pct_change", p_no_chg),
            ]:
                got = step[key]
                if got != want:
                    self.fail(
                        f"tradeoff {frm}->{to} {key}: expected {want}, got {got}"
                    )


# ---------------------------------------------------------------------------
# (f) Weights multiplied by 7: identical output
# ---------------------------------------------------------------------------

class TestWeightsScaling(unittest.TestCase):
    def test_f_multiply_weights_by_7(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            # Read the existing worlds.csv and multiply weights by 7
            worlds_path = dd / "worlds.csv"
            rows = []
            with open(worlds_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["weight"] = str(int(row["weight"]) * 7)
                    rows.append(row)
            with open(worlds_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["world_id", "weight"])
                writer.writeheader()
                writer.writerows(rows)
            db7 = load_all(dd)

        db1 = load_all()
        r1 = evaluate_worlds("D01", db1)
        r7 = evaluate_worlds("D01", db7)

        for opt1, opt7 in zip(r1["options"], r7["options"]):
            for key in ("expected_late_orders", "worst_late_orders",
                        "p90_late_orders", "p_no_late_pct", "extra_cost"):
                self.assertEqual(opt1[key], opt7[key],
                                 msg=f"{opt1['scenario_id']} {key} differs")

        self.assertEqual(r1["tradeoff_steps"], r7["tradeoff_steps"])


# ---------------------------------------------------------------------------
# (g) For every option: min late <= exact expected <= worst
# ---------------------------------------------------------------------------

class TestExpectedBounds(unittest.TestCase):
    def test_g_expected_between_min_and_worst(self):
        db = load_all()
        worlds = db["worlds"]
        scenario_ids = [sid for sid, s in db["scenarios"].items()
                        if s["disruption_id"] == "D01"]
        result = evaluate_worlds("D01", db)
        for opt in result["options"]:
            sid = opt["scenario_id"]
            actions, _ = build_scenario_actions(sid, db)
            lates = []
            for w in worlds:
                db_w = apply_world(db, w)
                sim = simulate(actions, "D01", db_w)
                ev = evaluate(sim)
                lates.append(ev["late_orders"])
            min_late = min(lates)
            worst = max(lates)
            exp = opt["expected_late_orders"]
            self.assertLessEqual(min_late, exp,
                msg=f"{sid}: min {min_late} > expected {exp}")
            self.assertLessEqual(exp, worst,
                msg=f"{sid}: expected {exp} > worst {worst}")


# ---------------------------------------------------------------------------
# (h) what_if dates and late_orders
# ---------------------------------------------------------------------------

_WHAT_IF_EXPECTED = {
    "WAIT":     [0, 1, 3, 4, 5, 7, 7, 8, 10, 10, 11],
    "TRANSFER": [0, 0, 1, 1, 2, 4, 4, 5, 7,  7,  8],
    "ALT_BUY":  [0, 1, 1, 1, 1, 3, 3, 4, 6,  6,  7],
    "HYBRID":   [0, 0, 0, 0, 0, 1, 1, 2, 4,  4,  5],
}

class TestWhatIf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_all()
        cls.result = evaluate_worlds("D01", cls.db)

    def test_h_dates(self):
        expected_dates = [
            f"2026-11-{d:02d}" for d in range(11, 22)
        ]
        self.assertEqual(self.result["what_if"]["dates"], expected_dates)

    def _check_scenario(self, sid):
        got = self.result["what_if"]["late_orders"][sid]
        want = _WHAT_IF_EXPECTED[sid]
        if got != want:
            self.fail(f"what_if {sid}: expected {want}, got {got}")

    def test_h_wait(self):      self._check_scenario("WAIT")
    def test_h_transfer(self):  self._check_scenario("TRANSFER")
    def test_h_alt_buy(self):   self._check_scenario("ALT_BUY")
    def test_h_hybrid(self):    self._check_scenario("HYBRID")

    def test_h_same_without_world_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = _copy_data(tmp)
            (dd / "worlds.csv").unlink()
            (dd / "world_overrides.csv").unlink()
            db_no = load_all(dd)
        r_no = evaluate_worlds("D01", db_no)
        self.assertEqual(r_no["what_if"], self.result["what_if"])


# ---------------------------------------------------------------------------
# (i) db is not mutated by evaluate_worlds
# ---------------------------------------------------------------------------

class TestNoMutation(unittest.TestCase):
    def test_i_db_not_mutated(self):
        db = load_all()
        original_revised = db["disruptions"]["D01"]["revised_receipt_date"]

        evaluate_worlds("D01", db)

        self.assertEqual(
            db["disruptions"]["D01"]["revised_receipt_date"],
            original_revised,
        )
        # compare_scenarios() must give the same result after evaluate_worlds
        cs_before = compare_scenarios()
        evaluate_worlds("D01", db)
        cs_after = compare_scenarios()
        self.assertEqual(cs_before["ranked"], cs_after["ranked"])


# ---------------------------------------------------------------------------
# (j) round_half_away
# ---------------------------------------------------------------------------

class TestRoundHalfAway(unittest.TestCase):
    def test_j_0125_to_2digits(self):
        self.assertEqual(round_half_away(Fraction(125, 1000), 2), 0.13)

    def test_j_neg0125_to_2digits(self):
        self.assertEqual(round_half_away(Fraction(-125, 1000), 2), -0.13)

    def test_j_2p5_to_0digits(self):
        self.assertEqual(round_half_away(Fraction(5, 2), 0), 3.0)


# ---------------------------------------------------------------------------
# (k) quantile
# ---------------------------------------------------------------------------

class TestQuantile(unittest.TestCase):
    def test_k_level_1_gives_max(self):
        pairs = [(1, Fraction(1)), (3, Fraction(2)), (5, Fraction(1))]
        self.assertEqual(quantile(pairs, Fraction(1)), 5)

    def test_k_level_0_raises(self):
        with self.assertRaises(ValueError):
            quantile([(1, Fraction(1))], Fraction(0))

    def test_k_level_1p5_raises(self):
        with self.assertRaises(ValueError):
            quantile([(1, Fraction(1))], Fraction(3, 2))


# ---------------------------------------------------------------------------
# (l) apply_world with unsupported kind raises ValueError
# ---------------------------------------------------------------------------

class TestApplyWorldUnsupportedKind(unittest.TestCase):
    def test_l_offer_lead_days_raises(self):
        db = load_all()
        bad_world = {
            "overrides": {("offer", "OF02", "lead_days"): 5},
        }
        with self.assertRaises(ValueError):
            apply_world(db, bad_world)


if __name__ == "__main__":
    unittest.main()
