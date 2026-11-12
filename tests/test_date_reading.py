"""Tests for agent/render.py receipt-date reading functions.

Expected results were computed in advance.  If one does not match, the test
reports the difference and stops without modifying the expected values.
"""

import json
import pathlib
import unittest

from agent.render import (
    is_world_risk_question,
    reading_lines,
    resolve_receipt_date,
)

_FIXTURES = pathlib.Path(__file__).parent.parent / "ui_fixtures" / "agent_results.json"


def _check(test, msg, exp_date=None, exp_basis=None, exp_status=None):
    """Assert resolve_receipt_date gives exactly exp_date, exp_basis, exp_status."""
    r = resolve_receipt_date(msg)
    if r is None:
        test.fail(
            f"resolve_receipt_date returned None for {msg!r}; "
            f"expected date={exp_date} basis={exp_basis} status={exp_status}"
        )
    got_date = r.get("date")
    got_basis = r.get("basis")
    got_status = r.get("status")
    if (got_date, got_basis, got_status) != (exp_date, exp_basis, exp_status):
        test.fail(
            f"resolve_receipt_date({msg!r}):\n"
            f"  expected date={exp_date!r} basis={exp_basis!r} status={exp_status!r}\n"
            f"  got     date={got_date!r} basis={got_basis!r} status={got_status!r}"
        )


