"""Comparison claims in AI-written text (agent/claims.py).

The sentences in REAL_* are taken from recorded model answers
(eval_results/sweep_*.json).  The tables are written out here, so the tests do
not depend on the demo data; RandomTables checks the same wording against
tables with random values.
"""
import random
import unittest

from agent import claims
from agent.claims import check_sentence, check_comparisons


def _row(code, name, on_time, prio, days, cost, late_days, total=12):
    return {"code": code, "name": name, "on_time_orders": on_time,
            "total_orders": total, "priority_on_time": prio, "priority_total": 6,
            "total_days_late": days, "extra_cost": cost,
            "late_orders": [{"order_id": f"SO{i:02d}", "days_late": d, "priority_rank": 2}
                            for i, d in enumerate(late_days, 1)]}


NAMED = [
    _row("WAIT", "Wait for the delayed delivery", 5, 2, 27, 0, [6, 5, 4, 5, 3, 2, 2]),
    _row("TRANSFER", "Move stock from North Buffer and East Buffer", 8, 4, 12, 416,
         [5, 3, 2, 2]),
    _row("ALT_BUY", "Buy 65 from Beacon Circuits", 9, 4, 5, 1250, [1, 2, 2]),
    _row("HYBRID", "Move stock + buy 45 from Beacon Circuits", 11, 5, 2, 1306, [2]),
]
SEARCHED = NAMED + [
    _row("OF02 x35 + transfers", "Move stock + buy 35 from Beacon Circuits",
         10, 5, 4, 1126, [2, 2]),
    _row("OF02 x65 + transfers", "Move stock + buy 65 from Beacon Circuits",
         12, 6, 0, 1666, []),
]
T4 = claims.recommendation_table(NAMED)
T6 = claims.recommendation_table(SEARCHED)
T2 = claims.recommendation_table(NAMED[1:3])            # TRANSFER vs ALT_BUY

WR_ROWS = [
    {"code": "WAIT", "name": "Wait for the delayed delivery", "extra_cost": 0,
     "expected_late_orders": 7.42, "p90_late_orders": 10,
     "tail_mean_late_orders": 10.31, "p_no_late_pct": 0.0, "late_at_focus": 5},
    {"code": "TRANSFER", "name": "Move stock from North Buffer and East Buffer",
     "extra_cost": 416, "expected_late_orders": 5.55, "p90_late_orders": 9,
     "tail_mean_late_orders": 9.4, "p_no_late_pct": 6.9, "late_at_focus": 2},
    {"code": "ALT_BUY", "name": "Buy 65 from Beacon Circuits", "extra_cost": 1250,
     "expected_late_orders": 4.65, "p90_late_orders": 8,
     "tail_mean_late_orders": 8.52, "p_no_late_pct": 3.7, "late_at_focus": 1},
    {"code": "HYBRID", "name": "Move stock + buy 45 from Beacon Circuits",
     "extra_cost": 1306, "expected_late_orders": 3.34, "p90_late_orders": 7,
     "tail_mean_late_orders": 7.6, "p_no_late_pct": 11.0, "late_at_focus": 0},
]
WR = claims.world_risk_table(WR_ROWS, has_focus=True)
WR_NOFOCUS = claims.world_risk_table(WR_ROWS, has_focus=False)

