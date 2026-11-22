"""The UI fixtures still match the agent code (network-free).

If this fails after a change to agent/render.py or agent/loop.py, the view
contract changed: update docs/ui-contract.md, tell the UI developer, and run
``python -m scripts.make_ui_fixtures``.
"""
import json
import unittest
from pathlib import Path

from scripts.make_ui_fixtures import OUT, build, DEFAULT_SWEEP, StaleRun

EXPECTED_TYPES = {"recommendation", "comparison", "option", "order",
                  "proposal", "unsupported", "world_risk", None}


class TestUIFixtures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # A sweep made with a Monte Carlo run is replayed against that run.  When
        # the engine changed and runs/demo was not rebuilt yet, the run no longer
        # matches its fingerprint: skip with the reason instead of failing
        # (python -m engine.runs --check is the gate before any recording).
        try:
            cls.fixtures = build(DEFAULT_SWEEP)   # AssertionError on a mismatch
        except StaleRun as exc:
            raise unittest.SkipTest(f"UI fixtures not checked: {exc}")

    def test_every_view_type_is_covered(self):
        types = {(f["result"].get("view") or {}).get("type") for f in self.fixtures}
        self.assertEqual(types, EXPECTED_TYPES)

    def test_results_are_json_serialisable(self):
        json.dumps(self.fixtures, default=str)

    def test_proposals_only_in_proposal_views(self):
        for f in self.fixtures:
            r = f["result"]
            is_proposal_view = (r.get("view") or {}).get("type") == "proposal"
            self.assertEqual(r["proposal"] is not None, is_proposal_view, f["question"])

    def test_error_case_has_no_view(self):
        err = [f for f in self.fixtures if f["conversation"] == "error"]
        self.assertEqual(len(err), 1)
        self.assertIn("error", err[0]["result"])
        self.assertIsNone(err[0]["result"].get("view"))

    def test_committed_file_has_same_questions(self):
        self.assertTrue(Path(OUT).exists(), "run: python -m scripts.make_ui_fixtures")
        committed = json.loads(Path(OUT).read_text(encoding="utf-8"))
        self.assertEqual([f["question"] for f in committed],
                         [f["question"] for f in self.fixtures])


if __name__ == "__main__":
    unittest.main()
