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

    def test_eight_tools_exposed(self):
        # get_order_detail was added after eval run 5
        self.assertEqual(len(TOOL_SPECS), 8)
        self.assertIn("get_order_detail", self._tool_names())

    def test_all_tools_have_required_fields(self):
        for spec in TOOL_SPECS:
            self.assertEqual(spec["type"], "function")
            fn = spec["function"]
            self.assertIn("name", fn)
            self.assertIn("description", fn)
            self.assertIn("parameters", fn)

    def test_get_offers_present(self):
        self.assertIn("get_offers", self._tool_names())


# ── helpers ───────────────────────────────────────────────────────────────────

def _tool_then_compose(tool_calls_turn, compose_answer="Composed answer."):
    """Build a 2-turn script: one tool-calls turn + one compose turn."""
    return [tool_calls_turn, {"content": compose_answer}]


def _direct_compose(answer="Composed answer."):
    """Build a 2-turn script: one gather text turn + one compose turn."""
    return [{"content": "gather context"}, {"content": answer}]


# ── run_agent loop ────────────────────────────────────────────────────────────

class TestRunAgent(unittest.TestCase):

    def test_direct_text_answer(self):
        """Gather phase returns text immediately; compose produces the answer."""
        llm = ScriptedLLM([
            {"content": "gather: Only D01 is supported."},  # gather phase text
            {"content": "Composed: Only D01 is supported."},  # compose phase
        ])
        result = run_agent("What disruption is this?", llm=llm)
        self.assertEqual(result["answer"], "Composed: Only D01 is supported.")
        self.assertEqual(result["tool_trace"], [])
        self.assertIsNone(result["proposal"])

    def test_single_tool_call_then_answer(self):
        """Gather calls one tool, then compose produces the answer."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "gather text"},       # gather phase text (context only)
            {"content": "Composed: PO01 delayed 6 days."},  # compose answer
        ])
        result = run_agent("What happened?", llm=llm)
        self.assertEqual(result["answer"], "Composed: PO01 delayed 6 days.")
        self.assertEqual(len(result["tool_trace"]), 1)
        self.assertEqual(result["tool_trace"][0]["name"], "get_disruption")

    def test_tool_result_in_trace(self):
        """Tool trace captures name, args, and result."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c2", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "gather"},
            {"content": "Composed."},
        ])
        result = run_agent("Details?", llm=llm)
        entry = result["tool_trace"][0]
        self.assertEqual(entry["name"], "get_disruption")
        self.assertEqual(entry["args"], {"disruption_id": "D01"})
        self.assertIn("disruption_id", entry["result"])

    def test_max_steps_stop_still_composes(self):
        """Loop stops at max_steps and compose still runs."""
        tool_turns = [
            {"tool_calls": [{"id": f"c{i}", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]}
            for i in range(3)
        ]
        llm = ScriptedLLM(tool_turns + [{"content": "Composed after max_steps."}])
        result = run_agent("Loop forever?", llm=llm, max_steps=3)
        self.assertEqual(result["answer"], "Composed after max_steps.")
        self.assertEqual(len(result["tool_trace"]), 3)

    def test_canned_fallback_when_compose_empty(self):
        """Canned fallback used when compose returns empty content."""
        tool_turns = [
            {"tool_calls": [{"id": "c0", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]}
        ]
        llm = ScriptedLLM(tool_turns + [{"content": ""}])
        result = run_agent("What?", llm=llm, max_steps=1)
        self.assertIn("unable to compose", result["answer"].lower())

    def test_compose_call_receives_no_tools(self):
        """Compose phase calls llm.chat with an empty tools list."""
        received_tools = []

        class CapturingLLM:
            def chat(self_inner, messages, tools):  # noqa: N805
                received_tools.append(tools)
                if len(received_tools) == 1:
                    return {"content": "gather", "tool_calls": []}
                return {"content": "composed", "tool_calls": []}

        run_agent("Question?", llm=CapturingLLM())
        # Last call (compose) must have empty tools
        self.assertEqual(received_tools[-1], [])

    def test_compose_content_is_final_answer(self):
        """Answer comes from compose phase, not from gather text."""
        llm = ScriptedLLM([
            {"content": "gather text (not the answer)"},
            {"content": "FINAL COMPOSED ANSWER"},
        ])
        result = run_agent("Any question?", llm=llm)
        self.assertEqual(result["answer"], "FINAL COMPOSED ANSWER")
        self.assertNotEqual(result["answer"], "gather text (not the answer)")

    def test_compose_answer_is_last_history_message(self):
        """The compose answer is the final assistant message in history."""
        llm = ScriptedLLM([
            {"content": "gather context"},
            {"content": "FINAL COMPOSED ANSWER"},
        ])
        result = run_agent("Q?", llm=llm)
        last = result["history"][-1]
        self.assertEqual(last["role"], "assistant")
        self.assertEqual(last["content"], "FINAL COMPOSED ANSWER")

    def test_unknown_tool_call_returns_error_to_llm(self):
        """Unknown tool name returns an error dict; loop continues."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "approve_now", "args": {}}]},
            {"content": "gather"},
            {"content": "Composed: I cannot approve things."},
        ])
        result = run_agent("Approve!", llm=llm)
        self.assertEqual(result["answer"], "Composed: I cannot approve things.")
        self.assertIn("error", result["tool_trace"][0]["result"])

    def test_propose_action_result_in_proposal(self):
        """propose_action result is captured in result['proposal']."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "propose_action",
                             "args": {"scenario_id": "HYBRID",
                                      "reason": "best trade-off"}}]},
            {"content": "gather"},
            {"content": "Proposal created. Pending approval in the UI."},
        ])
        result = run_agent("Propose HYBRID", llm=llm)
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["status"], "pending_approval")

    def test_history_grows_across_turns(self):
        """History returned from run_agent feeds correctly into next turn."""
        llm1 = ScriptedLLM([
            {"content": "gather1"},
            {"content": "Composed turn 1."},
        ])
        r1 = run_agent("How long is the delay?", llm=llm1)
        history = r1["history"]

        llm2 = ScriptedLLM([
            {"content": "gather2"},
            {"content": "Composed turn 2."},
        ])
        r2 = run_agent("Which scenario is best?", history=history, llm=llm2)
        roles = [m["role"] for m in r2["history"]]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_history_structure_no_tool_calls(self):
        """History for a direct-answer turn: [user, gather-assistant, compose-assistant]."""
        llm = ScriptedLLM([
            {"content": "gather context"},
            {"content": "D01 is the disruption."},
        ])
        result = run_agent("What is the disruption?", llm=llm)
        h = result["history"]
        # user + gather assistant + compose assistant
        self.assertEqual(len(h), 3)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[0]["content"], "What is the disruption?")
        self.assertEqual(h[1]["role"], "assistant")   # gather text
        self.assertEqual(h[2]["role"], "assistant")   # compose answer
        self.assertEqual(h[2]["content"], "D01 is the disruption.")

    def test_history_structure_with_tool_call(self):
        """History for a turn with one tool call includes correct message sequence."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "tc1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "gather text"},
            {"content": "PO01 is delayed 6 days."},
        ])
        result = run_agent("Tell me about D01.", llm=llm)
        h = result["history"]
        # user, assistant(tool_calls), tool, gather-assistant, compose-assistant
        self.assertEqual(len(h), 5)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[1]["role"], "assistant")
        self.assertIn("tool_calls", h[1])
        self.assertEqual(h[1].get("content"), "")
        fn = h[1]["tool_calls"][0]["function"]
        self.assertIsInstance(fn["arguments"], str)
        json.loads(fn["arguments"])  # must be valid JSON
        self.assertEqual(h[2]["role"], "tool")
        self.assertIn("tool_call_id", h[2])
        self.assertEqual(h[2]["tool_call_id"], "tc1")
        self.assertEqual(h[3]["role"], "assistant")   # gather text
        self.assertEqual(h[4]["role"], "assistant")   # compose answer
        self.assertEqual(h[4]["content"], "PO01 is delayed 6 days.")

    def test_history_no_fabricated_tool_content(self):
        """History must not contain fabricated '[tool call: ...]' text."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "tc1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "gather"},
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
            {"content": "gather"},
            {"content": "Two tools called."},
        ])
        result = run_agent("Tell me everything about D01.", llm=llm)
        self.assertEqual(len(result["tool_trace"]), 2)
        names = [t["name"] for t in result["tool_trace"]]
        self.assertIn("get_disruption", names)
        self.assertIn("get_impact", names)

    def test_duplicate_call_returns_note(self):
        """Same tool+args called twice: second call gets note, engine called once."""
        llm = ScriptedLLM([
            # Step 1: call get_disruption
            {"tool_calls": [{"id": "c1", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            # Step 2: call it again with same args
            {"tool_calls": [{"id": "c2", "name": "get_disruption",
                             "args": {"disruption_id": "D01"}}]},
            {"content": "gather"},
            {"content": "Composed."},
        ])
        result = run_agent("Tell me again.", llm=llm, max_steps=10)
        self.assertEqual(len(result["tool_trace"]), 2)
        # First call: real engine result (has disruption_id)
        self.assertIn("disruption_id", result["tool_trace"][0]["result"])
        # Second call: duplicate guard note
        self.assertIn("note", result["tool_trace"][1]["result"])
        self.assertIn("already called", result["tool_trace"][1]["result"]["note"])

    def test_duplicate_guard_engine_called_once(self):
        """Engine is called exactly once for a duplicated (name, args) pair."""
        call_count = [0]
        original_call_tool = __import__("agent.tool_specs", fromlist=["call_tool"]).call_tool

        def counting_call_tool(name, args, offered_names=None):
            if name == "get_disruption":
                call_count[0] += 1
            return original_call_tool(name, args, offered_names=offered_names)

        import agent.loop as loop_module
        original = loop_module.call_tool
        loop_module.call_tool = counting_call_tool
        try:
            llm = ScriptedLLM([
                {"tool_calls": [{"id": "c1", "name": "get_disruption",
                                 "args": {"disruption_id": "D01"}}]},
                {"tool_calls": [{"id": "c2", "name": "get_disruption",
                                 "args": {"disruption_id": "D01"}}]},
                {"content": "gather"},
                {"content": "Done."},
            ])
            run_agent("Repeat?", llm=llm, max_steps=10)
        finally:
            loop_module.call_tool = original

        self.assertEqual(call_count[0], 1)

    def test_propose_action_still_yields_pending(self):
        """propose_action via run_agent still returns pending_approval status."""
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "propose_action",
                             "args": {"scenario_id": "HYBRID",
                                      "reason": "best option"}}]},
            {"content": "gather"},
            {"content": "Proposal HYBRID is pending approval."},
        ])
        result = run_agent("Propose HYBRID", llm=llm)
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["status"], "pending_approval")