# (sentence, table, star, budget)
REAL_OK = [
    ("The recommended option is TRANSFER, which has the most on-time orders "
     "within the budget of $500.", T4, "TRANSFER", 500),
    ("The recommended option is TRANSFER, which has the most on-time orders (8 of 12) "
     "among the options within the $1,000 budget.", T4, "TRANSFER", 1000),
    ("The engine recommends TRANSFER because it results in 8 on-time orders, which is "
     "the highest number among options within the $800 budget.", T4, "TRANSFER", 800),
    ("The recommended option, OF02 x35 + transfers, fits the user's request because it "
     "has the lowest extra cost, $1,126, among options with at least 10 on-time orders.",
     T6, "OF02 x35 + transfers", None),
    ("In comparison to WAIT, TRANSFER has more on-time orders and priority-1 on-time "
     "orders.", T4, "TRANSFER", 800),
    ("In comparison to WAIT, TRANSFER has 3 more on-time orders and 15 fewer total "
     "days late.", T4, "TRANSFER", 1000),
    ("In comparison to other options, (TRANSFER) has more on-time orders than (WAIT) "
     "and is cheaper than (ALT_BUY) and (HYBRID).", T4, "TRANSFER", 500),
    ("It is the best choice among the options that are within the budget, compared to "
     "WAIT and TRANSFER which have fewer on-time orders.", T6, "OF02 x35 + transfers", 1200),
    ("This option is distinct from WAIT and TRANSFER, which have fewer on-time orders, "
     "and from ALT_BUY and HYBRID, which have higher extra costs.",
     T6, "OF02 x35 + transfers", None),
    ("It has 10 on-time orders, which is more than TRANSFER and WAIT.",
     T6, "OF02 x35 + transfers", 1200),
    ("It has fewer on-time orders than HYBRID, but at a lower extra cost.",
     T6, "OF02 x35 + transfers", None),
    ("This option has 8 on-time orders, which is more than WAIT, and is within the "
     "budget, unlike ALT_BUY and HYBRID.", T4, "TRANSFER", 1000),
    ("This option has the lowest total days late, with only 2 days.", T4, "HYBRID", 1306),
    ("This option has the highest extra cost of $1,666.", T6, "OF02 x65 + transfers", None),
    ("The options differ in the number of on-time orders, with (HYBRID) having the most "
     "at 11 of 12, and (WAIT) having the least at 5 of 12.", T4, None, None),
    ("The options also vary in extra cost, ranging from $0 for (WAIT) to $1,666 for "
     "(OF02 x65 + transfers).", T6, None, None),
    ("- WAIT would reduce extra cost to $0 but have fewer on-time orders.",
     T4, "TRANSFER", 500),
    ("- ALT_BUY would increase on-time orders to 9 but exceed the budget of $500.",
     T4, "TRANSFER", 500),
    ("- ALT_BUY would have 9 on-time orders, but its extra cost of $1,250 is above "
     "the budget.", T4, "TRANSFER", 800),
    ("- ALT_BUY would have 9 of 12 orders on time but cost $1,250, exceeding the budget.",
     T4, "TRANSFER", 500),
    ("- Choosing WAIT would eliminate extra cost but have the fewest on-time orders, "
     "5 of 12.", T6, "OF02 x35 + transfers", 1200),
    ("- HYBRID would increase on-time orders to 11 and have the lowest total days late "
     "at 2, but at a higher extra cost of $1,306.", T4, "ALT_BUY", None),
    ("- WAIT would save $1,306 but result in 7 late orders and 27 total days late.",
     T4, "HYBRID", 1306),
    ("- TRANSFER would save $890 but have 3 fewer on-time orders.", T4, "HYBRID", None),
    ("- TRANSFER would cost $834 less than ALT_BUY but have 12 total days late.",
     T4, "ALT_BUY", None),
    ("- TRANSFER would save $1,250 but have 4 late orders, - ALT_BUY would save $416 "
     "but have 3 late orders.", T6, "OF02 x65 + transfers", None),
    ("- Choosing ALT_BUY or HYBRID would increase the number of on-time orders but "
     "exceed the $1,000 budget.", T4, "TRANSFER", 1000),
    ("- WAIT would save $416 in extra cost but have fewer on-time orders (5 of 12) and "
     "more total days late (27).", T4, "TRANSFER", 1000),
    ("- Choosing ALT_BUY would increase the extra cost to $1,250.", T2, None, None),
    ("The Chance of no late order column shows that HYBRID has the highest chance of "
     "no late orders at 11.0%.", WR, None, None),
    ("The risk of each option is uncertain, with the expected late orders ranging from "
     "3.34 for HYBRID to 7.42 for WAIT, and the 90th percentile of late orders ranging "
     "from 7 for HYBRID to 10 for WAIT.", WR, None, None),
    ("The 90th percentile column shows that in 9 of 10 cases, late orders are at or "
     "below 10 for WAIT, 9 for TRANSFER, 8 for ALT_BUY, and 7 for HYBRID.", WR, None, None),
    ("The HYBRID option will have 0 late orders if it arrives on Nov 15, as shown in "
     "the same column.", WR, None, None),
]

