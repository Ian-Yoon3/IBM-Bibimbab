"""Tests for the agent layer — no network calls, uses ScriptedLLM."""
import json
import unittest

from agent.llm import normalize_tool_calls
from agent.fake_llm import ScriptedLLM
from agent.tool_specs import TOOL_SPECS, call_tool
from agent.loop import run_agent


# ── normalize_tool_calls ──────────────────────────────────────────────────────

class TestNormalizeToolCalls(unittest.TestCase):

    def _granite_raw(self, name, args_str):
        """Granite-style: arguments is a JSON-encoded string."""
        return {
            "role": "assistant",
            "tool_calls": [{
                "id": "tc-001",
                "type": "function",
                "function": {"name": name, "arguments": args_str},
            }],
        }

    def _llama_raw(self, name, args_dict):
        """Llama-style: arguments is already a dict."""
        return {
            "role": "assistant",
            "tool_calls": [{
                "id": "tc-002",
                "type": "function",
                "function": {"name": name, "arguments": args_dict},
            }],
        }

    def test_granite_string_args_normalised_to_dict(self):
        """Granite returns arguments as a JSON string; must become a dict."""
        raw = self._granite_raw("get_disruption", '{"disruption_id": "D01"}')
        result = normalize_tool_calls(raw)
        self.assertEqual(len(result["tool_calls"]), 1)
        tc = result["tool_calls"][0]
        self.assertIsInstance(tc["args"], dict)
        self.assertEqual(tc["args"]["disruption_id"], "D01")
        self.assertEqual(tc["name"], "get_disruption")

    def test_llama_dict_args_passed_through(self):
        """Llama returns arguments as a dict; must remain a dict unchanged."""
        raw = self._llama_raw("compare_scenarios", {"budget": 500})
        result = normalize_tool_calls(raw)
        tc = result["tool_calls"][0]
        self.assertIsInstance(tc["args"], dict)
        self.assertEqual(tc["args"]["budget"], 500)

    def test_granite_doubly_encoded_string(self):
        """Granite sometimes double-encodes; outer string must be decoded."""
        # arguments is a string containing another JSON string
        inner = '{"budget": 500}'
        outer = json.dumps(inner)   # "\"{\\\"budget\\\": 500}\""
        raw = self._granite_raw("compare_scenarios", outer)
        result = normalize_tool_calls(raw)
        tc = result["tool_calls"][0]
        self.assertIsInstance(tc["args"], dict)
        self.assertEqual(tc["args"]["budget"], 500)

    def test_no_tool_calls_returns_empty_list(self):
        raw = {"role": "assistant", "content": "Here is my answer."}
        result = normalize_tool_calls(raw)
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(result["content"], "Here is my answer.")

    def test_content_preserved(self):
        raw = {"role": "assistant", "content": "Hello!", "tool_calls": None}
        result = normalize_tool_calls(raw)
        self.assertEqual(result["content"], "Hello!")
        self.assertEqual(result["tool_calls"], [])

    def test_unparseable_string_args_sets_parse_error(self):
        """Malformed JSON string → args=None, _parse_error set."""
        raw = self._granite_raw("get_disruption", "not valid json {{{{")
        result = normalize_tool_calls(raw)
        tc = result["tool_calls"][0]
        self.assertIsNone(tc["args"])
        self.assertIsNotNone(tc["_parse_error"])
        self.assertIn("get_disruption", tc["_parse_error"])

    def test_non_dict_non_string_args_sets_parse_error(self):
        """Non-dict, non-string arguments (e.g. a list) → args=None."""
        raw = self._llama_raw("get_disruption", ["D01"])
        result = normalize_tool_calls(raw)
        tc = result["tool_calls"][0]
        self.assertIsNone(tc["args"])
        self.assertIsNotNone(tc["_parse_error"])

    def test_good_args_have_no_parse_error(self):
        """Successfully parsed args → _parse_error is None."""
        raw = self._granite_raw("get_disruption", '{"disruption_id": "D01"}')
        result = normalize_tool_calls(raw)
        tc = result["tool_calls"][0]
        self.assertIsNone(tc["_parse_error"])


# ── call_tool ─────────────────────────────────────────────────────────────────