class TestResolveReceiptDate(unittest.TestCase):

    # ── in-window cases ────────────────────────────────────────────────────────

    def test_3_days_late(self):
        _check(self,
               "What if the supplier is 3 days late instead?",
               "2026-11-14", "original", "in_window")

    def test_2_days_earlier(self):
        _check(self,
               "The supplier says it will arrive 2 days earlier. What changes?",
               "2026-11-15", "announced", "in_window")

    def test_delay_becomes_8_days(self):
        _check(self,
               "What if the delay becomes 8 days?",
               "2026-11-19", "original", "in_window")

    def test_delay_becomes_10_days(self):
        _check(self,
               "What if the delay becomes 10 days?",
               "2026-11-21", "original", "in_window")

    def test_slips_2_more_days(self):
        _check(self,
               "What if it slips 2 more days?",
               "2026-11-19", "announced", "in_window")

    def test_explicit_mm_dd(self):
        _check(self,
               "What if PO01 arrives on 11-19?",
               "2026-11-19", "explicit", "in_window")

    def test_explicit_month_name(self):
        _check(self,
               "What if it arrives on Nov 20?",
               "2026-11-20", "explicit", "in_window")

    # ── special statuses ──────────────────────────────────────────────────────

    def test_two_weeks_after_window(self):
        _check(self,
               "Suppose the shipment slips by two weeks.",
               "2026-11-25", "original", "after_window")

    def test_6_days_equals_announced(self):
        _check(self,
               "If the delay is 6 days, what should we do?",
               "2026-11-17", "original", "announced")

    def test_10_days_earlier_before_original(self):
        _check(self,
               "What if it arrives 10 days earlier?",
               "2026-11-07", "announced", "before_original")

    # ── other_variable ────────────────────────────────────────────────────────

    def test_other_variable_transfer(self):
        r = resolve_receipt_date("What if the transfer takes 2 days longer?")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("status"), "other_variable",
                         msg=f"Expected other_variable, got {r!r}")

    # ── ambiguous ─────────────────────────────────────────────────────────────

    def test_ambiguous_two_durations(self):
        r = resolve_receipt_date("What if it is 3 days late or 5 days late?")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("status"), "ambiguous",
                         msg=f"Expected ambiguous, got {r!r}")

    # ── None cases ────────────────────────────────────────────────────────────

    def test_none_order_id(self):
        r = resolve_receipt_date("Why is SO08 2 days late?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    def test_none_orders_threshold(self):
        r = resolve_receipt_date(
            "Which orders are more than 3 days late if we wait?"
        )
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    def test_none_budget_question(self):
        r = resolve_receipt_date("Our budget is 500 dollars. What should we do?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    def test_none_disruption_d02(self):
        r = resolve_receipt_date("What happens with disruption D02?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")


class TestReadingLines(unittest.TestCase):

    def test_reading_lines_3_days_late(self):
        """3 days late: two lines — the read-as line and the counting rule."""
        r = resolve_receipt_date("What if the supplier is 3 days late instead?")
        lines = reading_lines(r)
        self.assertEqual(len(lines), 2,
                         msg=f"Expected 2 lines, got {len(lines)}: {lines!r}")
        self.assertEqual(lines[0], "Read as: PO01 arrives on 11-14.")
        # Second line contains both counting rules
        self.assertIn("11-11", lines[1])
        self.assertIn("11-17", lines[1])

    def test_reading_lines_explicit_one_line(self):
        """Explicit date: only the read-as line (no counting rule)."""
        r = resolve_receipt_date("What if PO01 arrives on 11-19?")
        lines = reading_lines(r)
        self.assertEqual(len(lines), 1,
                         msg=f"Expected 1 line, got {len(lines)}: {lines!r}")
        self.assertEqual(lines[0], "Read as: PO01 arrives on 11-19.")

    def test_reading_lines_two_weeks_three_lines(self):
        """Two weeks: three lines — read-as, counting rule, and after-window note."""
        r = resolve_receipt_date("Suppose the shipment slips by two weeks.")
        lines = reading_lines(r)
        self.assertEqual(len(lines), 3,
                         msg=f"Expected 3 lines, got {len(lines)}: {lines!r}")
        self.assertEqual(lines[0], "Read as: PO01 arrives on 11-25.")
        # Third line mentions 11-25 and 11-21 (last simulated day)
        self.assertIn("11-25", lines[2])
        self.assertIn("11-21", lines[2])

    def test_reading_lines_empty_for_other_variable(self):
        r = {"status": "other_variable"}
        self.assertEqual(reading_lines(r), [])

    def test_reading_lines_empty_for_ambiguous(self):
        r = {"status": "ambiguous"}
        self.assertEqual(reading_lines(r), [])


class TestIsWorldRiskQuestion(unittest.TestCase):

    # ── True cases ────────────────────────────────────────────────────────────

    def test_true_3_days_late(self):
        self.assertTrue(
            is_world_risk_question("What if the supplier is 3 days late instead?")
        )

    def test_true_2_days_earlier(self):
        self.assertTrue(
            is_world_risk_question(
                "The supplier says it will arrive 2 days earlier. What changes?"
            )
        )

    def test_true_delay_8_days(self):
        self.assertTrue(
            is_world_risk_question("What if the delay becomes 8 days?")
        )

    def test_true_delay_10_days(self):
        self.assertTrue(
            is_world_risk_question("What if the delay becomes 10 days?")
        )

    def test_true_slips_2_more_days(self):
        self.assertTrue(is_world_risk_question("What if it slips 2 more days?"))

    def test_true_uncertain_po01(self):
        self.assertTrue(
            is_world_risk_question(
                "How risky is each option if PO01's arrival date is uncertain?"
            )
        )

    def test_true_chance_transfer(self):
        self.assertTrue(
            is_world_risk_question(
                "What is the chance of no late orders with TRANSFER?"
            )
        )

    def test_true_risky_wait(self):
        self.assertTrue(is_world_risk_question("Is waiting too risky?"))

    def test_true_likely_hybrid(self):
        self.assertTrue(
            is_world_risk_question(
                "How likely is HYBRID to keep every order on time?"
            )
        )

    def test_true_worst_case_alt_buy(self):
        self.assertTrue(
            is_world_risk_question("What is the worst case for ALT_BUY?")
        )

    # ── False cases ───────────────────────────────────────────────────────────

    def test_false_customers_at_risk(self):
        self.assertFalse(
            is_world_risk_question("Which customers are at risk if we wait?")
        )

    def test_false_order_at_risk(self):
        self.assertFalse(
            is_world_risk_question("Is SO05 at risk under TRANSFER?")
        )

    def test_false_delay_6_days(self):
        self.assertFalse(
            is_world_risk_question("If the delay is 6 days, what should we do?")
        )

    def test_false_two_weeks_after_window(self):
        self.assertFalse(
            is_world_risk_question("Suppose the shipment slips by two weeks.")
        )

    def test_false_other_variable(self):
        self.assertFalse(
            is_world_risk_question("What if the transfer takes 2 days longer?")
        )

    # ── Fixture questions ─────────────────────────────────────────────────────

    def test_fixture_questions(self):
        """All fixture questions return False except the two hypothetical-delay ones."""
        with open(_FIXTURES, encoding="utf-8") as f:
            data = json.load(f)

        true_set = {
            "What if the supplier is 3 days late instead?",
            "The supplier says it will arrive 2 days earlier. What changes?",
        }
        failures = []
        for item in data:
            q = item["question"]
            expected = q in true_set
            got = is_world_risk_question(q)
            if got != expected:
                failures.append(
                    f"  {q!r}: expected {expected}, got {got}"
                )
        if failures:
            self.fail(
                "is_world_risk_question fixture mismatches:\n"
                + "\n".join(failures)
            )


class TestNumericRangeFix(unittest.TestCase):
    """Numeric ranges and fractions must not be read as dates."""

    # ── resolve_receipt_date returns None ─────────────────────────────────────

    def test_range_days_returns_none(self):
        r = resolve_receipt_date("What if the supplier is 3-4 days late?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    def test_fraction_order_returns_none(self):
        r = resolve_receipt_date("What if the supplier ships 1/2 of the order?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    def test_range_units_returns_none(self):
        r = resolve_receipt_date("Can the supplier deliver 10-12 units early?")
        self.assertIsNone(r, msg=f"Expected None, got {r!r}")

    # ── is_world_risk_question returns False ──────────────────────────────────

    def test_range_days_not_world_risk(self):
        self.assertFalse(
            is_world_risk_question("What if the supplier is 3-4 days late?")
        )

    def test_fraction_order_not_world_risk(self):
        self.assertFalse(
            is_world_risk_question("What if the supplier ships 1/2 of the order?")
        )

    def test_range_units_not_world_risk(self):
        self.assertFalse(
            is_world_risk_question("Can the supplier deliver 10-12 units early?")
        )

    # ── valid explicit dates still work ──────────────────────────────────────

    def test_explicit_slash_still_works(self):
        """11/19 with announced month 11 still resolves to 2026-11-19."""
        _check(self,
               "What if it arrives on 11/19?",
               "2026-11-19", "explicit", "in_window")

    def test_month_name_dec_1(self):
        """Dec 1 resolves to 2026-12-01 (after window)."""
        _check(self,
               "What if it arrives on Dec 1?",
               "2026-12-01", "explicit", "after_window")


if __name__ == "__main__":
    unittest.main()
