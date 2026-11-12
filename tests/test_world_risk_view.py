"""Tests for world_risk_view, check_explanation, build_world_risk_message,
parse_world_risk_answer and get_overview.

Expected numbers were computed in advance.  If one does not match, the test
reports the difference and stops without modifying the expected values.
"""

import json
import unittest

from agent.overview import get_overview
from agent.prompts import build_world_risk_message
from agent.render import (
    SUGGESTED_QUESTIONS,
    check_explanation,
    is_world_risk_question,
    parse_world_risk_answer,
    world_risk_view,
    _build_world_risk_md_no_exp,
    _t,
    _catalog,
    situation_text,
)
from engine.worlds import evaluate_worlds
from engine.loader import load_all


def _md_no_exp(view, disruption_id="D01"):
    """Return the view markdown without the 'What this means' section."""
    wr = _t.get_world_risk(disruption_id)
    cat = _catalog()
    cat["_disruptions"] = [disruption_id]
    sit = situation_text(disruption_id, cat)
    scope = wr["scope_note"]
    rows = view["rows"]
    budget = view["settings"]["budget"]
    focus_date = view["focus_date"]
    reading = view["reading"]
    return _build_world_risk_md_no_exp(
        view["mode"], sit, scope, reading, rows, wr, budget, focus_date,
        disruption_id
    )


class TestOverview(unittest.TestCase):
    """(a) Overview mode."""

    @classmethod
    def setUpClass(cls):
        cls.view = get_overview()

    def test_a_type_and_mode(self):
        self.assertEqual(self.view["type"], "world_risk")
        self.assertEqual(self.view["mode"], "overview")

    def test_a_no_what_this_means(self):
        self.assertNotIn("## What this means", self.view["markdown"])

    def test_a_explanation_none(self):
        self.assertIsNone(self.view["explanation"])

    def test_a_explanation_status_none(self):
        self.assertIsNone(self.view["explanation_status"])

    def test_a_four_suggested_questions(self):
        self.assertEqual(len(self.view["suggested_questions"]), 4)

    def test_a_suggested_questions_are_world_risk(self):
        for q in self.view["suggested_questions"]:
            self.assertTrue(
                is_world_risk_question(q),
                msg=f"Suggested question not routed as world_risk: {q!r}"
            )

    def test_a_get_overview_equals_world_risk_view(self):
        direct = world_risk_view("overview")
        self.assertEqual(get_overview(), direct)


class TestRows(unittest.TestCase):
    """(b) Row values match get_world_risk options."""

    @classmethod
    def setUpClass(cls):
        cls.view = world_risk_view("overview")
        cls.rows = {r["scenario_id"]: r for r in cls.view["rows"]}

    def _check(self, sid, exp_exp, exp_p90, exp_worst, exp_pno, exp_cost):
        r = self.rows[sid]
        for attr, got, want in [
            ("expected_late_orders", r["expected_late_orders"], exp_exp),
            ("p90_late_orders",      r["p90_late_orders"],      exp_p90),
            ("worst_late_orders",    r["worst_late_orders"],    exp_worst),
            ("p_no_late_pct",        r["p_no_late_pct"],        exp_pno),
            ("extra_cost",           r["extra_cost"],           exp_cost),
        ]:
            if got != want:
                self.fail(
                    f"test_b: {sid} {attr}: expected {want!r}, got {got!r}"
                )

    def test_b_wait(self):
        self._check("WAIT",     6.53, 10, 11, 1.4,  0)

    def test_b_transfer(self):
        self._check("TRANSFER", 3.73,  7,  8, 5.6,  416)

    def test_b_alt_buy(self):
        self._check("ALT_BUY",  2.99,  6,  7, 1.4,  1250)

    def test_b_hybrid(self):
        self._check("HYBRID",   1.36,  4,  5, 35.0, 1306)