# ── prompts ───────────────────────────────────────────────────────────────────

class TestPrompts(unittest.TestCase):

    def test_compose_instruction_contains_na_rule(self):
        """The compose instruction must contain the n/a policy rule."""
        from agent.prompts import _COMPOSE_INSTRUCTION
        self.assertIn("n/a", _COMPOSE_INSTRUCTION)
        # The rule must reference tool results as the only allowed source
        self.assertIn("tool result", _COMPOSE_INSTRUCTION.lower())

    def test_compose_instruction_forbids_contact(self):
        """The compose instruction must tell the model not to direct users elsewhere."""
        from agent.prompts import _COMPOSE_INSTRUCTION
        self.assertIn("contact", _COMPOSE_INSTRUCTION.lower())

    def test_system_prompt_playbook_has_all_four_scenarios(self):
        """Recommendation playbook must list all 4 named scenarios for get_priority_view."""
        from agent.prompts import SYSTEM_PROMPT
        for scenario in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            self.assertIn(scenario, SYSTEM_PROMPT)

    def test_system_prompt_unsupported_includes_compare_scenarios(self):
        """Unsupported-question playbook must include compare_scenarios."""
        from agent.prompts import SYSTEM_PROMPT
        # Find the unsupported section and check compare_scenarios appears in it
        idx = SYSTEM_PROMPT.find("different delay length")
        self.assertGreater(idx, 0)
        unsupported_section = SYSTEM_PROMPT[idx:]
        self.assertIn("compare_scenarios", unsupported_section)

    def test_build_compose_message_contains_na_rule(self):
        """build_compose_message output must carry the n/a rule."""
        from agent.prompts import build_compose_message
        msg = build_compose_message("test question")
        self.assertIn("n/a", msg["content"])
        self.assertEqual(msg["role"], "user")


# ── normalise ─────────────────────────────────────────────────────────────────