# A comparison that disagrees with the table.
REAL_WRONG = [
    # the recorded error that started this check (sweep 2026-11-22, comparison view)
    ("- (TRANSFER) would cost $416 less than (HYBRID) but have 3 fewer on-time orders.",
     T6, None, None),
    ("TRANSFER also has a lower total days late and extra cost compared to other "
     "options like ALT_BUY.", T4, "TRANSFER", 800),
    ("- HYBRID would have the most on-time orders, 11 of 12, but would also exceed the "
     "$1,000 budget.", T6, "TRANSFER", 1000),
    ("The options differ in the number of on-time orders, with HYBRID (11 of 12) and "
     "OF02 x65 + transfers (12 of 12) having the most.", T6, None, None),
    # "the most" stated without its limit: the table has rows with more
    ("The recommended option is TRANSFER, which has the most on-time orders with 8 out "
     "of 12, and is within the budget of $800.", T4, "TRANSFER", 800),
    ("The maximum delay for ALT_BUY is not the lowest, but HYBRID has the lowest at "
     "2 days.", T4, "ALT_BUY", None),
    ("TRANSFER has a higher chance of no late order than HYBRID.", WR, None, None),
    ("HYBRID has the highest expected late orders.", WR, None, None),
    ("WAIT is within the budget of $800, unlike TRANSFER.", T4, "TRANSFER", 500),
]

# A comparison that cannot be tied to a column and to options on both sides.
REAL_UNVERIFIABLE = [
    # the recorded world-risk sentence (sweep 2026-11-22): no subject, wrong direction
    ("This is higher than the chance with ALT_BUY and HYBRID, but lower than the "
     "difference in expected late orders between TRANSFER and WAIT.", WR, None, None),
    ("The recommended option, OF02 x65 + transfers, fits the user's request because it "
     "is the only option that keeps all 12 orders on time.", T6, "OF02 x65 + transfers", None),
    ("- (WAIT) would save $1,666 but have only 5 on-time orders.", T6, None, None),
    ("- Waiting for the delayed delivery would save $1,666 but result in 7 late orders.",
     T6, "OF02 x65 + transfers", None),
    ("The HYBRID option has the lowest value of 4, indicating a lower risk.", WR, None, None),
    ("HYBRID is safer than TRANSFER.", WR, None, None),
    ("HYBRID is the safest option.", WR, None, None),
    ("HYBRID beats ALT_BUY on expected late orders.", WR, None, None),
    ("TRANSFER has twice the chance of no late order of ALT_BUY.", WR, None, None),
    ("HYBRID is more robust than WAIT.", WR, None, None),
    ("HYBRID has a wider range of the average than WAIT.", WR, None, None),
    ("HYBRID is within the budget.", T4, "HYBRID", None),          # no budget in the request
    ("Late if it arrives Nov 15 is lower for HYBRID than for WAIT.", WR_NOFOCUS, None, None),
]


class RealSentences(unittest.TestCase):
    def _run(self, cases, expected):
        for sent, table, star, budget in cases:
            with self.subTest(sentence=sent):
                status, why = check_sentence(sent, table, star, budget)
                self.assertEqual(status, expected, why)

    def test_true_comparisons_pass(self):
        self._run(REAL_OK, "ok")

    def test_wrong_comparisons_are_caught(self):
        self._run(REAL_WRONG, "wrong")

    def test_unreadable_comparisons_are_not_passed(self):
        self._run(REAL_UNVERIFIABLE, "unverifiable")

    def test_recorded_error_reason(self):
        _s, why = check_sentence(REAL_WRONG[0][0], T6)
        self.assertIn("890", why)

    def test_text_without_comparison_passes(self):
        text = ("TRANSFER has 8 on-time orders, 12 total days late, and an extra cost of "
                "$416, while ALT_BUY has 9 on-time orders. The extra cost does not depend "
                "on the receipt date.")
        self.assertEqual(check_comparisons(text, T4), (True, "ok"))

    def test_paragraph_fails_on_one_bad_sentence(self):
        text = ("The chance of no late orders with TRANSFER is 6.9%. "
                "TRANSFER has a higher chance of no late order than HYBRID.")
        ok, why = check_comparisons(text, WR)
        self.assertFalse(ok)
        self.assertTrue(why.startswith("wrong"))