class TestDateMode(unittest.TestCase):
    """(c) Date mode."""

    def test_c_3_days_late_focus_date(self):
        v = world_risk_view("date", "What if the supplier is 3 days late?")
        self.assertEqual(v["focus_date"], "2026-11-14")
        rows = {r["scenario_id"]: r for r in v["rows"]}
        for sid, want in [("WAIT", 4), ("TRANSFER", 1), ("ALT_BUY", 1), ("HYBRID", 0)]:
            got = rows[sid]["late_at_focus"]
            if got != want:
                self.fail(f"test_c: {sid} late_at_focus: expected {want}, got {got}")

    def test_c_3_days_late_reading_in_markdown(self):
        v = world_risk_view("date", "What if the supplier is 3 days late?")
        self.assertIn("Read as: PO01 arrives on Nov 14.", v["markdown"])
        # Rule line present (not explicit)
        self.assertIn("N days late", v["markdown"])

    def test_c_nov19_focus(self):
        v = world_risk_view("date", "What if PO01 arrives on Nov 19?")
        self.assertEqual(v["focus_date"], "2026-11-19")
        rows = {r["scenario_id"]: r for r in v["rows"]}
        for sid, want in [("WAIT", 10), ("TRANSFER", 7), ("ALT_BUY", 6), ("HYBRID", 4)]:
            got = rows[sid]["late_at_focus"]
            if got != want:
                self.fail(f"test_c: {sid} late_at_focus Nov19: expected {want}, got {got}")

    def test_c_nov19_no_rule_line(self):
        """Explicit date: no counting-rule line in the reading section."""
        v = world_risk_view("date", "What if PO01 arrives on Nov 19?")
        # reading has only one line
        self.assertEqual(len(v["reading"]), 1)

    def test_c_two_weeks_raises(self):
        """After-window date raises ValueError."""
        with self.assertRaises(ValueError):
            world_risk_view("date", "Suppose the shipment slips by two weeks.")


class TestBudget(unittest.TestCase):
    """(d) Budget column."""

    def test_d_budget_500(self):
        v = world_risk_view("general", "Our budget is $500. How risky is each option?")
        rows = {r["scenario_id"]: r for r in v["rows"]}
        expected = {"WAIT": True, "TRANSFER": True, "ALT_BUY": False, "HYBRID": False}
        for sid, want in expected.items():
            got = rows[sid]["within_budget"]
            self.assertEqual(got, want,
                             msg=f"within_budget {sid}: expected {want}, got {got}")
        self.assertIn("Within $500", v["markdown"])

    def test_d_no_budget_all_none(self):
        v = world_risk_view("general", "How risky is each option?")
        for r in v["rows"]:
            self.assertIsNone(r["within_budget"],
                              msg=f"{r['scenario_id']} within_budget should be None")
        self.assertNotIn("Within budget", v["markdown"])


class TestExplanation(unittest.TestCase):
    """(e) Explanation slot and check_explanation."""

    @classmethod
    def setUpClass(cls):
        cls.v = world_risk_view("general")
        cls.md_no = _md_no_exp(cls.v)

    def test_e_good_text_ok(self):
        text = "HYBRID has an expected 1.36 late orders and TRANSFER costs 416."
        ok, reason = check_explanation(text, self.md_no)
        self.assertTrue(ok, msg=f"Expected ok, got: {reason}")

    def test_e_bad_number_dropped(self):
        ok, _ = check_explanation("Expected late orders for WAIT is 6.5.", self.md_no)
        self.assertFalse(ok)

    def test_e_bad_code_normal_dropped(self):
        ok, _ = check_explanation("NORMAL has zero late orders.", self.md_no)
        self.assertFalse(ok)

    def test_e_five_sentences_dropped(self):
        ok, _ = check_explanation("One. Two. Three. Four. Five.", self.md_no)
        self.assertFalse(ok)

    def test_e_35pct_accepted(self):
        """'35%' matches '35.0%' in the view."""
        ok, reason = check_explanation(
            "HYBRID has a 35% chance of no late orders.", self.md_no
        )
        self.assertTrue(ok, msg=f"Expected ok, got: {reason}")

    def test_e_dollar_1306_accepted(self):
        text = "HYBRID costs $1,306."
        ok, reason = check_explanation(text, self.md_no)
        self.assertTrue(ok, msg=f"Expected ok, got: {reason}")

    def test_e_explanation_shown_when_ok(self):
        text = "HYBRID has 1.36 expected late orders."
        v = world_risk_view("general", explanation=text)
        self.assertEqual(v["explanation_status"], "ok")
        self.assertIn(text, v["markdown"])

    def test_e_explanation_dropped_on_bad_number(self):
        text = "WAIT has 6.5 expected late orders."
        v = world_risk_view("general", explanation=text)
        self.assertEqual(v["explanation_status"], "dropped")
        self.assertIn("not shown", v["markdown"])

    def test_e_explanation_unavailable_when_none(self):
        v = world_risk_view("general", explanation=None)
        self.assertEqual(v["explanation_status"], "unavailable")
        self.assertIn("unavailable", v["markdown"])


