"""Tests for engine/analysis.py and related tools functions."""
import unittest

from engine.loader import load_all
from engine.simulate import simulate, build_scenario_actions
from engine.evaluate import evaluate
from engine.analysis import disruption_impact, priority_view, marginal_cost
from engine.tools import get_impact, get_priority_view

_DB = load_all()


def _run_scenario(scenario_id):
    actions, disruption_id = build_scenario_actions(scenario_id, _DB)
    sim = simulate(actions, disruption_id, _DB)
    return sim


class TestDisruptionImpact(unittest.TestCase):

    def setUp(self):
        self.impact = disruption_impact("D01", _DB)

    def test_first_late_order_is_so02(self):
        self.assertEqual(self.impact["first_late_order_id"], "SO02")

    def test_first_late_days(self):
        # SO02 in WAIT scenario: delivery 2026-11-19, due 2026-11-13 → 6 days late
        self.assertEqual(self.impact["first_late_days"], 6)

    def test_late_orders_count(self):
        # SO01 is on time; SO02-SO08 are late in WAIT; SO09-SO12 catch up
        self.assertEqual(len(self.impact["late_orders"]), 7)

    def test_late_order_ids(self):
        ids = [r["order_id"] for r in self.impact["late_orders"]]
        self.assertEqual(ids, ["SO02", "SO03", "SO04", "SO05", "SO06", "SO07", "SO08"])

    def test_c01_shortage_has_13_days(self):
        # DAY0 to HORIZON inclusive = 13 days
        self.assertEqual(len(self.impact["c01_shortage_by_day"]), 13)

    def test_c01_shortage_day_zero_positive(self):
        # On DAY0 (2026-11-09) there is C01 shortage because WH01 only has 24
        # but SO01 needs 12 (latest start 11-10) — no shortage yet on day 0
        # since no order has latest_start <= 11-09
        row = next(r for r in self.impact["c01_shortage_by_day"]
                   if r["date"] == "2026-11-09")
        # SO01 latest_start = 11-11 - 1 = 11-10, so on 11-09 cumulative_needed = 0
        self.assertEqual(row["c01_cumulative_needed"], 0)
        self.assertEqual(row["shortage"], 0)

    def test_unknown_disruption_raises(self):
        with self.assertRaises(ValueError):
            disruption_impact("D99", _DB)


class TestPriorityView(unittest.TestCase):

    def test_wait_priority1_on_time_count(self):
        """WAIT: SO01 and SO11 are the only priority-1 orders on time → 2 of 6."""
        sim = _run_scenario("WAIT")
        pv = priority_view(sim, _DB)
        self.assertEqual(pv["on_time_count"], 2)
        self.assertEqual(pv["total_count"], 6)

    def test_hybrid_priority1_on_time_count(self):
        """HYBRID: SO08 is the only priority-1 order late → 5 of 6 on time."""
        sim = _run_scenario("HYBRID")
        pv = priority_view(sim, _DB)
        self.assertEqual(pv["on_time_count"], 5)
        self.assertEqual(pv["total_count"], 6)

    def test_priority1_order_ids(self):
        """Priority-1 orders are SO01, SO02, SO04, SO06, SO08, SO11."""
        sim = _run_scenario("NORMAL")
        pv = priority_view(sim, _DB)
        order_ids = [r["order_id"] for r in pv["priority_1_orders"]]
        self.assertEqual(order_ids, ["SO01", "SO02", "SO04", "SO06", "SO08", "SO11"])

    def test_customer_impact_structure(self):
        """customer_impact must have an entry for each customer with a priority-1 order."""
        sim = _run_scenario("WAIT")
        pv = priority_view(sim, _DB)
        # All priority-1 orders belong to unique customers
        self.assertIn("CU01", pv["customer_impact"])  # SO01
        self.assertIn("CU08", pv["customer_impact"])  # SO08


class TestMarginalCost(unittest.TestCase):

    def setUp(self):
        """Build evaluated options for disrupted scenarios only."""
        disrupted = ["WAIT", "TRANSFER", "ALT_BUY", "HYBRID"]
        opts = []
        for sid in disrupted:
            actions, disruption_id = build_scenario_actions(sid, _DB)
            sim = simulate(actions, disruption_id, _DB)
            kpi = evaluate(sim)
            kpi["label"] = sid
            opts.append(kpi)
        self.result = marginal_cost(opts)

    def test_step_count(self):
        """3 steps between 4 options."""
        self.assertEqual(len(self.result["steps"]), 3)

    def test_wait_to_transfer(self):
        step = self.result["steps"][0]
        self.assertEqual(step["from_label"], "WAIT")
        self.assertEqual(step["to_label"], "TRANSFER")
        self.assertEqual(step["extra_on_time_orders"], 3)
        self.assertEqual(step["extra_cost_usd"], 416)
        self.assertAlmostEqual(step["cost_per_order_usd"], 416 / 3)

    def test_transfer_to_alt_buy(self):
        step = self.result["steps"][1]
        self.assertEqual(step["from_label"], "TRANSFER")
        self.assertEqual(step["to_label"], "ALT_BUY")
        self.assertEqual(step["extra_on_time_orders"], 1)
        self.assertEqual(step["extra_cost_usd"], 834)
        self.assertAlmostEqual(step["cost_per_order_usd"], 834.0)

    def test_alt_buy_to_hybrid(self):
        step = self.result["steps"][2]
        self.assertEqual(step["from_label"], "ALT_BUY")
        self.assertEqual(step["to_label"], "HYBRID")
        self.assertEqual(step["extra_on_time_orders"], 2)
        self.assertEqual(step["extra_cost_usd"], 56)
        self.assertAlmostEqual(step["cost_per_order_usd"], 28.0)


if __name__ == "__main__":
    unittest.main()
