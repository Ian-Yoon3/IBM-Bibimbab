"""Tests verifying that all 5 named scenarios reproduce tests/expected/ exactly."""
import csv
import unittest
from pathlib import Path

from engine.loader import load_all
from engine.simulate import simulate, build_scenario_actions
from engine.evaluate import evaluate

# ── paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXPECTED = _REPO_ROOT / "tests" / "expected"

# Load once for all tests
_DB = load_all()

# ── helpers ────────────────────────────────────────────────────────────────────

def _load_expected_summary() -> dict:
    """Return {scenario_id: row_dict} from tests/expected/scenario_summary.csv."""
    result = {}
    with (_EXPECTED / "scenario_summary.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            result[row["scenario_id"]] = row
    return result


def _load_expected_order_results() -> dict:
    """Return {(scenario_id, order_id): row_dict} from tests/expected/order_results.csv."""
    result = {}
    with (_EXPECTED / "order_results.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            result[(row["scenario_id"], row["order_id"])] = row
    return result


_EXPECTED_SUMMARY = _load_expected_summary()
_EXPECTED_ORDER_RESULTS = _load_expected_order_results()

SCENARIO_IDS = ["NORMAL", "WAIT", "TRANSFER", "ALT_BUY", "HYBRID"]


def _run(scenario_id: str):
    actions, disruption_id = build_scenario_actions(scenario_id, _DB)
    sim = simulate(actions, disruption_id, _DB)
    kpi = evaluate(sim)
    return sim, kpi


# ── scenario summary tests ─────────────────────────────────────────────────────

class TestScenarioSummary(unittest.TestCase):
    """Compare evaluate() output against tests/expected/scenario_summary.csv."""

    def _check(self, scenario_id: str):
        _, kpi = _run(scenario_id)
        exp = _EXPECTED_SUMMARY[scenario_id]

        self.assertEqual(
            kpi["on_time_orders"], int(exp["on_time_orders"]),
            f"{scenario_id}: on_time_orders"
        )
        self.assertEqual(
            kpi["on_time_units"], int(exp["on_time_units"]),
            f"{scenario_id}: on_time_units"
        )
        self.assertEqual(
            kpi["orders_completed_by_horizon"], int(exp["orders_completed_by_horizon"]),
            f"{scenario_id}: orders_completed_by_horizon"
        )
        self.assertEqual(
            kpi["total_order_days_late"], int(exp["total_order_days_late"]),
            f"{scenario_id}: total_order_days_late"
        )
        self.assertEqual(
            kpi["max_order_days_late"], int(exp["max_order_days_late"]),
            f"{scenario_id}: max_order_days_late"
        )
        self.assertEqual(
            kpi["purchase_cost"], int(exp["extra_purchase_usd"]),
            f"{scenario_id}: purchase_cost (extra_purchase_usd)"
        )
        self.assertEqual(
            kpi["transfer_cost"], int(exp["transfer_usd"]),
            f"{scenario_id}: transfer_cost (transfer_usd)"
        )
        self.assertEqual(
            kpi["total_extra_cost"], int(exp["total_extra_usd"]),
            f"{scenario_id}: total_extra_cost (total_extra_usd)"
        )
        # End C01 inventory per warehouse (sorted warehouse order WH01, WH02, WH03)
        self.assertEqual(
            kpi["end_c01"]["WH01"], int(exp["wh01_c01_end_qty"]),
            f"{scenario_id}: end_c01 WH01"
        )
        self.assertEqual(
            kpi["end_c01"]["WH02"], int(exp["wh02_c01_end_qty"]),
            f"{scenario_id}: end_c01 WH02"
        )
        self.assertEqual(
            kpi["end_c01"]["WH03"], int(exp["wh03_c01_end_qty"]),
            f"{scenario_id}: end_c01 WH03"
        )

    def test_NORMAL(self):
        self._check("NORMAL")

    def test_WAIT(self):
        self._check("WAIT")

    def test_TRANSFER(self):
        self._check("TRANSFER")

    def test_ALT_BUY(self):
        self._check("ALT_BUY")

    def test_HYBRID(self):
        self._check("HYBRID")


# ── order results tests ────────────────────────────────────────────────────────

class TestOrderResults(unittest.TestCase):
    """Compare per-order start/delivery/late vs tests/expected/order_results.csv."""

    def _check(self, scenario_id: str):
        sim, _ = _run(scenario_id)
        order_ids = [r["order_id"] for r in sim["order_results"]]
        # Queue must be SO01..SO12
        self.assertEqual(
            order_ids,
            [f"SO{i:02d}" for i in range(1, 13)],
            f"{scenario_id}: queue order"
        )
        for row in sim["order_results"]:
            oid = row["order_id"]
            exp = _EXPECTED_ORDER_RESULTS[(scenario_id, oid)]
            self.assertEqual(
                row["product_id"], exp["product_id"],
                f"{scenario_id}/{oid}: product_id"
            )
            self.assertEqual(
                row["qty"], int(exp["qty"]),
                f"{scenario_id}/{oid}: qty"
            )
            self.assertEqual(
                row["due_date"], exp["due_date"],
                f"{scenario_id}/{oid}: due_date"
            )
            self.assertEqual(
                row["c01_required"], int(exp["c01_required"]),
                f"{scenario_id}/{oid}: c01_required"
            )
            self.assertEqual(
                row["start_date"], exp["start_date"],
                f"{scenario_id}/{oid}: start_date"
            )
            self.assertEqual(
                row["delivery_date"], exp["delivery_date"],
                f"{scenario_id}/{oid}: delivery_date"
            )
            self.assertEqual(
                row["days_late"], int(exp["days_late"]),
                f"{scenario_id}/{oid}: days_late"
            )

    def test_NORMAL(self):
        self._check("NORMAL")

    def test_WAIT(self):
        self._check("WAIT")

    def test_TRANSFER(self):
        self._check("TRANSFER")

    def test_ALT_BUY(self):
        self._check("ALT_BUY")

    def test_HYBRID(self):
        self._check("HYBRID")


if __name__ == "__main__":
    unittest.main()