class TestNormalise(unittest.TestCase):
    """Tests for scripts/eval_agent.normalise (pure function, no network)."""

    @classmethod
    def setUpClass(cls):
        # Import here so the test file works even without dotenv loaded
        from scripts.eval_agent import normalise
        cls.normalise = staticmethod(normalise)

    def test_lowercase(self):
        self.assertEqual(self.normalise("TRANSFER"), "transfer")

    def test_dollar_stripped(self):
        self.assertEqual(self.normalise("$1,216"), "1216")

    def test_comma_between_digits_stripped(self):
        self.assertEqual(self.normalise("$1,216 USD"), "1216 usd")

    def test_comma_not_stripped_in_text(self):
        """Comma not between digits must be kept."""
        result = self.normalise("Hello, world")
        self.assertIn(",", result)

    def test_unicode_en_dash_normalised(self):
        """U+2013 EN DASH → '-'"""
        self.assertEqual(self.normalise("trade\u2013offs"), "trade-offs")

    def test_unicode_em_dash_normalised(self):
        """U+2014 EM DASH → '-'"""
        self.assertEqual(self.normalise("cost\u2014benefit"), "cost-benefit")

    def test_unicode_minus_sign_normalised(self):
        """U+2212 MINUS SIGN → '-'"""
        self.assertEqual(self.normalise("5\u22126"), "5-6")

    def test_non_breaking_space_normalised(self):
        """U+00A0 NON-BREAKING SPACE → regular space"""
        result = self.normalise("5\u00a0of\u00a06")
        self.assertEqual(result, "5 of 6")

    def test_5_out_of_6_matches_after_normalise(self):
        """'5 out of 6' pattern survives normalisation and is found."""
        answer = "Priority-1 orders: 5 out of 6 are on time."
        self.assertIn("5 out of 6", self.normalise(answer))

    def test_1216_found_after_stripping_comma_and_dollar(self):
        """'$1,216' in answer → '1216' after normalisation."""
        answer = "The cheapest option costs $1,216."
        self.assertIn("1216", self.normalise(answer))

    def test_unicode_dash_in_trade_offs_heading(self):
        """'Trade\u2013offs and risks' → 'trade-offs and risks' (matches heading)."""
        answer = "## Trade\u2013offs and Risks"
        self.assertIn("trade-offs and risks", self.normalise(answer))

    def test_of_12_stays_separate(self):
        """'of 12' must NOT be joined — 'of' before single digit stays a word."""
        result = self.normalise("11 of 12 orders are on time.")
        self.assertIn("of 12", result)
        self.assertNotIn("of12", result)

    def test_the_11_stays_separate(self):
        """'the 11' must NOT be joined."""
        result = self.normalise("the 11 orders delivered on time.")
        self.assertIn("the 11", result)
        self.assertNotIn("the11", result)

    def test_so_02_joined(self):
        """'SO 02' IS a known ID prefix+2 digits and must be joined to 'so02'."""
        result = self.normalise("Order SO 02 is late.")
        self.assertIn("so02", result)
        self.assertNotIn("so 02", result)

    def test_po_01_joined(self):
        """'PO 01' → 'po01'."""
        result = self.normalise("PO 01 delayed.")
        self.assertIn("po01", result)

    def test_wh_01_joined(self):
        """'WH 01' → 'wh01' (unambiguous prefix)."""
        result = self.normalise("Warehouse WH 01 holds stock.")
        self.assertIn("wh01", result)


# ── coercion ─────────────────────────────────────────────────────────────────