class TestBuildWorldRiskMessage(unittest.TestCase):
    """(f) build_world_risk_message content."""

    @classmethod
    def setUpClass(cls):
        cls.v = world_risk_view("general", "How risky is each option?")
        cls.msg = build_world_risk_message(
            "How risky is each option?", cls.v
        )

    def test_f_role_user(self):
        self.assertEqual(self.msg["role"], "user")

    def test_f_contains_user_message(self):
        self.assertIn("How risky is each option?", self.msg["content"])

    def test_f_contains_time_cost_table(self):
        self.assertIn("Time and cost by option", self.msg["content"])

    def test_f_contains_at_most_three_numbers(self):
        self.assertIn("at most three numbers", self.msg["content"])

    def test_f_contains_at_most_4_sentences(self):
        self.assertIn("at most 4 sentences", self.msg["content"])

    def test_f_contains_do_not_compute(self):
        self.assertIn("Do not compute", self.msg["content"])

    def test_f_contains_column_meanings(self):
        self.assertIn("Column meanings", self.msg["content"])

    def test_f_date_mode_nov19_contains_late_if_nov19(self):
        """In date mode for Nov 19 the message names the focus column."""
        v_date = world_risk_view("date", "What if PO01 arrives on Nov 19?")
        msg_date = build_world_risk_message("What if PO01 arrives on Nov 19?", v_date)
        self.assertIn("Late if it arrives Nov 19", msg_date["content"])

    def test_f_budget_500_explanation_accepted(self):
        """$500 from user_message is allowed by check_explanation."""
        from agent.render import check_explanation, _build_world_risk_md_no_exp, _t, _catalog, situation_text
        q = "Our budget is $500. How risky is each option?"
        v = world_risk_view("general", q)
        wr = _t.get_world_risk("D01")
        cat = _catalog()
        cat["_disruptions"] = ["D01"]
        sit = situation_text("D01", cat)
        view_md = _build_world_risk_md_no_exp(
            v["mode"], sit, wr["scope_note"], v["reading"], v["rows"],
            wr, v["settings"]["budget"], v["focus_date"], "D01"
        )
        text = (
            "The WAIT option has 6.53 expected late orders and costs $0, while the "
            "TRANSFER option has 3.73 expected late orders and costs $416. The ALT_BUY option "
            "has 2.99 expected late orders but is not within the budget of $500. The HYBRID "
            "option has the lowest expected late orders at 1.36, but also exceeds the budget "
            "at $1,306."
        )
        ok, reason = check_explanation(text, view_md + "\n" + q)
        self.assertTrue(ok, msg=f"Expected ok, got: {reason}")


class TestParseWorldRiskAnswer(unittest.TestCase):
    """(g) parse_world_risk_answer."""

    def test_g_strips_answer_label(self):
        self.assertEqual(parse_world_risk_answer("Answer: Text."), "Text.")

    def test_g_no_label_unchanged(self):
        self.assertEqual(parse_world_risk_answer("Text."), "Text.")