_SWAP = [("more", "fewer"), ("fewer", "more"), ("higher", "lower"), ("lower", "higher"),
         ("most", "fewest"), ("fewest", "most"), ("highest", "lowest"),
         ("lowest", "highest"), ("cheaper", "more expensive"), ("reduce", "increase"),
         ("increase", "reduce"), ("least", "most"), ("above", "below"),
         ("exceed", "is below"), ("exceeding", "below"), ("less", "more")]


class Mutations(unittest.TestCase):
    """Turn every true sentence around: the result must never be 'ok'."""

    def test_reversed_direction_never_passes(self):
        import re
        n = 0
        for sent, table, star, budget in REAL_OK:
            for a, b in _SWAP:
                hits = list(re.finditer(rf"\b{a}\b", sent))
                for h in hits:
                    mutated = sent[:h.start()] + b + sent[h.end():]
                    if "at or below" in sent and a in ("below",):
                        continue
                    with self.subTest(sentence=mutated):
                        status, _ = check_sentence(mutated, table, star, budget)
                        self.assertNotEqual(status, "ok")
                        n += 1
        self.assertGreater(n, 30)

    def test_changed_amount_never_passes(self):
        cases = [
            ("- TRANSFER would save $891 but have 3 fewer on-time orders.", T4, "HYBRID"),
            ("- TRANSFER would save $890 but have 2 fewer on-time orders.", T4, "HYBRID"),
            ("In comparison to WAIT, TRANSFER has 4 more on-time orders.", T4, "TRANSFER"),
            ("- ALT_BUY would increase on-time orders to 10.", T4, "TRANSFER"),
            ("- TRANSFER would cost $416 less than ALT_BUY.", T4, "ALT_BUY"),
        ]
        for sent, table, star in cases:
            with self.subTest(sentence=sent):
                self.assertEqual(check_sentence(sent, table, star)[0], "wrong")

    def test_range_must_be_the_real_extremes(self):
        s = "Expected late orders range from 3.34 for HYBRID to 5.55 for TRANSFER."
        self.assertEqual(check_sentence(s, WR)[0], "wrong")
        s = "Expected late orders range from 3.34 for TRANSFER to 7.42 for WAIT."
        self.assertEqual(check_sentence(s, WR)[0], "wrong")


class Reading(unittest.TestCase):
    def test_limit_is_bound_only_without_and(self):
        bound = "TRANSFER has the most on-time orders within the budget."
        loose = "TRANSFER has the most on-time orders, and it is within the budget."
        self.assertEqual(check_sentence(bound, T4, "TRANSFER", 500)[0], "ok")
        self.assertEqual(check_sentence(loose, T4, "TRANSFER", 500)[0], "wrong")

    def test_budget_amount_must_be_the_request_budget(self):
        s = "TRANSFER has the most on-time orders within the budget of $900."
        self.assertEqual(check_sentence(s, T4, "TRANSFER", 500)[0], "wrong")

    def test_other_options_means_every_other_row(self):
        s = "Compared to other options like WAIT, TRANSFER has more on-time orders."
        self.assertEqual(check_sentence(s, T4, "TRANSFER")[0], "wrong")
        s = "Compared to the other options, HYBRID has more on-time orders."
        self.assertEqual(check_sentence(s, T4, "HYBRID")[0], "ok")

    def test_plain_late_orders_must_hold_in_every_late_column(self):
        # true for expected, 90th percentile, worst-10% and the focus date
        s = "HYBRID has fewer late orders than WAIT."
        self.assertEqual(check_sentence(s, WR)[0], "ok")
        rows = [dict(r) for r in WR_ROWS]
        rows[3]["p90_late_orders"] = 11            # HYBRID worse on one column
        t = claims.world_risk_table(rows, has_focus=True)
        self.assertEqual(check_sentence(s, t)[0], "wrong")

    def test_values_are_compared_as_printed(self):
        rows = [dict(r) for r in WR_ROWS]
        rows[1]["expected_late_orders"], rows[2]["expected_late_orders"] = 4.654, 4.651
        t = claims.world_risk_table(rows, has_focus=True)   # both print as 4.65
        s = "TRANSFER has higher expected late orders than ALT_BUY."
        self.assertEqual(check_sentence(s, t)[0], "wrong")

    def test_ties_count_for_superlatives(self):
        s = "ALT_BUY has the shortest maximum delay."
        self.assertEqual(check_sentence(s, T4, "ALT_BUY")[0], "ok")   # 2 days, tied with HYBRID

    def test_negation(self):
        self.assertEqual(check_sentence(
            "TRANSFER does not exceed the budget.", T4, "TRANSFER", 500)[0], "ok")
        self.assertEqual(check_sentence(
            "ALT_BUY does not exceed the budget.", T4, "TRANSFER", 500)[0], "wrong")
        self.assertEqual(check_sentence(
            "WAIT is not the cheapest option.", T4, "TRANSFER")[0], "wrong")

    def test_two_rows_compare_with_each_other(self):
        s = "- Choosing TRANSFER would decrease the number of on-time orders to 8."
        self.assertEqual(check_sentence(s, T2)[0], "ok")
        self.assertEqual(check_sentence(s, T4)[0], "unverifiable")   # four rows, no reference

    def test_option_name_instead_of_code(self):
        s = "Move stock + buy 45 from Beacon Circuits has more on-time orders than WAIT."
        self.assertEqual(check_sentence(s, T6)[0], "ok")
        s = "Move stock + buy 35 from Beacon Circuits has more on-time orders than HYBRID."
        self.assertEqual(check_sentence(s, T6)[0], "wrong")

    def test_lower_case_wait_is_not_the_option(self):
        s = "If we wait, costs are lower than HYBRID."
        self.assertEqual(check_sentence(s, T4)[0], "unverifiable")