class TestCoercion(unittest.TestCase):
    """Tests for call_tool type coercion (integer and boolean fields)."""

    def test_budget_as_numeric_string_accepted(self):
        """budget='500' is coerced to 500 and passes validation."""
        result = call_tool("compare_scenarios", {"budget": "500"})
        self.assertNotIn("error", result)
        self.assertIn("ranked", result)

    def test_budget_as_int_accepted(self):
        result = call_tool("compare_scenarios", {"budget": 500})
        self.assertNotIn("error", result)

    def test_budget_as_non_numeric_string_rejected(self):
        result = call_tool("compare_scenarios", {"budget": "five hundred"})
        self.assertIn("error", result)

    def test_budget_as_bool_rejected(self):
        result = call_tool("compare_scenarios", {"budget": True})
        self.assertIn("error", result)

    def test_include_transfers_string_false_is_false(self):
        """include_transfers='false' must be coerced to False, not truthy string."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": "false",
        })
        self.assertNotIn("error", result)
        # When include_transfers=False no transfer actions should appear in ranked actions
        for r in result["ranked"]:
            transfer_actions = [a for a in r.get("actions", []) if a["type"] == "transfer"]
            self.assertEqual(transfer_actions, [])

    def test_include_transfers_string_true_is_true(self):
        """include_transfers='true' must be coerced to True."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": "true",
        })
        self.assertNotIn("error", result)

    def test_include_transfers_string_TRUE_case_insensitive(self):
        """'TRUE' (uppercase) also coerces to True."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": "TRUE",
        })
        self.assertNotIn("error", result)

    def test_include_transfers_bad_value_rejected(self):
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": "yes",
        })
        self.assertIn("error", result)

    def test_qty_as_string_coerced(self):
        """qty='45' is coerced to int for propose_action."""
        result = call_tool("propose_action", {
            "offer_id": "OF02",
            "qty": "45",
            "include_transfers": True,
            "reason": "coercion test",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "pending_approval")

    def test_qty_as_bad_value_rejected(self):
        result = call_tool("propose_action", {
            "offer_id": "OF02",
            "qty": "forty-five",
            "reason": "bad qty",
        })
        self.assertIn("error", result)


# ── min_on_time_orders ────────────────────────────────────────────────────────

class TestMinOnTimeOrders(unittest.TestCase):
    """Tests for explore_purchase_qty min_on_time_orders filter."""

    def test_min_11_objective_cost_best_qty_40_cost_1216(self):
        """OF02, include_transfers=True, min_on_time_orders=11, objective='cost'
        -> rank-1 option has purchase_qty=40 and total_extra_cost=1216."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": True,
            "min_on_time_orders": 11,
            "objective": "cost",
        })
        self.assertNotIn("error", result)
        best = result["ranked"][0]
        self.assertEqual(best["purchase_qty"], 40)
        self.assertEqual(best["total_extra_cost"], 1216)

    def test_min_11_excludes_low_on_time_options(self):
        """All ranked options must have on_time_orders >= 11."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "include_transfers": True,
            "min_on_time_orders": 11,
        })
        for r in result["ranked"]:
            self.assertGreaterEqual(r["on_time_orders"], 11)

    def test_min_on_time_as_string_coerced(self):
        """min_on_time_orders='11' is coerced to int."""
        result = call_tool("explore_purchase_qty", {
            "offer_id": "OF02",
            "min_on_time_orders": "11",
        })
        self.assertNotIn("error", result)


# ── disrupted-offer guard ─────────────────────────────────────────────────────

class TestDisruptedOfferGuard(unittest.TestCase):
    """Tests for the disrupted-supplier guard in call_tool."""

    def _get_disrupted_offer_id(self) -> str:
        """Look up the disrupted offer ID from engine data."""
        from engine.loader import load_all
        db = load_all()
        po = db["purchase_orders"][db["disruptions"]["D01"]["po_id"]]
        return po["offer_id"]

    def test_explore_disrupted_offer_returns_error(self):
        disrupted_oid = self._get_disrupted_offer_id()
        result = call_tool("explore_purchase_qty", {"offer_id": disrupted_oid})
        self.assertIn("error", result)
        self.assertIn("disrupted supplier", result["error"])

    def test_propose_disrupted_offer_returns_error(self):
        disrupted_oid = self._get_disrupted_offer_id()
        result = call_tool("propose_action", {
            "offer_id": disrupted_oid,
            "qty": 40,
            "reason": "trying disrupted offer",
        })
        self.assertIn("error", result)
        self.assertIn("disrupted supplier", result["error"])

    def test_alternative_offer_of02_not_disrupted(self):
        """OF02 must NOT be the disrupted offer (it's the recovery offer)."""
        result = call_tool("explore_purchase_qty", {"offer_id": "OF02"})
        self.assertNotIn("error", result)


# ── propose_action guard in loop ──────────────────────────────────────────────

class TestProposeActionGate(unittest.TestCase):
    """Tests for the heuristic that hides propose_action for non-action messages."""

    def test_propose_hidden_without_action_intent(self):
        """Tool list for a recommendation question must NOT include propose_action."""
        from agent.tool_specs import tool_specs_for
        specs = tool_specs_for("Our budget is 500 dollars. What should we do?")
        names = {s["function"]["name"] for s in specs}
        self.assertNotIn("propose_action", names)

    def test_propose_present_with_approve_keyword(self):
        from agent.tool_specs import tool_specs_for
        specs = tool_specs_for("Approve HYBRID now.")
        names = {s["function"]["name"] for s in specs}
        self.assertIn("propose_action", names)

    def test_propose_present_with_implement_keyword(self):
        from agent.tool_specs import tool_specs_for
        specs = tool_specs_for("Let's implement the TRANSFER option.")
        names = {s["function"]["name"] for s in specs}
        self.assertIn("propose_action", names)

    def test_propose_present_with_submit_keyword(self):
        from agent.tool_specs import tool_specs_for
        specs = tool_specs_for("Submit the plan for approval.")
        names = {s["function"]["name"] for s in specs}
        self.assertIn("propose_action", names)

    def test_propose_hidden_for_impact_question(self):
        from agent.tool_specs import tool_specs_for
        specs = tool_specs_for("How bad is this disruption?")
        names = {s["function"]["name"] for s in specs}
        self.assertNotIn("propose_action", names)

    def test_run_agent_uses_action_intent_gate(self):
        """run_agent with non-action message never sees propose_action spec."""
        received_specs = []

        class CapturingLLM:
            def chat(self_inner, messages, tools):  # noqa: N805
                received_specs.append([s["function"]["name"] for s in tools])
                if len(received_specs) == 1:
                    return {"content": "gather", "tool_calls": []}
                return {"content": "composed", "tool_calls": []}

        run_agent("Which option is best?", llm=CapturingLLM())
        # Gather-phase call (index 0) must not include propose_action
        self.assertNotIn("propose_action", received_specs[0])


# ── tool-offer guard ─────────────────────────────────────────────────────────

class TestToolOfferGuard(unittest.TestCase):
    """Tests for the call-time tool-offer enforcement (fix 1)."""

    def test_hidden_tool_blocked_at_call_time(self):
        """call_tool with offered_names that excludes a tool returns an error."""
        offered = {"get_disruption", "get_impact", "compare_scenarios"}
        result = call_tool("propose_action", {"scenario_id": "HYBRID", "reason": "r"},
                           offered_names=offered)
        self.assertIn("error", result)
        self.assertIn("not available", result["error"])
        self.assertIn("propose_action", result["error"])

    def test_offered_tool_not_blocked(self):
        """call_tool with offered_names that includes the tool proceeds normally."""
        offered = {"get_disruption", "propose_action"}
        result = call_tool("propose_action",
                           {"scenario_id": "HYBRID", "reason": "test"},
                           offered_names=offered)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "pending_approval")

    def test_none_offered_names_no_guard(self):
        """offered_names=None disables the guard entirely."""
        result = call_tool("propose_action",
                           {"scenario_id": "HYBRID", "reason": "test"},
                           offered_names=None)
        self.assertNotIn("error", result)

    def test_run_agent_blocks_propose_on_non_action_turn(self):
        """propose_action called by the LLM on a non-action turn gets blocked."""
        # Non-action message -> propose_action is not in offered tools
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "c1", "name": "propose_action",
                             "args": {"scenario_id": "HYBRID",
                                      "reason": "sneak approval"}}]},
            {"content": "gather"},
            {"content": "Composed."},
        ])
        result = run_agent("Which scenario is best?", llm=llm)
        # The tool trace must show an error (blocked), not a pending_approval
        self.assertIn("error", result["tool_trace"][0]["result"])
        self.assertIsNone(result["proposal"])


# ── no angle-bracket placeholders ─────────────────────────────────────────────

class TestNoPlaceholders(unittest.TestCase):
    """SYSTEM_PROMPT and compose instruction must not contain < ... > placeholders."""

    def test_system_prompt_no_angle_brackets(self):
        from agent.prompts import SYSTEM_PROMPT
        import re
        placeholders = re.findall(r"<[^>]+>", SYSTEM_PROMPT)
        self.assertEqual(placeholders, [],
                         f"Found angle-bracket placeholders: {placeholders}")

    def test_compose_instruction_no_angle_brackets(self):
        from agent.prompts import _COMPOSE_INSTRUCTION
        import re
        placeholders = re.findall(r"<[^>]+>", _COMPOSE_INSTRUCTION)
        self.assertEqual(placeholders, [],
                         f"Found angle-bracket placeholders: {placeholders}")


# ── grounding check ───────────────────────────────────────────────────────────

