"""Tests for engine/tools.py — agent-facing functions."""
import json
import unittest

from engine.loader import load_all
from engine.tools import (
    get_disruption,
    get_offers,
    run_scenario,
    compare_scenarios,
    get_impact,
    get_priority_view,
    explore_purchase_qty,
    propose_action,
)
from engine.simulate import build_scenario_actions

_DB = load_all()


class TestGetDisruption(unittest.TestCase):

    def test_d01_fields(self):
        result = get_disruption("D01")
        self.assertEqual(result["disruption_id"], "D01")
        self.assertEqual(result["po_id"], "PO01")
        self.assertEqual(result["component_id"], "C01")
        self.assertEqual(result["qty"], 145)
        self.assertEqual(result["original_receipt_date"], "2026-11-11")
        self.assertEqual(result["revised_receipt_date"], "2026-11-17")
        self.assertEqual(result["delay_days"], 6)

    def test_json_serialisable(self):
        result = get_disruption("D01")
        json.dumps(result)  # must not raise

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            get_disruption("D99")


class TestRunScenario(unittest.TestCase):

    def test_wait_on_time_orders(self):
        result = run_scenario([], "D01")
        self.assertEqual(result["on_time_orders"], 5)

    def test_normal_all_on_time(self):
        result = run_scenario([], None)
        self.assertEqual(result["on_time_orders"], 12)

    def test_json_serialisable(self):
        result = run_scenario([], "D01")
        json.dumps(result)  # must not raise

    def test_returns_order_results(self):
        result = run_scenario([], None)
        self.assertIn("order_results", result)
        self.assertEqual(len(result["order_results"]), 12)

    def test_returns_end_inventory(self):
        result = run_scenario([], None)
        self.assertIn("end_inventory", result)
        self.assertIn("WH01", result["end_inventory"])


class TestCompareScenarios(unittest.TestCase):

    def test_budget_500_best_is_transfer(self):
        """best must be scenario_id TRANSFER, not a display label."""
        result = compare_scenarios(budget=500, objective="on_time_orders")
        self.assertEqual(result["best"], "TRANSFER")

    def test_no_budget_best_is_hybrid(self):
        """best must be scenario_id HYBRID, not a display label."""
        result = compare_scenarios(objective="on_time_orders")
        self.assertEqual(result["best"], "HYBRID")

    def test_json_serialisable(self):
        result = compare_scenarios()
        json.dumps(result)

    def test_budget_500_has_two_options(self):
        # Only WAIT ($0) and TRANSFER ($416) are within budget=500
        result = compare_scenarios(budget=500)
        self.assertEqual(len(result["ranked"]), 2)

    def test_has_baseline_with_normal_metrics(self):
        """compare_scenarios must include NORMAL as a separate baseline field."""
        result = compare_scenarios()
        self.assertIn("baseline", result)
        self.assertEqual(result["baseline"]["on_time_orders"], 12)
        self.assertEqual(result["baseline"]["scenario_id"], "NORMAL")
        self.assertEqual(result["baseline"]["total_extra_cost"], 0)

    def test_ranked_have_scenario_id(self):
        """Each ranked entry must have a scenario_id field."""
        result = compare_scenarios()
        for entry in result["ranked"]:
            self.assertIn("scenario_id", entry)
            self.assertIn("label", entry)


class TestGetImpact(unittest.TestCase):

    def test_first_late_order(self):
        result = get_impact("D01")
        self.assertEqual(result["first_late_order_id"], "SO02")

    def test_json_serialisable(self):
        result = get_impact("D01")
        json.dumps(result)


