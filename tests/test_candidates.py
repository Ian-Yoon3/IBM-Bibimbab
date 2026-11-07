"""Tests for engine/candidates.py."""
import unittest

from engine.loader import load_all
from engine.candidates import transferable_qty, purchase_qty_options

_DB = load_all()


class TestTransferableQty(unittest.TestCase):

    def test_c01_lanes_count(self):
        """There should be exactly 2 lanes (LN01 and LN02) into WH01."""
        result = transferable_qty("C01", _DB)
        self.assertEqual(len(result), 2)
        lane_ids = {r["lane_id"] for r in result}
        self.assertEqual(lane_ids, {"LN01", "LN02"})

    def test_ln01_c01_equals_18(self):
        """WH02 → WH01: on_hand=25, reserved=3, protected=4 → avail=18; max=18 → 18."""
        result = {r["lane_id"]: r for r in transferable_qty("C01", _DB)}
        self.assertEqual(result["LN01"]["transferable_qty"], 18)
        self.assertEqual(result["LN01"]["available_at_source"], 18)
        self.assertEqual(result["LN01"]["lane_max_qty"], 18)

    def test_ln02_c01_equals_14(self):
        """WH03 → WH01: on_hand=22, reserved=2, protected=6 → avail=14; max=14 → 14."""
        result = {r["lane_id"]: r for r in transferable_qty("C01", _DB)}
        self.assertEqual(result["LN02"]["transferable_qty"], 14)
        self.assertEqual(result["LN02"]["available_at_source"], 14)
        self.assertEqual(result["LN02"]["lane_max_qty"], 14)

    def test_unknown_component_raises(self):
        with self.assertRaises(ValueError):
            transferable_qty("C99", _DB)


class TestPurchaseQtyOptions(unittest.TestCase):

    def test_of02_count(self):
        """OF02: min=20, max=65, step=5 → 10 valid quantities."""
        result = purchase_qty_options("OF02", _DB)
        self.assertEqual(len(result["valid_quantities"]), 10)

    def test_of02_bounds(self):
        """OF02 valid quantities must include 20 and 65."""
        result = purchase_qty_options("OF02", _DB)
        self.assertIn(20, result["valid_quantities"])
        self.assertIn(65, result["valid_quantities"])

    def test_of02_full_list(self):
        """OF02 valid quantities = [20, 25, 30, 35, 40, 45, 50, 55, 60, 65]."""
        result = purchase_qty_options("OF02", _DB)
        self.assertEqual(
            result["valid_quantities"],
            [20, 25, 30, 35, 40, 45, 50, 55, 60, 65],
        )

    def test_of02_metadata(self):
        result = purchase_qty_options("OF02", _DB)
        self.assertEqual(result["offer_id"], "OF02")
        self.assertEqual(result["component_id"], "C01")
        self.assertEqual(result["lead_days"], 3)
        self.assertEqual(result["unit_cost_usd"], 18)
        self.assertEqual(result["fixed_fee_usd"], 80)

    def test_unknown_offer_raises(self):
        with self.assertRaises(ValueError):
            purchase_qty_options("OF99", _DB)


if __name__ == "__main__":
    unittest.main()