class TestGroundingCheck(unittest.TestCase):
    """Tests for check_grounding and normalise in eval_agent."""

    @classmethod
    def setUpClass(cls):
        from scripts.eval_agent import check_grounding, normalise
        cls.check_grounding = staticmethod(check_grounding)
        cls.normalise = staticmethod(normalise)

    def _make_result(self, answer, tool_results=None, question="Test?"):
        """Build a minimal result dict for grounding tests."""
        trace = []
        for r in (tool_results or []):
            trace.append({"name": "mock_tool", "args": {}, "result": r})
        return {"answer": answer, "tool_trace": trace, "question": question}

    def test_grounded_number_passes(self):
        """A number from tool results is grounded."""
        result = self._make_result(
            answer="The delay is 6 days.",
            tool_results=[{"delay_days": 6}],
        )
        ungrounded = self.check_grounding(result)
        self.assertNotIn("6", ungrounded)

    def test_invented_number_flagged(self):
        """A number not in tool results or question is flagged."""
        result = self._make_result(
            answer="The extra cost is 9999 USD.",
            tool_results=[{"delay_days": 6}],
        )
        ungrounded = self.check_grounding(result)
        self.assertIn("9999", ungrounded)

    def test_denominator_12_exempt(self):
        """'12' (orders denominator) is always exempt."""
        result = self._make_result(
            answer="11 of 12 orders are on time.",
            tool_results=[{"on_time_orders": 11}],
        )
        ungrounded = self.check_grounding(result)
        self.assertNotIn("12", ungrounded)

    def test_denominator_6_exempt(self):
        """'6' (priority-1 denominator) is always exempt."""
        result = self._make_result(
            answer="5 of 6 priority-1 orders on time.",
            tool_results=[{"on_time_count": 5}],
        )
        ungrounded = self.check_grounding(result)
        self.assertNotIn("6", ungrounded)

    def test_thin_space_1216_normalised(self):
        """'1\u2009216' (thin space) normalises to '1216'."""
        result = self.normalise("cost: 1\u2009216 USD")
        self.assertIn("1216", result)

    def test_so02_split_normalised(self):
        """'SO 02' normalises to 'so02'."""
        result = self.normalise("Order SO 02 is late.")
        self.assertIn("so02", result)

    def test_narrow_no_break_space_1216(self):
        """U+202F narrow no-break space between digits collapses to nothing."""
        result = self.normalise("1\u202f216")
        self.assertIn("1216", result)

    def test_uuid_not_flagged(self):
        """UUID in answer is not flagged as ungrounded."""
        uuid = "a3b4c5d6-1234-5678-abcd-ef0123456789"
        result = self._make_result(
            answer=f"Proposal {uuid} created.",
            tool_results=[{"proposal_id": uuid, "status": "pending_approval"}],
        )
        ungrounded = self.check_grounding(result)
        # No UUID fragment (1234, 5678, etc.) should appear
        self.assertNotIn("1234", ungrounded)
        self.assertNotIn("5678", ungrounded)

    def test_uuid_not_in_answer_not_flagged(self):
        """UUID that appears only in the answer is also stripped and not flagged."""
        uuid = "ffffffff-0000-1111-2222-333333333333"
        result = self._make_result(
            answer=f"Proposal ID: {uuid}.",
            tool_results=[{"delay_days": 6}],
        )
        ungrounded = self.check_grounding(result)
        self.assertEqual(ungrounded, [])

    def test_invented_2000_flagged(self):
        """An invented number like 2000 not in any tool result is flagged."""
        result = self._make_result(
            answer="The cost is 2000 USD.",
            tool_results=[{"total_extra_cost": 1216}],
        )
        ungrounded = self.check_grounding(result)
        self.assertIn("2000", ungrounded)
        self.assertNotIn("1216", ungrounded)


# ── explore best not null ─────────────────────────────────────────────────────

class TestExploreBestField(unittest.TestCase):
    """Tests for the 'best' field in explore_purchase_qty results."""

    def test_explore_best_is_not_null_with_min_on_time(self):
        """explore_purchase_qty with min_on_time_orders -> best is a dict, not None."""
        from engine.tools import explore_purchase_qty
        result = explore_purchase_qty(
            "OF02",
            include_transfers=True,
            min_on_time_orders=11,
            objective="cost",
        )
        self.assertIsNotNone(result["best"])
        self.assertIsInstance(result["best"], dict)
        self.assertEqual(result["best"]["qty"], 40)

    def test_explore_best_dict_has_required_keys(self):
        """best dict must have label, offer_id, qty, include_transfers."""
        from engine.tools import explore_purchase_qty
        result = explore_purchase_qty("OF02", include_transfers=True)
        best = result["best"]
        self.assertIsInstance(best, dict)
        self.assertIn("label", best)
        self.assertIn("offer_id", best)
        self.assertIn("qty", best)
        self.assertIn("include_transfers", best)

    def test_explore_best_offer_id_is_of02(self):
        """offer_id extracted from label must be 'OF02'."""
        from engine.tools import explore_purchase_qty
        result = explore_purchase_qty("OF02")
        self.assertEqual(result["best"]["offer_id"], "OF02")

    def test_explore_best_include_transfers_true_when_transfers(self):
        """best with transfers has include_transfers=True."""
        from engine.tools import explore_purchase_qty
        result = explore_purchase_qty("OF02", include_transfers=True)
        self.assertTrue(result["best"]["include_transfers"])

    def test_explore_best_include_transfers_false_without_transfers(self):
        """best without transfers has include_transfers=False."""
        from engine.tools import explore_purchase_qty
        result = explore_purchase_qty("OF02", include_transfers=False)
        self.assertFalse(result["best"]["include_transfers"])


# ── late_order_count and late_count ──────────────────────────────────────────

class TestCountFields(unittest.TestCase):
    """Tests for additive count fields on get_impact and get_priority_view."""

    def test_get_impact_has_late_order_count(self):
        """get_impact must return late_order_count."""
        from engine.tools import get_impact
        result = get_impact("D01")
        self.assertIn("late_order_count", result)
        self.assertIsInstance(result["late_order_count"], int)

    def test_get_impact_late_order_count_matches_list(self):
        """late_order_count must equal len(late_orders)."""
        from engine.tools import get_impact
        result = get_impact("D01")
        self.assertEqual(result["late_order_count"], len(result["late_orders"]))

    def test_get_priority_view_has_late_count(self):
        """get_priority_view must return late_count."""
        from engine.tools import get_priority_view
        result = get_priority_view(scenario_id="HYBRID")
        self.assertIn("late_count", result)
        self.assertIsInstance(result["late_count"], int)

    def test_get_priority_view_late_count_plus_on_time_equals_total(self):
        """late_count + on_time_count must equal total_count."""
        from engine.tools import get_priority_view
        result = get_priority_view(scenario_id="HYBRID")
        self.assertEqual(
            result["late_count"] + result["on_time_count"],
            result["total_count"],
        )

    def test_get_priority_view_late_count_wait(self):
        """WAIT scenario: 4 of 6 priority-1 orders are late."""
        from engine.tools import get_priority_view
        result = get_priority_view(scenario_id="WAIT")
        self.assertEqual(result["late_count"], result["total_count"] - result["on_time_count"])



