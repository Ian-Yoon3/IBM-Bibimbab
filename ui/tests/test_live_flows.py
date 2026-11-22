"""Live-mode flows driven through the real pages with a fake agent.

The other UI tests pre-seed st.session_state.  These tests press the buttons:
they check which message reaches run_agent, that no call is made without an API
key, and that a decision is written only by a click.  They control the
environment themselves, so the result does not depend on a local .env file:
dotenv.load_dotenv is replaced by a no-op and the WX_* variables are set or
removed per test.  No test calls watsonx.ai or writes to decisions/.
"""
import copy
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ui.fixtures import is_error_fixture, load_fixtures

_APP_PATH = str(Path(__file__).parent.parent.parent / "app.py")
_WX_KEYS = ("WX_API_KEY", "WX_PROJECT_ID", "WX_URL", "WX_MODEL_ID")


class FakeAgent:
    """Stands in for agent.loop.run_agent and records every call."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return copy.deepcopy(self.results[min(len(self.calls), len(self.results)) - 1])


@contextmanager
def app_env(*, api_key: bool, agent: FakeAgent, log_path: str = ""):
    env = {k: v for k, v in os.environ.items() if k not in _WX_KEYS}
    if api_key:
        env["WX_API_KEY"] = "test-key-not-real"
    if log_path:
        env["DECISION_LOG_PATH"] = log_path
    with patch("dotenv.load_dotenv", lambda *a, **k: False), \
            patch.dict(os.environ, env, clear=True), \
            patch("agent.loop.run_agent", agent):
        yield


def _boot_live(page_key: str) -> AppTest:
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    at.radio(key="mode_radio").set_value("Live agent")
    at.run()
    at.button(key=page_key).click()
    at.run()
    return at


def _click_label(at: AppTest, label: str) -> None:
    matches = [b for b in at.button if b.label == label]
    assert len(matches) == 1, f"{label!r}: {[b.label for b in at.button]}"
    matches[0].click()
    at.run()


def _rendered(at: AppTest) -> str:
    return " ".join(str(e.value) for e in list(at.markdown) + list(at.info)
                    + list(at.warning) + list(at.error) + list(at.success))


def _fixture(predicate) -> dict:
    found = [e for e in load_fixtures() if predicate(e)]
    assert found, "no saved example matches"
    return copy.deepcopy(found[0]["result"])


def _recommendation_with_budget() -> dict:
    """A saved recommendation whose starred option is within the stated budget."""
    def ok(e):
        v = (e["result"].get("view") or {})
        return (not is_error_fixture(e["result"]) and v.get("type") == "recommendation"
                and v.get("recommended") and (v.get("settings") or {}).get("budget"))
    return _fixture(ok)


def _proposal_result() -> dict:
    return _fixture(lambda e: e["result"].get("proposal"))


class RiskQuestionLive(unittest.TestCase):
    QUESTION = "  What if PO01 arrives two days after the announced date?  "

    def test_without_key_no_call_and_guidance(self):
        agent = FakeAgent({"answer": "x", "proposal": None, "tool_trace": []})
        with app_env(api_key=False, agent=agent):
            at = _boot_live("nav_impact")
            self.assertEqual(len(at.exception), 0)
            self.assertEqual([t for t in at.text_input if t.key == "risk_question"], [])
            self.assertIn("WX_API_KEY", _rendered(at))
        self.assertEqual(agent.calls, [])

    def test_question_reaches_the_agent_and_the_answer_is_shown(self):
        answer = "ANSWER-7f3a for the risk question"
        agent = FakeAgent({"answer": answer, "proposal": None, "view": None,
                           "tool_trace": [{"name": "get_world_risk"}]})
        with app_env(api_key=True, agent=agent):
            at = _boot_live("nav_impact")
            at.text_input(key="risk_question").input(self.QUESTION)
            _click_label(at, "Ask")
            self.assertEqual(len(at.exception), 0)
            self.assertIn(answer, _rendered(at))
        self.assertEqual(agent.calls, [((self.QUESTION.strip(),), {})])

    def test_empty_question_makes_no_call(self):
        agent = FakeAgent({"answer": "x", "proposal": None, "tool_trace": []})
        with app_env(api_key=True, agent=agent):
            at = _boot_live("nav_impact")
            at.text_input(key="risk_question").input("   ")
            _click_label(at, "Ask")
        self.assertEqual(agent.calls, [])

    def test_agent_error_result_shows_the_safe_answer(self):
        agent = FakeAgent({"answer": "SAFE-MESSAGE-91", "proposal": None,
                           "tool_trace": [], "error": "ConnectionError: down"})
        with app_env(api_key=True, agent=agent):
            at = _boot_live("nav_impact")
            at.text_input(key="risk_question").input("How risky is each option?")
            _click_label(at, "Ask")
            self.assertEqual(len(at.exception), 0)
            self.assertIn("SAFE-MESSAGE-91", _rendered(at))


class FindPlanProposeDecide(unittest.TestCase):
    def setUp(self):
        self.rec = _recommendation_with_budget()
        self.rec["history"] = [{"role": "user", "content": "marker-history"}]
        self.code = self.rec["view"]["recommended"]
        self.budget = int(self.rec["view"]["settings"]["budget"])
        self.prop = _proposal_result()
        self.tmp = tempfile.TemporaryDirectory()
        self.log = str(Path(self.tmp.name) / "log.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _entries(self):
        p = Path(self.log)
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] \
            if p.exists() else []

    def _to_proposal(self, at):
        at.number_input(key="find_plan_budget_widget").set_value(self.budget)
        _click_label(at, "Find a recovery plan")
        _click_label(at, f"Create a proposal for {self.code}")

    def test_without_key_no_call(self):
        agent = FakeAgent(self.rec, self.prop)
        with app_env(api_key=False, agent=agent, log_path=self.log):
            at = _boot_live("nav_find_plan")
            at.number_input(key="find_plan_budget_widget").set_value(self.budget)
            _click_label(at, "Find a recovery plan")
            self.assertEqual(len(at.exception), 0)
        self.assertEqual(agent.calls, [])

    def test_propose_message_history_and_approval(self):
        agent = FakeAgent(self.rec, self.prop)
        with app_env(api_key=True, agent=agent, log_path=self.log):
            at = _boot_live("nav_find_plan")
            self._to_proposal(at)
            self.assertEqual(len(at.exception), 0)
            self.assertEqual(len(agent.calls), 2)
            self.assertEqual(agent.calls[1],
                             ((f"Propose {self.code}",), {"history": self.rec["history"]}))
            self.assertEqual(self._entries(), [], "nothing is decided without a click")

            # a click without a name records nothing
            at.button(key="fp_decision_approve").click()
            at.run()
            self.assertEqual(self._entries(), [])

            at.text_input(key="fp_decision_name").input("Dana Reviewer")
            at.button(key="fp_decision_approve").click()
            at.run()
            self.assertEqual(len(at.exception), 0)
            entries = self._entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["decided_by"], "Dana Reviewer")
            self.assertEqual(entries[0]["proposal_id"], self.prop["proposal"]["proposal_id"])
            self.assertEqual(entries[0]["decision"], "approved")
            # the controls are gone, so the same proposal cannot be decided twice
            at.run()
            self.assertEqual([b for b in at.button if b.key == "fp_decision_approve"], [])
            self.assertEqual(len(self._entries()), 1)
        self.assertEqual(len(agent.calls), 2, "deciding makes no agent call")

    def test_reject_is_recorded_as_not_approved(self):
        agent = FakeAgent(self.rec, self.prop)
        with app_env(api_key=True, agent=agent, log_path=self.log):
            at = _boot_live("nav_find_plan")
            self._to_proposal(at)
            at.text_input(key="fp_decision_name").input("Dana Reviewer")
            at.button(key="fp_decision_reject").click()
            at.run()
            entries = self._entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["decision"], "rejected")

    def test_no_proposal_in_the_answer_gives_no_controls(self):
        no_prop = {"answer": "NO-PROPOSAL-ANSWER-55", "proposal": None, "view": None,
                   "tool_trace": []}
        agent = FakeAgent(self.rec, no_prop)
        with app_env(api_key=True, agent=agent, log_path=self.log):
            at = _boot_live("nav_find_plan")
            self._to_proposal(at)
            self.assertEqual(len(at.exception), 0)
            self.assertEqual([b for b in at.button if "decision" in (b.key or "")], [])
            self.assertIn("No proposal was created", _rendered(at))
        self.assertEqual(self._entries(), [])


class EnvFile(unittest.TestCase):
    def test_app_reads_env_file_without_overriding(self):
        seen = []
        agent = FakeAgent({"answer": "x", "proposal": None, "tool_trace": []})
        with app_env(api_key=False, agent=agent):
            with patch("dotenv.load_dotenv", lambda *a, **k: seen.append(k) or False):
                at = AppTest.from_file(_APP_PATH, default_timeout=30)
                at.run()
        self.assertTrue(seen, "load_dotenv was not called")
        self.assertFalse(any(k.get("override") for k in seen))


if __name__ == "__main__":
    unittest.main()