class TestGetPriorityView(unittest.TestCase):

    def test_wait_on_time_count(self):
        result = get_priority_view([], "D01")
        self.assertEqual(result["on_time_count"], 2)

    def test_json_serialisable(self):
        result = get_priority_view([], "D01")
        json.dumps(result)

    def test_scenario_id_hybrid_on_time_count(self):
        """get_priority_view(scenario_id='HYBRID') -> 5 of 6 priority-1 on time."""
        result = get_priority_view(scenario_id="HYBRID")
        self.assertEqual(result["on_time_count"], 5)
        self.assertEqual(result["total_count"], 6)

    def test_scenario_id_matches_actions_path(self):
        """Results via scenario_id= match the equivalent explicit actions path."""
        actions, disruption_id = build_scenario_actions("TRANSFER", _DB)
        via_actions = get_priority_view(actions, disruption_id)
        via_scenario = get_priority_view(scenario_id="TRANSFER")
        self.assertEqual(via_actions["on_time_count"], via_scenario["on_time_count"])

    def test_unknown_scenario_id_raises(self):
        with self.assertRaises(ValueError):
            get_priority_view(scenario_id="BOGUS")


class TestExplorePurchaseQty(unittest.TestCase):

    def test_qty_65_reproduces_alt_buy(self):
        """OF02 qty=65 should reproduce ALT_BUY: 9 on-time, $1250."""
        result = explore_purchase_qty("OF02")
        options = {r["purchase_qty"]: r for r in result["ranked"]}
        self.assertEqual(options[65]["on_time_orders"], 9)
        self.assertEqual(options[65]["total_extra_cost"], 1250)

    def test_qty_45_with_transfers_reproduces_hybrid(self):
        """OF02 qty=45 + all transfers should reproduce HYBRID: 11 on-time, $1306."""
        result = explore_purchase_qty("OF02", include_transfers=True)
        options = {r["purchase_qty"]: r for r in result["ranked"]}
        self.assertEqual(options[45]["on_time_orders"], 11)
        self.assertEqual(options[45]["total_extra_cost"], 1306)

    def test_all_valid_quantities_present(self):
        result = explore_purchase_qty("OF02")
        qtys = {r["purchase_qty"] for r in result["ranked"]}
        for qty in range(20, 66, 5):
            self.assertIn(qty, qtys)

    def test_explore_labels_descriptive(self):
        """Labels must be descriptive and not contain 'buy_' prefix."""
        result = explore_purchase_qty("OF02")
        for r in result["ranked"]:
            self.assertNotIn("buy_", r["label"])
            self.assertIn("OF02", r["label"])

    def test_explore_with_transfers_label_mentions_transfers(self):
        """Labels with transfers must mention 'Transfers'."""
        result = explore_purchase_qty("OF02", include_transfers=True)
        for r in result["ranked"]:
            self.assertIn("Transfers", r["label"])

    def test_explore_option_type_is_explored(self):
        """option_type must be 'explored'."""
        result = explore_purchase_qty("OF02")
        for r in result["ranked"]:
            self.assertEqual(r["option_type"], "explored")

    def test_explore_scenario_id_is_null(self):
        """scenario_id must be None for explored options."""
        result = explore_purchase_qty("OF02")
        for r in result["ranked"]:
            self.assertIsNone(r["scenario_id"])

    def test_json_serialisable(self):
        result = explore_purchase_qty("OF02")
        json.dumps(result)

    def test_budget_filters_options(self):
        result = explore_purchase_qty("OF02", budget=500)
        for r in result["ranked"]:
            self.assertLessEqual(r["total_extra_cost"], 500)

    def test_ranked_options_have_actions_key(self):
        """Each ranked option must carry an 'actions' list for propose_action."""
        result = explore_purchase_qty("OF02")
        for r in result["ranked"]:
            self.assertIn("actions", r)
            self.assertIsInstance(r["actions"], list)
            self.assertTrue(len(r["actions"]) >= 1)

    def test_actions_key_with_transfers(self):
        """Actions list includes transfer actions when include_transfers=True."""
        result = explore_purchase_qty("OF02", include_transfers=True)
        for r in result["ranked"]:
            self.assertIn("actions", r)
            transfer_actions = [a for a in r["actions"] if a["type"] == "transfer"]
            self.assertTrue(len(transfer_actions) >= 1)


