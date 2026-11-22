"""World-risk view on a Monte Carlo run (step 6b-2, written without Bob).

The stage 1 view tests (test_world_risk_view.py) cover one-draw data. These
tests cover what only a run shows: the range of the average, ranking
stability, the shared-cause section with grid thresholds, the assumption
lines and the removal of the worst-case column (Q7, Q8, S1-S3).
"""

import json
import pathlib
import shutil
import tempfile
import unittest

import engine.loader
import engine.runs
import engine.tools as _t
from agent.prompts import build_world_risk_message
from agent.render import _cause_lines, check_explanation, world_risk_view
from montecarlo.run import build_run

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


class _RunViewBase(unittest.TestCase):
    readme = True

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data = base / "data"
        shutil.copytree(_DATA_DIR, cls.data)
        readme = cls.data / "history" / "README.md"
        if not cls.readme and readme.exists():
            readme.unlink()
        cls.run_dir = base / "runs" / "v"
        build_run(cls.data, cls.run_dir, M=20, N=10, seed=11,
                  grid=True, target_se=0.5, pilot_M=4, max_M=8)
        sel = base / "selection.json"
        sel.write_text(json.dumps({"run": str(cls.run_dir)}), encoding="utf-8")
        cls._prev_dir = engine.loader._DEFAULT_DATA_DIR
        cls._prev_sel = engine.runs.SELECTION_PATH
        engine.loader._DEFAULT_DATA_DIR = cls.data
        engine.runs.SELECTION_PATH = sel
        _t._DB_CACHE.clear()
        cls.wr = _t.get_world_risk("D01")
        cls.view = world_risk_view("general", "How risky is each option?",
                                   explanation=None)

    @classmethod
    def tearDownClass(cls):
        engine.loader._DEFAULT_DATA_DIR = cls._prev_dir
        engine.runs.SELECTION_PATH = cls._prev_sel
        _t._DB_CACHE.clear()
        shutil.rmtree(cls._tmp, ignore_errors=True)


class TestRunView(_RunViewBase):

    def test_weights_from_run(self):
        self.assertEqual(self.wr["weights_source"], "run")
        self.assertTrue(self.wr["causes"])

    def test_heading_order(self):
        headings = [l[3:] for l in self.view["markdown"].splitlines()
                    if l.startswith("## ")]
        self.assertEqual(headings, [
            "Situation", "Time and cost by option", "How sure is this",
            "Shared causes", "Late orders by receipt date", "Trade-offs",
            "What this means", "Assumptions", "Notes", "Next step",
        ])

    def test_table_columns(self):
        md = self.view["markdown"]
        header = next(l for l in md.splitlines() if l.startswith("| Option | Extra cost"))
        self.assertEqual(header, "| Option | Extra cost | Expected late orders | "
                         "Range of the average | 90th percentile | Worst-10% average | "
                         "Chance of no late order |")
        self.assertNotIn("Worst case", md)
        self.assertNotIn("worst case", md)

    def test_rows_and_steps(self):
        opts = {o["scenario_id"]: o for o in self.wr["options"]}
        for r in self.view["rows"]:
            o = opts[r["scenario_id"]]
            self.assertNotIn("worst_late_orders", r)
            self.assertEqual(r["tail_mean_late_orders"], o["tail_mean_late_orders"])
            self.assertEqual(r["average_range"], o["average_range"])
            lo, hi = o["average_range"]
            self.assertIn(f"{lo:.2f} to {hi:.2f}", self.view["markdown"])
            self.assertIn(f"{o['tail_mean_late_orders']:.2f}", self.view["markdown"])
        for st in self.view["steps"]:
            self.assertNotIn("worst_late_change", st)
            self.assertIn("tail_mean_late_change", st)

    def test_view_keys(self):
        for key in ("ranking", "causes", "common_scale", "assumptions"):
            self.assertIn(key, self.view)
        self.assertEqual(self.view["causes"], self.wr["causes"])
        self.assertEqual(self.view["ranking"], self.wr["ranking"])

    def test_ranking_sentence(self):
        rk = self.wr["ranking"]
        self.assertIn(f"is the same in {rk['same_draws']} of {rk['draws']} parameter "
                      f"draws", self.view["markdown"])

    def test_cause_numbers_in_markdown(self):
        md = self.view["markdown"]
        for c in self.wr["causes"]:
            self.assertIn(f"window {c['active_pct']:.1f}%", md)
            for sid, wo in c["without"].items():
                wi = c["with"][sid]
                wo_s = f"{wo:.2f}" if wo is not None else "n/a"
                wi_s = f"{wi:.2f}" if wi is not None else "n/a"
                self.assertIn(f"{sid} {wo_s} / {wi_s}", md)

    def test_synthetic_line(self):
        self.assertIn("synthetic", " ".join(self.view["assumptions"]))

    def test_explanation_check_uses_new_sections(self):
        c = self.wr["causes"][0]
        ok_text = (f"{c['cause_id']} starts in the decision window with a chance of "
                   f"{c['active_pct']:.1f}%.")
        v = world_risk_view("general", "How risky is each option?",
                            explanation=ok_text)
        self.assertEqual(v["explanation_status"], "ok")
        v2 = world_risk_view("general", "How risky is each option?",
                             explanation="WAIT has 123.45 expected late orders.")
        self.assertEqual(v2["explanation_status"], "dropped")

    def test_compose_message_has_new_sections(self):
        msg = build_world_risk_message("How risky is each option?", self.view)["content"]
        self.assertIn("## How sure is this", msg)
        self.assertIn("## Shared causes", msg)
        self.assertIn("Range of the average is uncertainty about the average", msg)