class TestCallTool(unittest.TestCase):

    def test_unknown_tool_returns_error_dict(self):
        """Unknown tool names return {'error': ...}, they do not raise."""
        result = call_tool("approve_everything", {})
        self.assertIn("error", result)
        self.assertIn("approve_everything", result["error"])

    def test_unknown_tool_error_contains_name(self):
        result = call_tool("nonexistent_tool", {"x": 1})
        self.assertIn("nonexistent_tool", result["error"])

    def test_invalid_disruption_id_returns_error(self):
        result = call_tool("get_disruption", {"disruption_id": "D99"})
        self.assertIn("error", result)

    def test_invalid_disruption_id_for_get_impact(self):
        result = call_tool("get_impact", {"disruption_id": "FAKE"})
        self.assertIn("error", result)

    def test_invalid_scenario_id_for_priority_view(self):
        result = call_tool("get_priority_view", {"scenario_id": "BOGUS"})
        self.assertIn("error", result)

    def test_get_disruption_d01_succeeds(self):
        result = call_tool("get_disruption", {"disruption_id": "D01"})
        self.assertNotIn("error", result)
        self.assertEqual(result["disruption_id"], "D01")

    def test_compare_scenarios_no_args_succeeds(self):
        result = call_tool("compare_scenarios", {})
        self.assertNotIn("error", result)
        self.assertIn("ranked", result)

    def test_propose_action_missing_reason_returns_error(self):
        result = call_tool("propose_action", {"scenario_id": "HYBRID"})
        self.assertIn("error", result)

    def test_propose_action_scenario_id_returns_pending(self):
        result = call_tool("propose_action", {"scenario_id": "HYBRID", "reason": "test"})
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "pending_approval")

    def test_propose_action_offer_qty_path(self):
        """propose_action with offer_id+qty resolves via explore and returns proposal."""
        result = call_tool("propose_action", {
            "offer_id": "OF02",
            "qty": 45,
            "include_transfers": True,
            "reason": "cheapest 11-order option",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(result["metrics"]["on_time_orders"], 11)

    def test_propose_action_offer_qty_wrong_qty_returns_error(self):
        result = call_tool("propose_action", {
            "offer_id": "OF02",
            "qty": 999,
            "reason": "bad qty",
        })
        self.assertIn("error", result)

    def test_none_args_returns_parse_error(self):
        """call_tool with args=None returns an error dict (parse failure path)."""
        result = call_tool("get_disruption", None)
        self.assertIn("error", result)
        self.assertIn("get_disruption", result["error"])

    def test_none_args_unknown_tool_returns_unknown_error(self):
        """Unknown tool name takes precedence over None args."""
        result = call_tool("bogus_tool", None)
        self.assertIn("error", result)
        self.assertIn("bogus_tool", result["error"])


# ── TOOL_SPECS ────────────────────────────────────────────────────────────────

class TestToolSpecs(unittest.TestCase):

    def _tool_names(self):
        return {spec["function"]["name"] for spec in TOOL_SPECS}

    def test_no_approve_tool_exists(self):
        """TOOL_SPECS must not expose any approve/confirm/execute tool."""
        names = self._tool_names()
        for name in names:
            self.assertNotIn("approve",  name.lower())
            self.assertNotIn("confirm",  name.lower())
            self.assertNotIn("execute",  name.lower())

    def test_run_scenario_not_exposed(self):
        self.assertNotIn("run_scenario", self._tool_names())

    def test_seven_tools_exposed(self):
        self.assertEqual(len(TOOL_SPECS), 7)

    def test_all_tools_have_required_fields(self):
        for spec in TOOL_SPECS:
            self.assertEqual(spec["type"], "function")
            fn = spec["function"]
            self.assertIn("name", fn)
            self.assertIn("description", fn)
            self.assertIn("parameters", fn)

    def test_get_offers_present(self):
        self.assertIn("get_offers", self._tool_names())


# ── run_agent loop ────────────────────────────────────────────────────────────

class TestRunAgent(unittest.TestCase):

    def test_direct_text_answer(self):
        """LLM returns text on first turn — no tool calls."""
        llm = ScriptedLLM([{"content": "Only D01 is supported."}])
        result = run_agent("What disruption is this?", llm=llm)
        self.assertEqual(result["answer"], "Only D01 is supported.")
        self.assertEqual(result["tool_trace"], [])
        self.assertIsNone(result["proposal"])

    def test_single_tool_call_then_answer(self):
        """LLM calls get_disruption once, then returns text."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "The disruption delays PO01 by 6 days."},
        ])
        result = run_agent("What happened?", llm=llm)
        self.assertEqual(result["answer"], "The disruption delays PO01 by 6 days.")
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(result["tool_trace"][0]["name"], "get_disruption")

    def test_tool_result_in_trace(self):
        """Tool trace captures name, args, and result."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c2", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "Done."},
        ])
        result = run_agent("Details?", llm=llm)
        entry = result["tool_trace"][0]
        self.assertEqual(entry["name"], "get_disruption")
        self.assertEqual(entry["args"], {"disruption_id": "D01"})
        self.assertIn("disruption_id", entry["result"])

    def test_max_steps_stop_returns_graceful_answer(self):
        """Loop stops at max_steps and returns a graceful answer instead of crashing."""
        # Every step returns a tool call — model never gives a text answer
        llm = ScriptedLLM([
            {"tool_calls": [{"id": f"c{i}", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]}
            for i in range(10)
        ])
        result = run_agent("Loop forever?", llm=llm, max_steps=3)
        self.assertIsInstance(result["answer"], str)
        self.assertGreater(len(result["answer"]), 0)
        self.assertEqual(len(result["tool_trace"]), 3)

    def test_unknown_tool_call_returns_error_to_llm(self):
        """Unknown tool name returns an error dict; loop continues."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "approve_now",
                             "args": {}}]},
            {"content": "I cannot approve things."},
        ])
        result = run_agent("Approve!", llm=llm)
        self.assertEqual(result["answer"], "I cannot approve things.")
        self.assertIn("error", result["tool_trace"][0]["result"])

    def test_propose_action_result_in_proposal(self):
        """propose_action result is captured in result['proposal']."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "propose_action",
                             "args": {"scenario_id": "HYBRID",
                                      "reason": "best trade-off"}}]},
            {"content": "I've created a proposal for HYBRID."},
        ])
        result = run_agent("Propose HYBRID", llm=llm)
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["status"], "pending_approval")

    def test_history_grows_across_turns(self):
        """History returned from run_agent feeds correctly into next turn."""
        llm1 = ScriptedLLM([{"content": "The disruption is 6 days."}])
        r1 = run_agent("How long is the delay?", llm=llm1)
        history = r1["history"]

        llm2 = ScriptedLLM([{"content": "HYBRID is best."}])
        r2 = run_agent("Which scenario is best?", history=history, llm=llm2)
        # history should include both turns
        roles = [m["role"] for m in r2["history"]]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_history_structure_no_tool_calls(self):
        """History for a direct-answer turn: [user, assistant]."""
        llm = ScriptedLLM([{"content": "D01 is the disruption."}])
        result = run_agent("What is the disruption?", llm=llm)
        h = result["history"]
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[0]["content"], "What is the disruption?")
        self.assertEqual(h[1]["role"], "assistant")
        self.assertEqual(h[1]["content"], "D01 is the disruption.")

    def test_history_structure_with_tool_call(self):
        """History for a turn with one tool call: [user, assistant+tool_calls, tool, assistant]."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "tc1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "PO01 is delayed 6 days."},
        ])
        result = run_agent("Tell me about D01.", llm=llm)
        h = result["history"]
        # Expect: user, assistant(tool_calls), tool, assistant(answer)
        self.assertEqual(len(h), 4)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[1]["role"], "assistant")
        self.assertIn("tool_calls", h[1])
        # assistant tool_calls entry should have content="" and arguments as JSON string
        self.assertEqual(h[1].get("content"), "")
        fn = h[1]["tool_calls"][0]["function"]
        self.assertIsInstance(fn["arguments"], str)
        json.loads(fn["arguments"])  # must be valid JSON
        self.assertEqual(h[2]["role"], "tool")
        self.assertIn("tool_call_id", h[2])
        self.assertEqual(h[2]["tool_call_id"], "tc1")
        self.assertEqual(h[3]["role"], "assistant")
        self.assertEqual(h[3]["content"], "PO01 is delayed 6 days.")

    def test_history_no_fabricated_tool_content(self):
        """History must not contain fabricated '[tool call: ...]' text."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "tc1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "Done."},
        ])
        result = run_agent("Info?", llm=llm)
        for msg in result["history"]:
            content = msg.get("content") or ""
            self.assertNotIn("[tool call:", content)

    def test_multi_tool_calls_in_one_step(self):
        """Multiple tool calls in one response are all executed."""
        llm = ScriptedLLM([
            {
                "tool_calls": [
                    {"id": "c1", "name": "get_disruption",
                     "args": {"disruption_id": "D01"}},
                    {"id": "c2", "name": "get_impact",
                     "args": {"disruption_id": "D01"}},
                ]
            },
            {"content": "Two tools called."},
        ])
        result = run_agent("Tell me everything about D01.", llm=llm)
        self.assertEqual(len(result["tool_trace"]), 2)
        names = [t["name"] for t in result["tool_trace"]]
        self.assertIn("get_disruption", names)
        self.assertIn("get_impact", names)


if __name__ == "__main__":
    unittest.main()