class TestNullLikeArgs(unittest.TestCase):
    """Eval run 4: Llama sent budget "null" and offer_id "null"."""

    def test_null_string_budget_is_ignored(self):
        r = call_tool("compare_scenarios", {"budget": "null", "objective": "cost"})
        self.assertNotIn("error", r)
        self.assertIsNone(r["budget"])

    def test_none_and_empty_strings_are_ignored(self):
        for v in ("None", "", "  NULL "):
            r = call_tool("compare_scenarios", {"budget": v})
            self.assertNotIn("error", r, msg=repr(v))

    def test_null_offer_id_reports_missing(self):
        r = call_tool("explore_purchase_qty", {"offer_id": "null"})
        self.assertIn("error", r)
        self.assertIn("offer_id", r["error"])


class TestSystemPromptProposeGate(unittest.TestCase):
    """Eval run 4: Llama called propose_action because the prompt named it."""

    def test_no_propose_prompt_does_not_name_the_tool(self):
        from agent.prompts import build_system_prompt
        self.assertNotIn("propose_action", build_system_prompt(False))
        self.assertIn("propose_action", build_system_prompt(True))

    def test_recommendation_turn_uses_no_propose_prompt(self):
        llm = ScriptedLLM([{"content": "gathered"}, {"content": "final"}])
        seen = []
        orig = llm.chat

        def spy(messages, tools):
            seen.append(messages[0]["content"])
            return orig(messages, tools)

        llm.chat = spy
        run_agent("Our budget is 500 dollars. What should we do?", llm=llm)
        self.assertNotIn("propose_action", seen[0])

    def test_action_turn_uses_propose_prompt(self):
        llm = ScriptedLLM([{"content": "gathered"}, {"content": "final"}])
        seen = []
        orig = llm.chat

        def spy(messages, tools):
            seen.append(messages[0]["content"])
            return orig(messages, tools)

        llm.chat = spy
        run_agent("Approve HYBRID now.", llm=llm)
        self.assertIn("propose_action", seen[0])


class TestLateOrderCount(unittest.TestCase):
    """The engine reports late_orders so the LLM never subtracts."""

    def test_compare_entries_have_late_orders(self):
        import engine.tools as t
        for r in t.compare_scenarios()["ranked"]:
            self.assertEqual(r["late_orders"], r["total_orders"] - r["on_time_orders"])

    def test_proposal_metrics_have_late_orders(self):
        import engine.tools as t
        m = t.propose_action("HYBRID", "test")["metrics"]
        self.assertEqual(m["late_orders"], 1)
        self.assertEqual(m["total_orders"], 12)


class TestCheckTable(unittest.TestCase):
    """Table check against engine ground truth (scripts/eval_agent.py)."""

    _HEADER = (
        "## Options compared\n"
        "| Option | On-time orders (of 12) | Priority-1 on time (of 6) | Extra cost USD |\n"
        "|---|---|---|---|\n"
    )

    def _check(self, rows):
        from scripts.eval_agent import check_table
        return check_table(self._HEADER + rows + "\n## Recommendation\nx")

    def test_correct_table_passes(self):
        rows = (
            "| TRANSFER | 8 | 4 | 416 |\n"
            "| WAIT | 5 | 2 | 0 |\n"
            "| Transfers + buy 40 x OF02 | 11 | n/a | $1,216 |"
        )
        self.assertEqual(self._check(rows), [])

    def test_wrong_column_is_flagged(self):
        # Llama run 4 Q4 put priority-1 counts into the on-time column
        self.assertTrue(self._check("| HYBRID | 5 | 5 | n/a |"))

    def test_invented_priority_for_explored_option_is_flagged(self):
        # Granite run 4 Q4 wrote 6 of 6 for explored options
        self.assertTrue(self._check("| Transfers + buy 40 units (OF02) | 11 | 6 | 1,216 |"))

    def test_thin_spaces_and_bold_are_parsed(self):
        rows = "| **HYBRID** | **11** | **5** | **1\u202f306** |"
        self.assertEqual(self._check(rows), [])

    def test_text_cell_is_not_a_number(self):
        rows = "| ALT_BUY | n/a | n/a | not viable within budget |"
        self.assertEqual(self._check(rows), [])

    def test_no_table_returns_empty(self):
        from scripts.eval_agent import check_table
        self.assertEqual(check_table("## Answer\nNo table here."), [])



class TestOrderDetail(unittest.TestCase):
    """get_order_detail explains lateness (added after eval run 5)."""

    def test_hybrid_so08_component_shortage(self):
        import engine.tools as t
        d = t.get_order_detail("SO08", scenario_id="HYBRID")
        self.assertEqual(d["days_late"], 2)
        self.assertEqual(d["latest_start_date"], "2026-11-15")
        self.assertEqual(d["cause"]["type"], "component_shortage")
        self.assertEqual(d["cause"]["shortfall"], {"C01": 18})

    def test_wait_so03_blocked_behind_so02(self):
        import engine.tools as t
        d = t.get_order_detail("SO03")  # no option -> WAIT
        self.assertEqual(d["option"], "WAIT")
        self.assertEqual(d["cause"]["type"], "queue_blocked")
        self.assertEqual(d["cause"]["waiting_order_id"], "SO02")
        self.assertEqual(d["cause"]["shortfall"], {"C01": 8})

    def test_wait_so02_shortfall_matches_impact_table(self):
        import engine.tools as t
        d = t.get_order_detail("SO02", scenario_id="WAIT")
        day = d["cause"]["check_date"]
        table = {r["date"]: r for r in t.get_impact("D01")["c01_shortage_by_day"]}
        self.assertEqual(d["cause"]["shortfall"]["C01"], table[day]["shortage"])

    def test_explored_option(self):
        import engine.tools as t
        d40 = t.get_order_detail("SO08", offer_id="OF02", qty=40, include_transfers=True)
        d65 = t.get_order_detail("SO08", offer_id="OF02", qty=65, include_transfers=True)
        self.assertEqual(d40["option"], "Transfers + buy 40 x OF02")
        self.assertEqual(d40["cause"]["shortfall"], {"C01": 23})
        self.assertEqual(d65["cause"], {"type": "on_time"})

    def test_on_time_order(self):
        import engine.tools as t
        self.assertEqual(t.get_order_detail("SO01", scenario_id="HYBRID")["cause"],
                         {"type": "on_time"})

    def test_call_tool_validation(self):
        self.assertIn("error", call_tool("get_order_detail", {}))
        self.assertIn("error", call_tool("get_order_detail", {"order_id": "SO99"}))
        self.assertIn("error", call_tool("get_order_detail",
                                         {"order_id": "SO08", "offer_id": "OF02", "qty": 41}))
        self.assertIn("error", call_tool("get_order_detail",
                                         {"order_id": "SO08", "offer_id": "OF01", "qty": 40}))
        r = call_tool("get_order_detail", {"order_id": "SO08", "scenario_id": "HYBRID"})
        self.assertEqual(r["days_late"], 2)


