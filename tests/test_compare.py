"""Tests for engine/compare.py and engine/tools.compare_scenarios."""
import unittest

from engine.loader import load_all
from engine.simulate import simulate, build_scenario_actions
from engine.evaluate import evaluate
from engine.compare import rank_options
from engine.tools import compare_scenarios

_DB = load_all()


def _build_disrupted_options():
    """Build evaluated options for the 4 disrupted scenarios (excludes NORMAL)."""
    options = []
    for sid, scenario in _DB["scenarios"].items():
        if scenario["disruption_id"] is None:
            continue
        actions, disruption_id = build_scenario_actions(sid, _DB)
        sim = simulate(actions, disruption_id, _DB)
        kpi = evaluate(sim)
        kpi["scenario_id"] = sid
        kpi["label"] = f"Label for {sid}"  # display label distinct from scenario_id
        options.append(kpi)
    return options


_OPTIONS = _build_disrupted_options()


class TestCompareScenarios(unittest.TestCase):

    def test_budget_500_best_is_transfer(self):
        """With budget=500, best is scenario_id TRANSFER."""
        result = compare_scenarios(budget=500, objective="on_time_orders")
        self.assertEqual(result["best"], "TRANSFER",
                         f"Full result: {result}")

    def test_no_budget_best_is_hybrid(self):
        """Without budget constraint, best is scenario_id HYBRID."""
        result = compare_scenarios(objective="on_time_orders")
        self.assertEqual(result["best"], "HYBRID",
                         f"Full result: {result}")

    def test_best_is_scenario_id_not_label(self):
        """best field must be scenario_id (e.g. HYBRID), not the CSV label."""
        result = compare_scenarios(objective="on_time_orders")
        # scenario_id is always uppercase without spaces
        self.assertNotIn(" ", result["best"])
        self.assertEqual(result["best"], result["best"].upper())

    def test_ranked_entries_have_scenario_id_and_label(self):
        """Each ranked entry must carry both scenario_id and label fields."""
        result = compare_scenarios(objective="on_time_orders")
        for entry in result["ranked"]:
            self.assertIn("scenario_id", entry)
            self.assertIn("label", entry)
            # scenario_id and label must differ (label is the CSV display string)
            self.assertNotEqual(entry["scenario_id"], entry["label"])

    def test_compare_scenarios_has_baseline(self):
        """compare_scenarios must return a baseline field with NORMAL metrics."""
        result = compare_scenarios()
        self.assertIn("baseline", result)
        baseline = result["baseline"]
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline["on_time_orders"], 12)
        self.assertEqual(baseline["total_extra_cost"], 0)
        self.assertEqual(baseline["scenario_id"], "NORMAL")

    def test_budget_500_excludes_alt_buy_and_hybrid(self):
        """Budget 500 must exclude ALT_BUY ($1250) and HYBRID ($1306)."""
        result = compare_scenarios(budget=500, objective="on_time_orders")
        ranked_ids = [r["scenario_id"] for r in result["ranked"]]
        self.assertNotIn("ALT_BUY", ranked_ids)
        self.assertNotIn("HYBRID", ranked_ids)

    def test_rank_options_budget_500_best_is_transfer(self):
        """rank_options with scenario_id and budget=500 → TRANSFER best."""
        result = rank_options(_OPTIONS, objective="on_time_orders", budget=500)
        self.assertEqual(result["best"], "TRANSFER")

    def test_rank_options_no_budget_best_is_hybrid(self):
        """rank_options with no budget → HYBRID best."""
        result = rank_options(_OPTIONS, objective="on_time_orders")
        self.assertEqual(result["best"], "HYBRID")

    def test_rank_options_invalid_objective(self):
        with self.assertRaises(ValueError):
            rank_options(_OPTIONS, objective="invalid_objective")

    def test_rank_options_budget_zero_only_wait(self):
        """Budget of 0 from disrupted options only leaves WAIT ($0 cost)."""
        result = rank_options(_OPTIONS, objective="on_time_orders", budget=0)
        self.assertEqual(result["best"], "WAIT")

    def test_transfer_rank_within_budget(self):
        """TRANSFER ($416) should be rank 1 within budget=500 by on_time_orders."""
        result = rank_options(_OPTIONS, objective="on_time_orders", budget=500)
        self.assertEqual(result["ranked"][0]["scenario_id"], "TRANSFER")
        self.assertEqual(result["ranked"][0]["on_time_orders"], 8)


if __name__ == "__main__":
    unittest.main()
