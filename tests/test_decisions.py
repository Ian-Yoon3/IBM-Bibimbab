"""Tests for agent/decisions.py — the human decision log (network-free)."""
import json
import tempfile
import unittest
from pathlib import Path

from agent.decisions import list_decisions, record_decision
from agent.tool_specs import TOOL_SPECS, call_tool
from engine.tools import propose_action


class TestRecordDecision(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "log.jsonl"
        self.proposal = propose_action("HYBRID", "test")

    def tearDown(self):
        self._tmp.cleanup()

    def test_approve_writes_one_entry(self):
        entry = record_decision(self.proposal, True, "Ian", log_path=self.log)
        self.assertEqual(entry["decision"], "approved")
        self.assertEqual(entry["proposal_id"], self.proposal["proposal_id"])
        self.assertEqual(entry["on_time_orders"], 11)
        self.assertEqual(entry["total_extra_cost"], 1306)
        self.assertEqual(list_decisions(self.log), [entry])

    def test_reject_is_recorded(self):
        entry = record_decision(self.proposal, False, "Ian", note="too costly",
                                log_path=self.log)
        self.assertEqual(entry["decision"], "rejected")
        self.assertEqual(entry["note"], "too costly")

    def test_entry_is_json_serialisable(self):
        entry = record_decision(self.proposal, True, "Ian", log_path=self.log)
        json.dumps(entry)

    def test_proposal_is_not_mutated(self):
        before = json.dumps(self.proposal, sort_keys=True, default=str)
        record_decision(self.proposal, True, "Ian", log_path=self.log)
        self.assertEqual(json.dumps(self.proposal, sort_keys=True, default=str), before)
        self.assertEqual(self.proposal["status"], "pending_approval")

    def test_same_proposal_cannot_be_decided_twice(self):
        record_decision(self.proposal, True, "Ian", log_path=self.log)
        with self.assertRaises(ValueError):
            record_decision(self.proposal, False, "Ian", log_path=self.log)
        self.assertEqual(len(list_decisions(self.log)), 1)

    def test_invalid_inputs_write_nothing(self):
        bad_cases = [
            ({}, True, "Ian"),
            ({**self.proposal, "status": "approved"}, True, "Ian"),
            (self.proposal, "true", "Ian"),
            (self.proposal, True, "  "),
        ]
        for proposal, approved, who in bad_cases:
            with self.subTest(approved=approved, who=who):
                with self.assertRaises(ValueError):
                    record_decision(proposal, approved, who, log_path=self.log)
        self.assertEqual(list_decisions(self.log), [])

    def test_empty_log_returns_empty_list(self):
        self.assertEqual(list_decisions(self.log), [])


class TestDecisionNotReachableByLLM(unittest.TestCase):

    def test_not_in_tool_specs(self):
        names = {s["function"]["name"] for s in TOOL_SPECS}
        self.assertNotIn("record_decision", names)

    def test_call_tool_rejects_it(self):
        result = call_tool("record_decision", {"approved": True})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