class TestGetOffers(unittest.TestCase):

    def test_d01_returns_component_id(self):
        result = get_offers("D01")
        self.assertEqual(result["disruption_id"], "D01")
        self.assertEqual(result["component_id"], "C01")

    def test_offers_list_nonempty(self):
        result = get_offers("D01")
        self.assertGreater(len(result["offers"]), 0)

    def test_offer_fields(self):
        result = get_offers("D01")
        for o in result["offers"]:
            self.assertIn("offer_id", o)
            self.assertIn("supplier_id", o)
            self.assertIn("lead_days", o)
            self.assertIn("unit_cost_usd", o)
            self.assertIn("min_qty", o)
            self.assertIn("max_qty", o)

    def test_all_offers_for_c01(self):
        """All returned offers must be for the C01 component."""
        result = get_offers("D01")
        for o in result["offers"]:
            self.assertEqual(o["component_id"], "C01")

    def test_unknown_disruption_raises(self):
        with self.assertRaises(ValueError):
            get_offers("D99")

    def test_json_serialisable(self):
        result = get_offers("D01")
        json.dumps(result)

    def test_is_disrupted_supplier_field_present(self):
        """Each offer must have an is_disrupted_supplier bool field."""
        result = get_offers("D01")
        for o in result["offers"]:
            self.assertIn("is_disrupted_supplier", o)
            self.assertIsInstance(o["is_disrupted_supplier"], bool)

    def test_exactly_one_disrupted_supplier(self):
        """Exactly one offer must be flagged as the disrupted supplier."""
        result = get_offers("D01")
        disrupted = [o for o in result["offers"] if o["is_disrupted_supplier"]]
        self.assertEqual(len(disrupted), 1)

    def test_disrupted_supplier_matches_po(self):
        """The flagged offer must correspond to PO01 (the disrupted PO)."""
        from engine.loader import load_all
        db = load_all()
        po = db["purchase_orders"][db["disruptions"]["D01"]["po_id"]]
        expected_offer_id = po["offer_id"]
        result = get_offers("D01")
        disrupted = [o for o in result["offers"] if o["is_disrupted_supplier"]]
        self.assertEqual(disrupted[0]["offer_id"], expected_offer_id)


class TestProposeAction(unittest.TestCase):

    def test_status_pending_approval(self):
        p = propose_action("HYBRID", "Best trade-off")
        self.assertEqual(p["status"], "pending_approval")

    def test_has_proposal_id(self):
        p = propose_action("HYBRID", "Best trade-off")
        self.assertIn("proposal_id", p)
        self.assertIsInstance(p["proposal_id"], str)
        self.assertTrue(len(p["proposal_id"]) > 0)

    def test_proposal_ids_are_unique(self):
        p1 = propose_action("HYBRID", "reason")
        p2 = propose_action("HYBRID", "reason")
        self.assertNotEqual(p1["proposal_id"], p2["proposal_id"])

    def test_has_metrics(self):
        p = propose_action("HYBRID", "reason")
        self.assertIn("metrics", p)
        self.assertIn("on_time_orders", p["metrics"])

    def test_hybrid_metrics_match(self):
        p = propose_action("HYBRID", "reason")
        self.assertEqual(p["metrics"]["on_time_orders"], 11)
        self.assertEqual(p["metrics"]["total_extra_cost"], 1306)

    def test_accepts_explicit_actions(self):
        """propose_action accepts a raw action list, not just a scenario_id."""
        actions, disruption_id = build_scenario_actions("TRANSFER", _DB)
        p = propose_action(actions, "manual transfer actions")
        self.assertEqual(p["status"], "pending_approval")
        self.assertIn("metrics", p)

    def test_json_serialisable(self):
        p = propose_action("HYBRID", "reason")
        json.dumps(p)

    def test_does_not_modify_db(self):
        """Calling propose_action must not change the inventory state."""
        import copy
        opening_before = copy.deepcopy(_DB["opening"])
        propose_action("HYBRID", "reason")
        self.assertEqual(_DB["opening"], opening_before)


if __name__ == "__main__":
    unittest.main()