class TestPriorityViewExplored(unittest.TestCase):
    """Priority-1 view for explored options (added after eval run 5)."""

    def test_explored_40_and_65(self):
        r40 = call_tool("get_priority_view",
                        {"offer_id": "OF02", "qty": "40", "include_transfers": "true"})
        r65 = call_tool("get_priority_view",
                        {"offer_id": "OF02", "qty": 65, "include_transfers": True})
        self.assertEqual(r40["on_time_count"], 5)
        self.assertEqual(r65["on_time_count"], 6)

    def test_named_scenario_unchanged(self):
        self.assertEqual(call_tool("get_priority_view", {"scenario_id": "HYBRID"})["on_time_count"], 5)

    def test_needs_an_option(self):
        self.assertIn("error", call_tool("get_priority_view", {}))
        self.assertIn("error", call_tool("get_priority_view", {"offer_id": "OF02"}))
        self.assertIn("error", call_tool("get_priority_view",
                                         {"scenario_id": "HYBRID", "offer_id": "OF02", "qty": 40}))


class _FailingLLM:
    """Fake LLM that raises on a chosen call number."""

    def __init__(self, script, fail_on):
        self._inner = ScriptedLLM(script)
        self._n = 0
        self._fail_on = fail_on

    def chat(self, messages, tools):
        self._n += 1
        if self._n == self._fail_on:
            raise ConnectionError("simulated network failure")
        return self._inner.chat(messages, tools)