class TestJsonSerializable(unittest.TestCase):
    """(h) View passes json.dumps."""

    def test_h_overview_serialisable(self):
        v = world_risk_view("overview")
        try:
            json.dumps(v)
        except (TypeError, ValueError) as exc:
            self.fail(f"overview view is not JSON-serialisable: {exc}")

    def test_h_general_serialisable(self):
        v = world_risk_view("general")
        try:
            json.dumps(v)
        except (TypeError, ValueError) as exc:
            self.fail(f"general view is not JSON-serialisable: {exc}")

    def test_h_date_serialisable(self):
        v = world_risk_view("date", "What if the supplier is 3 days late?")
        try:
            json.dumps(v)
        except (TypeError, ValueError) as exc:
            self.fail(f"date view is not JSON-serialisable: {exc}")


class TestFourFixes(unittest.TestCase):
    """Tests for the four follow-up fixes."""

    # Fix 1: check_explanation sentence counting with decimals
    def test_fix1_three_sentences_with_decimals_ok(self):
        v = world_risk_view("general")
        md_no = _md_no_exp(v)
        text = (
            "ALT_BUY expects 2.99 late orders and TRANSFER 3.73. "
            "HYBRID expects 1.36 and WAIT 6.53. "
            "Only HYBRID has a 35.0% chance of no late order."
        )
        ok, reason = check_explanation(text, md_no)
        self.assertTrue(ok, msg=f"Expected ok, got: {reason}")

    # Fix 2: option cells show "<name> (<code>)"
    def test_fix2_time_cost_table_has_codes_in_parens(self):
        v = world_risk_view("general")
        md = v["markdown"]
        # Extract the time-and-cost table section
        start = md.find("## Time and cost by option")
        end = md.find("\n## ", start + 1)
        table = md[start:end]
        for r in v["rows"]:
            self.assertIn(f"({r['code']})", table,
                          msg=f"Code {r['code']!r} not in parens in time-cost table")

    def test_fix2_late_orders_table_has_codes_in_parens(self):
        v = world_risk_view("general")
        md = v["markdown"]
        start = md.find("## Late orders by receipt date")
        end = md.find("\n## ", start + 1)
        table = md[start:end]
        for r in v["rows"]:
            self.assertIn(f"({r['code']})", table,
                          msg=f"Code {r['code']!r} not in parens in late-orders table")

    # Fix 3: heading order
    def test_fix3_heading_order_general(self):
        v = world_risk_view("general", explanation="HYBRID has 1.36 expected late orders.")
        md = v["markdown"]
        headings = [line[3:] for line in md.splitlines() if line.startswith("## ")]
        expected = [
            "Situation",
            "Time and cost by option",
            "Late orders by receipt date",
            "Trade-offs",
            "What this means",
            "Notes",
            "Next step",
        ]
        self.assertEqual(headings, expected,
                         msg=f"Heading order wrong: {headings}")

    def test_fix3_heading_order_date(self):
        v = world_risk_view("date", "What if the supplier is 3 days late?",
                            explanation="HYBRID has 1.36 expected late orders.")
        md = v["markdown"]
        headings = [line[3:] for line in md.splitlines() if line.startswith("## ")]
        expected = [
            "Situation",
            "Reading",
            "Time and cost by option",
            "Late orders by receipt date",
            "Trade-offs",
            "What this means",
            "Notes",
            "Next step",
        ]
        self.assertEqual(headings, expected,
                         msg=f"Heading order wrong in date mode: {headings}")

    def test_fix3_overview_no_what_this_means(self):
        v = world_risk_view("overview")
        md = v["markdown"]
        self.assertNotIn("## What this means", md)

    # Fix 4: Situation section contains scope_note
    def test_fix4_overview_markdown_contains_scope_note(self):
        v = world_risk_view("overview")
        scope = v["scope_note"]
        self.assertIn(scope, v["markdown"],
                      msg="scope_note not found in overview markdown")