class RandomTables(unittest.TestCase):
    """The verdict follows the table values, whatever they are."""

    TEMPLATES = [
        ("{a} has more on-time orders than {b}.", "on_time_orders", +1),
        ("{a} has fewer on-time orders than {b}.", "on_time_orders", -1),
        ("{a} has a higher extra cost than {b}.", "extra_cost", +1),
        ("{a} is cheaper than {b}.", "extra_cost", -1),
        ("Total days late are lower for {a} than for {b}.", "total_days_late", -1),
        ("Compared to {b}, {a} has more priority-1 on-time orders.", "priority_on_time", +1),
    ]

    def test_pairs(self):
        rng = random.Random(20261122)
        codes = ["AAA", "BBB x10 + transfers", "CCC", "DDD"]
        for _ in range(60):
            rows = [_row(c, f"Option {c}", rng.randint(0, 20), rng.randint(0, 6),
                         rng.randint(0, 40), rng.choice([0, 100, 250, 250, 900]),
                         [rng.randint(1, 9)], total=20) for c in codes]
            table = claims.recommendation_table(rows)
            by = {r["code"]: r for r in rows}
            a, b = rng.sample(codes, 2)
            for tpl, key, d in self.TEMPLATES:
                truth = by[a][key] > by[b][key] if d > 0 else by[a][key] < by[b][key]
                status, why = check_sentence(tpl.format(a=a, b=b), table)
                with self.subTest(tpl=tpl, a=by[a][key], b=by[b][key]):
                    self.assertEqual(status, "ok" if truth else "wrong", why)

    def test_superlatives(self):
        rng = random.Random(7)
        codes = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        for _ in range(60):
            rows = [_row(c, f"Option {c}", rng.randint(0, 6), 0, rng.randint(0, 9),
                         rng.choice([0, 100, 250, 900]), [1], total=6) for c in codes]
            table = claims.recommendation_table(rows)
            a = rng.choice(codes)
            by = {r["code"]: r for r in rows}
            budget = rng.choice([100, 250, 900])
            cases = [
                (f"{a} has the most on-time orders.",
                 by[a]["on_time_orders"] == max(r["on_time_orders"] for r in rows)),
                (f"{a} is the cheapest option.",
                 by[a]["extra_cost"] == min(r["extra_cost"] for r in rows)),
                (f"{a} has the most on-time orders within the budget.",
                 by[a]["extra_cost"] <= budget and by[a]["on_time_orders"] == max(
                     r["on_time_orders"] for r in rows if r["extra_cost"] <= budget)),
            ]
            for sent, truth in cases:
                status, why = check_sentence(sent, table, None, budget)
                with self.subTest(sentence=sent):
                    self.assertEqual(status, "ok" if truth else "wrong", why)