class TestLLMUnavailable(unittest.TestCase):
    """API failures must not crash run_agent (added after eval run 5)."""

    def test_failure_in_gather_returns_safe_answer(self):
        r = run_agent("How bad is this disruption?", llm=_FailingLLM([], fail_on=1))
        self.assertIn("could not be reached", r["answer"])
        self.assertIn("ConnectionError", r["error"])
        self.assertIsNone(r["proposal"])

    def test_failure_in_compose_keeps_trace(self):
        script = [
            {"tool_calls": [{"id": "1", "name": "get_impact", "args": {"disruption_id": "D01"}}]},
            {"content": "gathered"},
        ]
        r = run_agent("How bad is this disruption?", llm=_FailingLLM(script, fail_on=3))
        self.assertIn("could not be reached", r["answer"])
        self.assertEqual(r["tool_trace"][0]["name"], "get_impact")

    def test_safe_answer_has_no_digits(self):
        r = run_agent("x", llm=_FailingLLM([], fail_on=1))
        self.assertFalse(any(ch.isdigit() for ch in r["answer"]))

    def test_watsonx_wrapper_retries_then_raises(self):
        from agent.llm import WatsonxLLM, LLMUnavailableError
        w = WatsonxLLM.__new__(WatsonxLLM)   # skip __init__ (no credentials)
        calls = {"n": 0}

        class _Model:
            def chat(self, **kw):
                calls["n"] += 1
                raise TimeoutError("slow")

        w._model, w._chat_params, w._retries, w._backoff_s = _Model(), None, 2, 0
        with self.assertRaises(LLMUnavailableError):
            w.chat([{"role": "user", "content": "hi"}], [])
        self.assertEqual(calls["n"], 3)

    def test_watsonx_wrapper_recovers_after_one_failure(self):
        from agent.llm import WatsonxLLM
        w = WatsonxLLM.__new__(WatsonxLLM)
        calls = {"n": 0}

        class _Model:
            def chat(self, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise TimeoutError("slow")
                return {"choices": [{"message": {"content": "ok"}}]}

        w._model, w._chat_params, w._retries, w._backoff_s = _Model(), None, 2, 0
        self.assertEqual(w.chat([], [])["content"], "ok")


class TestFollowUpProposal(unittest.TestCase):
    """Multi-turn: 'propose that one' after an explore question."""

    def test_follow_up_proposes_explored_option(self):
        turn1 = ScriptedLLM([
            {"tool_calls": [{"id": "a", "name": "explore_purchase_qty", "args": {
                "offer_id": "OF02", "include_transfers": True,
                "min_on_time_orders": 11, "objective": "cost"}}]},
            {"content": "gathered"},
            {"content": "Transfers + buy 40 x OF02 keeps 11 orders for 1216 USD."},
        ])
        r1 = run_agent("Is there a cheaper way than HYBRID to keep 11 orders on time?", llm=turn1)
        self.assertIsNone(r1["proposal"])
        turn2 = ScriptedLLM([
            {"tool_calls": [{"id": "b", "name": "propose_action", "args": {
                "offer_id": "OF02", "qty": 40, "include_transfers": True,
                "reason": "cheapest option with 11 on time"}}]},
            {"content": "done"},
            {"content": "Proposal created, pending approval."},
        ])
        r2 = run_agent("Propose that option.", history=r1["history"], llm=turn2)
        p = r2["proposal"]
        self.assertEqual(p["status"], "pending_approval")
        self.assertEqual(p["metrics"]["on_time_orders"], 11)
        self.assertEqual(p["metrics"]["total_extra_cost"], 1216)



class TestEvalHarnessExtensions(unittest.TestCase):
    """Golden set Q7-Q13, multi-turn runner and --runs (added after eval run 5)."""

    def _q(self, qid):
        from scripts.eval_agent import GOLDEN_QUESTIONS
        return next(q for q in GOLDEN_QUESTIONS if q["id"] == qid)

    def _result(self, tools, answer, proposal=None):
        trace = [{"name": n, "args": a, "result": call_tool(n, a)} for n, a in tools]
        return {"question": "x", "answer": answer, "tool_trace": trace,
                "proposal": proposal, "earlier_tools": []}

    def test_golden_set_has_13_questions(self):
        from scripts.eval_agent import GOLDEN_QUESTIONS
        self.assertEqual([q["id"] for q in GOLDEN_QUESTIONS],
                         [f"Q{i}" for i in range(1, 14)])

    def test_parse_args(self):
        from scripts.eval_agent import _parse_args, _MODELS
        self.assertEqual(_parse_args(["--runs", "3"]), (list(_MODELS), 3, False))
        self.assertEqual(_parse_args(["m1", "--runs=2", "--full"]), (["m1"], 2, True))

    def test_wrong_recommendation_fails(self):
        from scripts.eval_agent import _check_question
        ans = ("## Situation\nBudget given.\n## Options compared\nSee tools.\n"
               "## Recommendation\nChoose HYBRID.\n## Trade-offs and risks\nNone.\n"
               "## Next step\nAsk me.")
        ok, why = _check_question(self._q("Q7"), self._result(
            [("compare_scenarios", {"budget": "1000"})], ans))
        self.assertFalse(ok)
        self.assertIn("TRANSFER", why)

    def test_tool_args_mismatch_fails(self):
        from scripts.eval_agent import _check_question
        ans = "## Answer\nSO08 is 2 days late, short 18 C01 on 2026-11-15."
        ok, why = _check_question(self._q("Q9"), self._result(
            [("get_order_detail", {"order_id": "SO08", "scenario_id": "TRANSFER"})], ans))
        self.assertFalse(ok)
        self.assertIn("get_order_detail", why)

    def test_explored_priority_in_table_is_checked(self):
        from scripts.eval_agent import check_table
        head = ("## Options compared\n| Option | On-time | Priority-1 | Cost |\n"
                "|---|---|---|---|\n")
        self.assertEqual(check_table(head + "| Transfers + buy 40 x OF02 | 11 | 5 | 1216 |"), [])
        self.assertTrue(check_table(head + "| Transfers + buy 40 x OF02 | 11 | 6 | 1216 |"))

    def test_multi_turn_runner_and_q12_pass(self):
        from scripts.eval_agent import _run_question, _check_question
        llm = ScriptedLLM([
            # turn 1: explore, then gather text, then compose
            {"tool_calls": [{"id": "a", "name": "explore_purchase_qty", "args": {
                "offer_id": "OF02", "include_transfers": True,
                "min_on_time_orders": 11, "objective": "cost"}}]},
            {"content": "gathered"},
            {"content": "Transfers + buy 40 x OF02 keeps 11 orders on time for 1216 USD."},
            # turn 2: propose, then gather text, then compose
            {"tool_calls": [{"id": "b", "name": "propose_action", "args": {
                "offer_id": "OF02", "qty": 40, "include_transfers": True,
                "reason": "cheapest option with 11 on time"}}]},
            {"content": "done"},
            {"content": "A proposal for Transfers + buy 40 x OF02 is pending approval "
                        "in the UI. Nothing has been executed."},
        ])
        q = self._q("Q12")
        result = _run_question(q, llm)
        self.assertEqual([t["name"] for t in result["earlier_tools"]], ["explore_purchase_qty"])
        ok, why = _check_question(q, result)
        self.assertTrue(ok, why)



class TestRun6Fixes(unittest.TestCase):
    """Fixes from the 3x evaluation run (eval_results/20261107_213952.json)."""

    def test_order_detail_summary_contains_shortfall(self):
        import engine.tools as t
        s = t.get_order_detail("SO08", offer_id="OF02", qty=40, include_transfers=True)["summary"]
        self.assertIn("23 x C01", s)
        self.assertIn("2 days late", s)
        s3 = t.get_order_detail("SO03")["summary"]
        self.assertIn("behind SO02", s3)
        self.assertIn("8 x C01", s3)

    def test_proposal_notice_is_appended_by_code(self):
        # Q12 run 2: the model wrote a recommendation and never mentioned the proposal
        llm = ScriptedLLM([
            {"tool_calls": [{"id": "p", "name": "propose_action",
                             "args": {"scenario_id": "HYBRID", "reason": "asked"}}]},
            {"content": "done"},
            {"content": "## Recommendation\nTell me which option you'd like."},
        ])
        r = run_agent("Approve HYBRID now.", llm=llm)
        self.assertIn("pending approval in the UI", r["answer"])
        self.assertIn(r["proposal"]["proposal_id"], r["answer"])
        self.assertIn("Nothing has been executed", r["answer"])

    def test_no_notice_without_proposal(self):
        llm = ScriptedLLM([{"content": "x"}, {"content": "answer"}])
        r = run_agent("How bad is this disruption?", llm=llm)
        self.assertNotIn("pending approval", r["answer"])

    def test_compose_message_flags_proposal(self):
        from agent.prompts import build_compose_message
        self.assertIn("proposal WAS created", build_compose_message("q", True)["content"])
        self.assertNotIn("proposal WAS created", build_compose_message("q", False)["content"])

    def test_disruption_id_is_grounded(self):
        from scripts.eval_agent import check_grounding
        r = {"question": "x", "answer": "Disruption D01 is active.",
             "tool_trace": [], "earlier_tools": []}
        self.assertEqual(check_grounding(r), [])

    def test_q11_accepts_bare_count(self):
        from scripts.eval_agent import _check_question, GOLDEN_QUESTIONS
        q = next(q for q in GOLDEN_QUESTIONS if q["id"] == "Q11")
        args = {"offer_id": "OF02", "qty": 40, "include_transfers": True}
        trace = [{"name": "get_priority_view", "args": args,
                  "result": call_tool("get_priority_view", args)}]
        ans = "## Answer\nFor that option, 5 priority-1 orders are on time."
        ok, why = _check_question(q, {"question": "x", "answer": ans, "tool_trace": trace,
                                      "proposal": None, "earlier_tools": []})
        self.assertTrue(ok, why)



class TestRun7Fixes(unittest.TestCase):
    """Fixes from eval_results/20261107_215130.json (Q13 0/3, Q5 1/3)."""

    def test_compose_message_targets_latest_message(self):
        from agent.prompts import build_compose_message
        c = build_compose_message("With that option, why is SO08 still late?")["content"]
        self.assertIn("Answer THIS latest user message", c)
        self.assertIn("Latest user message: With that option", c)
        self.assertNotIn("Original question", c)

    def test_get_disruption_has_scope_note(self):
        import engine.tools as t
        note = t.get_disruption("D01")["scope_note"]
        self.assertIn("recorded delay of 6 days", note)
        self.assertIn("not supported yet", note)

    def test_only_filter(self):
        from scripts import eval_agent as ea
        ea._parse_args(["--only", "q5,Q13"])
        self.assertEqual(ea._ONLY, {"Q5", "Q13"})
        ea._parse_args([])
        self.assertEqual(ea._ONLY, set())


if __name__ == "__main__":
    unittest.main()