class TestLoopIntegration(unittest.TestCase):
    """Step 8 integration tests via run_agent with ScriptedLLM."""

    def _tc(self, i, name, **args):
        return {"tool_calls": [{"id": str(i), "name": name, "args": args}]}

    # (a) "3 days late" -> world_risk date mode, focus 2026-11-14
    def test_a_3_days_late_world_risk_date(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        r = run_agent(
            "What if the supplier is 3 days late instead?",
            llm=ScriptedLLM([
                self._tc(1, "get_disruption", disruption_id="D01"),
                {"content": "gathered"},
                {"content": "Answer: HYBRID has 0 late orders at focus date."},
            ])
        )
        self.assertEqual(r["view"]["type"], "world_risk")
        self.assertEqual(r["view"]["mode"], "date")
        self.assertEqual(r["view"]["focus_date"], "2026-11-14")

    # (b) Explanation acceptance and failing LLM
    def test_b_explanation_ok(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        r = run_agent(
            "How risky is each option?",
            llm=ScriptedLLM([
                {"content": "gathered"},
                {"content": "Answer: HYBRID has 1.36 expected late orders."},
            ])
        )
        self.assertEqual(r["view"]["type"], "world_risk")
        self.assertEqual(r["view"]["explanation_status"], "ok")

    def test_b_failing_llm_explanation_unavailable(self):
        from agent.loop import run_agent

        class _FailOnNarrative:
            n = 0
            def chat(self, messages, tools):
                self.n += 1
                if self.n == 1:
                    return {"content": "gathered", "tool_calls": []}
                raise ConnectionError("narrative fail")

        r = run_agent("How risky is each option?", llm=_FailOnNarrative())
        # Must not raise; explanation is unavailable
        self.assertEqual(r["view"]["type"], "world_risk")
        self.assertEqual(r["view"]["explanation_status"], "unavailable")

    # (c) "two weeks" -> unsupported, reading line about Nov 25
    def test_c_two_weeks_unsupported(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        r = run_agent(
            "Suppose the shipment slips by two weeks.",
            llm=ScriptedLLM([
                self._tc(1, "get_disruption", disruption_id="D01"),
                {"content": "gathered"},
                {"content": "(replayed)"},
            ])
        )
        self.assertEqual(r["view"]["type"], "unsupported")
        self.assertIn("Nov 25 is after the last simulated day (Nov 21).", r["answer"])

    # (d) ambiguous -> world_risk general
    def test_d_ambiguous_world_risk_general(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        r = run_agent(
            "What if it is 3 days late or 5 days late?",
            llm=ScriptedLLM([
                {"content": "gathered"},
                {"content": "Answer: HYBRID has 1.36 expected late orders."},
            ])
        )
        self.assertEqual(r["view"]["type"], "world_risk")
        self.assertEqual(r["view"]["mode"], "general")

    # (e) "What should we do?" stays recommendation
    def test_e_recommendation_unchanged(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        r = run_agent(
            "What should we do?",
            llm=ScriptedLLM([
                {"tool_calls": [{"id": "1", "name": "compare_scenarios", "args": {}}]},
                {"content": "gathered"},
                {"content": "Recommendation: TRANSFER.\nTrade-offs:\n- HYBRID costs more"},
            ])
        )
        self.assertEqual(r["view"]["type"], "recommendation")

    # (f) Fixture questions keep their saved view type (using _choose_view only)
    def test_f_fixture_view_types(self):
        import json
        from pathlib import Path
        from agent.loop import _choose_view

        fixture_path = (
            Path(__file__).parent.parent / "ui_fixtures" / "agent_results.json"
        )
        fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        two_world_risk = {
            "What if the supplier is 3 days late instead?",
            "The supplier says it will arrive 2 days earlier. What changes?",
        }
        for f in fixtures:
            if f.get("conversation") == "error":
                continue
            q = f["question"]
            expected_type = (f["result"].get("view") or {}).get("type")
            tool_trace = f["result"].get("tool_trace", [])
            proposal = f["result"].get("proposal")
            view = _choose_view(q, tool_trace, proposal)
            got_type = (view or {}).get("type") if view else None
            if q in two_world_risk:
                # These now return world_risk instead of the old fixture type
                self.assertEqual(got_type, "world_risk",
                                 msg=f"{q!r}: expected world_risk, got {got_type!r}")
            else:
                self.assertEqual(got_type, expected_type,
                                 msg=f"{q!r}: expected {expected_type!r}, got {got_type!r}")


if __name__ == "__main__":
    unittest.main()