class TestRunViewWithoutSyntheticReadme(_RunViewBase):
    readme = False

    def test_no_synthetic_line(self):
        self.assertNotIn("synthetic", " ".join(self.view["assumptions"]))
        self.assertIn("Which shipments share a cause is an assumption (data/causes.csv).",
                      self.view["assumptions"])


def _wr(causes, common_scale=None):
    return {"causes": causes, "common_scale": common_scale}


_ROWS = [{"scenario_id": "TRANSFER", "expected_late_orders": 5.55},
         {"scenario_id": "ALT_BUY", "expected_late_orders": 4.65}]


class TestCauseLines(unittest.TestCase):
    """Sentences checked against hand-written text."""

    def test_crossing_and_scale(self):
        c = {"cause_id": "K1", "targets": [["purchase_order", "PO01"], ["offer", "OF02"]],
             "active_pct": 9.5, "per_year_mean": 4.1, "open_episode": None,
             "without": {"TRANSFER": 5.38, "ALT_BUY": 4.41},
             "with": {"TRANSFER": 7.17, "ALT_BUY": 6.99},
             "grid": {"D0_days": 9, "max_p": 0.99, "max_per_year": 186.8,
                      "crossings": [{"pair": ["TRANSFER", "ALT_BUY"], "p_lo": 0.8125,
                                     "p_hi": 0.81875, "per_year_lo": 67.9,
                                     "per_year_hi": 69.3}]}}
        lines = _cause_lines(_ROWS, _wr([c], {"reference_cause": "K2", "crossings": [],
                                              "max_m": 40.53}))
        self.assertEqual(lines[0], "- K1 (affects PO01, OF02): chance that an episode "
                         "starts in the decision window 9.5% (about 4.1 per year).")
        self.assertEqual(lines[1], "  Expected late orders without / with it: "
                         "TRANSFER 5.38 / 7.17, ALT_BUY 4.41 / 6.99.")
        self.assertEqual(lines[2], "  TRANSFER and ALT_BUY swap places when the chance "
                         "is between 81.3% and 81.9% (about 67.9 to 69.3 per year). "
                         "Now ALT_BUY has fewer expected late orders.")
        self.assertEqual(lines[3], "- All causes together: no change in the order up "
                         "to 40.53 times the estimated rates.")

    def test_no_crossing(self):
        c = {"cause_id": "K2", "targets": [["lane", "LN01"]], "active_pct": 10.7,
             "per_year_mean": 8.3, "open_episode": None,
             "without": {"TRANSFER": 5.44, "ALT_BUY": 4.66},
             "with": {"TRANSFER": 6.45, "ALT_BUY": None},
             "grid": {"D0_days": 5, "max_p": 0.99, "max_per_year": 336.2,
                      "crossings": []}}
        lines = _cause_lines(_ROWS, _wr([c]))
        self.assertIn("ALT_BUY 4.66 / n/a", lines[1])
        self.assertEqual(lines[2], "  No change in the order up to a chance of 99.0% "
                         "(about 336.2 per year).")

    def test_open_episode_status(self):
        """F3: a cause in progress on the decision day gets a status sentence, no
        without/with numbers, and its grid is labelled in episodes per year."""
        c = {"cause_id": "K1", "targets": [["offer", "OF02"]], "active_pct": 100.0,
             "per_year_mean": 4.1,
             "open_episode": {"start_date": "2026-11-07", "end_date": None,
                              "delay_days": 3},
             "without": {"TRANSFER": None, "ALT_BUY": None},
             "with": {"TRANSFER": 6.0, "ALT_BUY": 5.0},
             "grid": {"D0_days": 9, "max_p": 0.99, "max_per_year": 186.8,
                      "crossings": []}}
        lines = _cause_lines(_ROWS, _wr([c]))
        self.assertEqual(lines[0], "- K1 (affects OF02): in progress since Nov 7, "
                         "end not announced, estimated from the history, recorded "
                         "delay 3 days. Current shipments are affected.")
        self.assertEqual(lines[1], "  No change in the order up to 186.8 new episodes "
                         "per year.")
        self.assertFalse(any(l.startswith("  Expected late orders without / with")
                             for l in lines))


if __name__ == "__main__":
    unittest.main()