class Wiring(unittest.TestCase):
    """The check is applied where AI text enters a view.  The sentences are
    built from the rows of the view, so the tests hold for other data."""

    @staticmethod
    def _pair(rows, key):
        """(code with the larger value, code with the smaller value)."""
        rows = sorted(rows, key=lambda r: r[key])
        lo, hi = rows[0], rows[-1]
        assert lo[key] != hi[key]
        return hi["code"], lo["code"]

    def test_recommendation_rationale_and_tradeoff_lines(self):
        from agent import render
        view = render.build_recommendation("Compare all options.", [], compare=True)
        hi, lo = self._pair(view["rows"], "on_time_orders")
        good = f"{hi} has more on-time orders than {lo}."
        bad = f"{lo} has more on-time orders than {hi}."
        plain = f"- {hi} is one of the rows."
        r, t, check = render.check_narrative(view, good, f"- {good}\n{plain}")
        self.assertEqual((r, check["rationale"], check["tradeoff_lines_dropped"]),
                         (good, "ok", 0))
        self.assertEqual(t, f"- {good}\n{plain}")
        r, t, check = render.check_narrative(view, bad, f"- {bad}\n{plain}")
        self.assertEqual(check, {"rationale": "dropped", "tradeoff_lines_dropped": 1})
        self.assertNotIn(bad, r + t)
        self.assertIn("could not be confirmed", r)
        self.assertIn(plain, t)
        self.assertIn("not shown", t)
        _r, _t, check = render.check_narrative(view, "", "")
        self.assertEqual(check["rationale"], "unavailable")

    def test_recommendation_through_the_agent_loop(self):
        from agent.fake_llm import ScriptedLLM
        from agent.loop import run_agent
        from agent import render
        rows = render.build_recommendation("Compare all options.", [], compare=True)["rows"]
        hi, lo = self._pair(rows, "extra_cost")
        bad = f"{hi} is cheaper than {lo}."
        call = {"tool_calls": [{"id": "c1", "name": "compare_scenarios", "args": {}}]}
        r = run_agent("Compare all options.", llm=ScriptedLLM([
            call, {"content": "gathered"},
            {"content": f"Comparison: {bad}\nTrade-offs:\n- {bad}"},
        ]))
        self.assertEqual(r["view"]["type"], "comparison")
        self.assertNotIn(bad, r["answer"])
        self.assertEqual(r["view"]["narrative_check"],
                         {"rationale": "dropped", "tradeoff_lines_dropped": 1})
        good = f"{lo} is cheaper than {hi}."
        r = run_agent("Compare all options.", llm=ScriptedLLM([
            call, {"content": "gathered"},
            {"content": f"Comparison: {good}\nTrade-offs:\n- {good}"},
        ]))
        self.assertEqual(r["answer"].count(good), 2)
        self.assertEqual(r["view"]["narrative_check"],
                         {"rationale": "ok", "tradeoff_lines_dropped": 0})

    def test_world_risk_explanation(self):
        from agent.render import world_risk_view
        rows = world_risk_view("general")["rows"]
        hi, lo = self._pair(rows, "expected_late_orders")
        good = f"{hi} has higher expected late orders than {lo}."
        bad = f"{lo} has higher expected late orders than {hi}."
        v = world_risk_view("general", explanation=good)
        self.assertEqual((v["explanation_status"], v["explanation_drop_reason"]),
                         ("ok", None))
        self.assertIn(good, v["markdown"])
        v = world_risk_view("general", explanation=bad)
        self.assertEqual((v["explanation_status"], v["explanation_drop_reason"]),
                         ("dropped", "comparison"))
        self.assertNotIn(bad, v["markdown"])
        self.assertIn("could not be confirmed", v["markdown"])
        v = world_risk_view("general", explanation="WAIT has 123456 expected late orders.")
        self.assertEqual(v["explanation_drop_reason"], "number")


if __name__ == "__main__":
    unittest.main()
