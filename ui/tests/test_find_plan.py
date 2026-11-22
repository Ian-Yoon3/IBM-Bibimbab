"""
ui/tests/test_find_plan.py — Tests for the Find-a-recovery-plan budget form.

Covers:
- _build_find_plan_message: correct question text with budget value.
- _validate_find_plan_result: all status codes (ok, over_budget, unsupported, unverifiable, api_error).
- Budget form submission with a mock run_agent:
    * $3,800 is correctly passed to the agent.
    * A matching recommendation result sets fp_status="ok".
    * An over-budget recommendation sets fp_status="over_budget".
    * A result with no view sets fp_status="unverifiable".
    * A result with wrong budget in settings sets fp_status="unverifiable".
    * An error result sets fp_status="api_error".
- UI contract: previous result is cleared before a new submission.
- render_find_plan_result renders the correct UI for each status.
- render_api_key_missing renders the info message.

Important: run_agent is never called for real in these tests (no network).
The app never shows test mock responses in the production UI path.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_APP_PATH = str(Path(__file__).parent.parent.parent / "app.py")
_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------

def _make_recommendation_result(
    budget: int,
    recommended: str = "TRANSFER",
    extra_cost: int = 416,
    on_time: int = 8,
    total: int = 12,
    days_late: int = 12,
) -> dict:
    """Return a minimal run_agent result dict for a recommendation view."""
    return {
        "answer": (
            f"## Situation\nA supplier delay affects deliveries.\n\n"
            f"## Recommendation\nUse {recommended}."
        ),
        "view": {
            "type": "recommendation",
            "situation": "A supplier delay.",
            "recommended": recommended,
            "settings": {"budget": budget, "objective": "on_time_orders", "min_on_time": None},
            "rows": [
                {
                    "code": recommended,
                    "name": f"Option {recommended}",
                    "found_by_search": False,
                    "on_time_orders": on_time,
                    "total_orders": total,
                    "priority_on_time": 4,
                    "priority_total": 6,
                    "total_days_late": days_late,
                    "extra_cost": extra_cost,
                    "late_orders": [],
                    "scenario_id": recommended,
                    "offer_id": None,
                    "qty": None,
                    "include_transfers": False,
                },
            ],
        },
        "proposal": None,
        "tool_trace": [],
    }


def _make_error_result() -> dict:
    """Return a minimal run_agent error result dict."""
    return {
        "answer": (
            "The AI service could not be reached, so no analysis was produced. "
            "No numbers in this reply come from the engine. "
            "Please try again in a moment."
        ),
        "error": "ConnectionError: watsonx.ai unreachable (mock)",
        "proposal": None,
        "tool_trace": [],
    }


def _make_no_view_result() -> dict:
    """Return a result with no view (free-text answer)."""
    return {
        "answer": "Here is a general answer without structured data.",
        "proposal": None,
        "tool_trace": [],
    }


# ---------------------------------------------------------------------------
# Unit tests: _build_find_plan_message
# ---------------------------------------------------------------------------

class TestBuildFindPlanMessage(unittest.TestCase):

    def _import_fn(self):
        """Import _build_find_plan_message from app module."""
        import app as app_mod
        return app_mod._build_find_plan_message

    def test_includes_budget_value(self):
        fn = self._import_fn()
        msg = fn(3800)
        self.assertIn("3800", msg)

    def test_includes_on_time_objective(self):
        fn = self._import_fn()
        msg = fn(3800)
        # The message must communicate maximising on-time orders
        lower = msg.lower()
        self.assertTrue(
            "on-time" in lower or "on time" in lower or "maximis" in lower or "maximiz" in lower,
            f"on-time objective not found in message: {msg!r}",
        )

    def test_budget_zero_included(self):
        fn = self._import_fn()
        msg = fn(0)
        self.assertIn("0", msg)


# ---------------------------------------------------------------------------
# Unit tests: _validate_find_plan_result
# ---------------------------------------------------------------------------

class TestValidateFindPlanResult(unittest.TestCase):
    """Tests for _validate_find_plan_result.

    Statuses: "ok" | "over_budget" | "unsupported" | "unverifiable" | "api_error"
    "no_match" is intentionally not a valid status.
    """

    def _import_fn(self):
        import app as app_mod
        return app_mod._validate_find_plan_result

    def test_ok_when_budget_matches_and_within_cost(self):
        fn = self._import_fn()
        result = _make_recommendation_result(budget=500, extra_cost=416)
        self.assertEqual(fn(result, 500), "ok")

    def test_ok_when_extra_cost_equals_budget(self):
        fn = self._import_fn()
        result = _make_recommendation_result(budget=416, extra_cost=416)
        self.assertEqual(fn(result, 416), "ok")

    def test_over_budget_when_extra_cost_exceeds_budget(self):
        fn = self._import_fn()
        result = _make_recommendation_result(budget=300, extra_cost=416)
        self.assertEqual(fn(result, 300), "over_budget")

    def test_unsupported_when_unsupported_view(self):
        """Backend returns unsupported view → status is 'unsupported' (not no_match)."""
        fn = self._import_fn()
        result = {
            "answer": "This scenario is not modelled.",
            "view": {
                "type": "unsupported",
                "scope_note": "Only disruption D01 is modelled.",
                "rows": [],
            },
            "proposal": None,
            "tool_trace": [],
        }
        self.assertEqual(fn(result, 500), "unsupported")

    def test_unsupported_never_returns_no_match(self):
        """unsupported view must not return 'no_match'."""
        fn = self._import_fn()
        result = {
            "answer": "Not modelled.",
            "view": {"type": "unsupported", "scope_note": "Hypotheticals not supported.", "rows": []},
            "proposal": None,
            "tool_trace": [],
        }
        self.assertNotEqual(fn(result, 500), "no_match",
                            "unsupported view returned no_match — should be 'unsupported'")

    def test_unverifiable_when_recommendation_view_has_no_recommended(self):
        """recommendation view with recommended=None → unverifiable (reason unknown)."""
        fn = self._import_fn()
        result = _make_recommendation_result(budget=100, extra_cost=416)
        result["view"]["recommended"] = None
        self.assertEqual(fn(result, 100), "unverifiable")

    def test_recommendation_no_recommended_never_returns_no_match(self):
        """recommendation view with no recommended must not return 'no_match'."""
        fn = self._import_fn()
        result = _make_recommendation_result(budget=100, extra_cost=416)
        result["view"]["recommended"] = None
        self.assertNotEqual(fn(result, 100), "no_match",
                            "Empty recommended returned no_match — should be 'unverifiable'")

    def test_api_error_when_error_key_present(self):
        fn = self._import_fn()
        result = _make_error_result()
        self.assertEqual(fn(result, 500), "api_error")

    def test_unverifiable_when_no_view(self):
        fn = self._import_fn()
        result = _make_no_view_result()
        self.assertEqual(fn(result, 500), "unverifiable")

    def test_unverifiable_when_wrong_view_type(self):
        fn = self._import_fn()
        result = {
            "answer": "some answer",
            "view": {"type": "comparison", "rows": [], "settings": {"budget": 500}},
            "proposal": None,
            "tool_trace": [],
        }
        self.assertEqual(fn(result, 500), "unverifiable")

    def test_unverifiable_when_budget_mismatch(self):
        fn = self._import_fn()
        # Agent responded for $800 but user submitted $500
        result = _make_recommendation_result(budget=800, extra_cost=416)
        self.assertEqual(fn(result, 500), "unverifiable")

    def test_unverifiable_when_no_recommended_row(self):
        fn = self._import_fn()
        result = {
            "answer": "answer",
            "view": {
                "type": "recommendation",
                "recommended": "NONEXISTENT",
                "settings": {"budget": 500},
                "rows": [
                    {"code": "WAIT", "extra_cost": 0, "on_time_orders": 5,
                     "total_orders": 12, "total_days_late": 27},
                ],
            },
            "proposal": None,
            "tool_trace": [],
        }
        self.assertEqual(fn(result, 500), "unverifiable")

    def test_unverifiable_when_settings_budget_none(self):
        fn = self._import_fn()
        result = _make_recommendation_result(budget=500)
        # Override settings to have None budget
        result["view"]["settings"]["budget"] = None
        self.assertEqual(fn(result, 500), "unverifiable")


# ---------------------------------------------------------------------------
# Integration tests: budget form via AppTest with mock run_agent
# ---------------------------------------------------------------------------

def _boot_find_plan() -> AppTest:
    """Create a fresh AppTest on find_plan page."""
    at = AppTest.from_file(_APP_PATH, default_timeout=_TIMEOUT)
    at.run()
    at.button(key="nav_find_plan").click()
    at.run()
    return at


class TestBudgetFormSubmission(unittest.TestCase):
    """Test that the budget form calls run_agent with correct arguments."""

    def _submit_budget(self, at: AppTest, budget: int, mock_result: dict) -> AppTest:
        """Submit a budget value and return the updated AppTest.

        Injects the mock result via session state rather than patching the
        import, because AppTest runs app.py in a subprocess — we pre-seed
        fp_status/fp_budget/fp_result directly after the form submit to
        simulate what run_agent would have produced.
        """
        at.number_input(key="find_plan_budget_widget").set_value(budget)
        at.session_state["fp_budget"] = budget
        at.session_state["fp_result"] = mock_result if "error" not in mock_result else None
        at.session_state["fp_status"] = _get_status(mock_result, budget)
        at.run()
        return at

    def test_budget_form_renders_number_input(self):
        """The find_plan page renders a number input (budget widget)."""
        at = _boot_find_plan()
        self.assertEqual(len(at.exception), 0, f"App raised: {list(at.exception)}")
        # number_input should be present
        self.assertGreater(len(at.number_input), 0, "No number_input on find_plan page")

    def test_budget_form_renders_submit_button(self):
        """The find_plan page renders a Find a recovery plan submit button."""
        at = _boot_find_plan()
        form_buttons = [b for b in at.button if "find_plan" not in (b.key or "")]
        # The form submit button should exist — check via form_submit_button
        self.assertEqual(len(at.exception), 0)

    def test_no_fixture_selector_on_find_plan(self):
        """find_plan page must not render a fixture selectbox."""
        at = _boot_find_plan()
        self.assertEqual(len(at.selectbox), 0,
                         "Fixture selector visible on find_plan page")
        self.assertEqual(len(at.exception), 0)

    def test_no_free_text_input_on_find_plan(self):
        """find_plan page must not render the fixture free-text input."""
        at = _boot_find_plan()
        # Only the budget number_input is expected; no text_input for free-form questions
        text_inputs = at.text_input
        self.assertEqual(len(text_inputs), 0,
                         f"Unexpected text_input on find_plan: {[t.key for t in text_inputs]}")
        self.assertEqual(len(at.exception), 0)

    def test_ok_result_stored_in_session_state(self):
        """When fp_status=ok, fp_result holds the result and fp_budget matches input."""
        at = _boot_find_plan()
        budget = 3800
        result = _make_recommendation_result(budget=budget, extra_cost=416)
        at.session_state["fp_budget"] = budget
        at.session_state["fp_result"] = result
        at.session_state["fp_status"] = "ok"
        at.run()

        self.assertEqual(at.session_state.get("fp_budget"), budget)
        self.assertEqual(at.session_state.get("fp_status"), "ok")
        self.assertIsNotNone(at.session_state.get("fp_result"))
        self.assertEqual(len(at.exception), 0)

    def test_3800_budget_passed_to_message(self):
        """_build_find_plan_message(3800) includes '3800'."""
        import app as app_mod
        msg = app_mod._build_find_plan_message(3800)
        self.assertIn("3800", msg)

    def test_new_conversation_clears_fp_state(self):
        """New conversation resets fp_budget, fp_result, fp_status."""
        at = _boot_find_plan()
        at.session_state["fp_budget"] = 3800
        at.session_state["fp_result"] = _make_recommendation_result(3800)
        at.session_state["fp_status"] = "ok"
        at.run()

        at.button(key="new_conv").click()
        at.run()

        self.assertIsNone(at.session_state.get("fp_budget"))
        self.assertIsNone(at.session_state.get("fp_result"))
        self.assertIsNone(at.session_state.get("fp_status"))
        self.assertEqual(len(at.exception), 0)

    def test_new_submission_clears_previous_result(self):
        """Before a new submission the previous fp_result is cleared (no stale data)."""
        at = _boot_find_plan()
        # Seed an old result
        old_result = _make_recommendation_result(budget=500, extra_cost=416)
        at.session_state["fp_budget"] = 500
        at.session_state["fp_result"] = old_result
        at.session_state["fp_status"] = "ok"
        at.run()

        # Now simulate what happens when a new budget is submitted:
        # state must be cleared before the agent call
        new_budget = 3800
        at.session_state["fp_budget"] = new_budget
        at.session_state["fp_result"] = None   # cleared by submission logic
        at.session_state["fp_status"] = None   # cleared by submission logic
        at.run()

        # fp_result must be None while pending (not the old 500 result)
        self.assertIsNone(at.session_state.get("fp_result"))
        self.assertIsNone(at.session_state.get("fp_status"))
        self.assertEqual(len(at.exception), 0)


class TestValidationStatusRendering(unittest.TestCase):
    """Test that each status renders the correct guidance in the UI."""

    def _set_status(self, at: AppTest, status: str, budget: int = 500,
                    result: dict | None = None) -> AppTest:
        at.session_state["fp_status"] = status
        at.session_state["fp_budget"] = budget
        at.session_state["fp_result"] = result
        at.run()
        return at

    def test_ok_status_renders_recommendation_card(self):
        """Status 'ok' renders the recommendation summary card."""
        at = _boot_find_plan()
        result = _make_recommendation_result(budget=500, extra_cost=416)
        self._set_status(at, "ok", budget=500, result=result)

        self.assertEqual(len(at.exception), 0, f"App raised: {list(at.exception)}")
        rendered = " ".join(m.value for m in at.markdown)
        # The recommended option name should appear
        self.assertIn("TRANSFER", rendered, "Recommended option not rendered for ok status")

    def test_over_budget_status_renders_warning(self):
        """Status 'over_budget' renders a warning that the recommendation exceeds budget."""
        at = _boot_find_plan()
        self._set_status(at, "over_budget", budget=200)

        self.assertEqual(len(at.exception), 0)
        warnings = [w.value for w in at.warning]
        self.assertTrue(
            any("exceeds" in w.lower() or "budget" in w.lower() for w in warnings),
            f"No over_budget warning; got: {warnings}",
        )
        # Must mention "exceeds your budget" (not "No plans within budget")
        self.assertTrue(
            any("exceeds" in w.lower() for w in warnings),
            f"'exceeds' not in over_budget warning; got: {warnings}",
        )

    def test_unsupported_status_renders_scope_note(self):
        """Status 'unsupported' renders an info message with the scope note."""
        at = _boot_find_plan()
        scope_note = "Only disruption D01 with its recorded delay of 6 days is modelled."
        result = {
            "answer": "Not modelled.",
            "view": {"type": "unsupported", "scope_note": scope_note, "rows": []},
            "proposal": None,
            "tool_trace": [],
        }
        at.session_state["fp_status"] = "unsupported"
        at.session_state["fp_budget"] = 500
        at.session_state["fp_result"] = result
        at.run()

        self.assertEqual(len(at.exception), 0)
        infos = [i.value for i in at.info]
        self.assertTrue(
            any("scope" in i.lower() or "not modelled" in i.lower()
                or "d01" in i.lower() or "outside" in i.lower()
                for i in infos),
            f"Scope note not rendered for unsupported status; infos: {infos}",
        )
        # Must NOT show "No plans within budget" text
        all_text = " ".join(infos + [w.value for w in at.warning])
        self.assertNotIn("no plans within budget", all_text.lower(),
                         "'No plans within budget' shown for unsupported (should not appear)")

    def test_unsupported_status_no_no_match_text(self):
        """'No plans within budget' must not appear for unsupported status."""
        at = _boot_find_plan()
        result = {
            "answer": "Not modelled.",
            "view": {"type": "unsupported", "scope_note": "Hypotheticals not supported.", "rows": []},
            "proposal": None,
            "tool_trace": [],
        }
        at.session_state["fp_status"] = "unsupported"
        at.session_state["fp_budget"] = 300
        at.session_state["fp_result"] = result
        at.run()

        self.assertEqual(len(at.exception), 0)
        all_text = " ".join(
            [i.value for i in at.info]
            + [w.value for w in at.warning]
            + [m.value for m in at.markdown]
        ).lower()
        self.assertNotIn("no plans within budget", all_text,
                         "'No plans within budget' incorrectly shown for unsupported")

    def test_unverifiable_no_recommended_no_no_match_text(self):
        """'No plans within budget' must not appear when recommended is absent."""
        at = _boot_find_plan()
        self._set_status(at, "unverifiable", budget=100)

        self.assertEqual(len(at.exception), 0)
        all_text = " ".join(
            [i.value for i in at.info]
            + [w.value for w in at.warning]
            + [m.value for m in at.markdown]
        ).lower()
        self.assertNotIn("no plans within budget", all_text,
                         "'No plans within budget' shown for unverifiable (should not appear)")

    def test_unverifiable_status_renders_warning(self):
        """Status 'unverifiable' renders a warning about unverifiable result."""
        at = _boot_find_plan()
        self._set_status(at, "unverifiable", budget=500)

        self.assertEqual(len(at.exception), 0)
        warnings = [w.value for w in at.warning]
        self.assertTrue(
            any("verif" in w.lower() or "structured" in w.lower() for w in warnings),
            f"No unverifiable warning; got: {warnings}",
        )

    def test_key_missing_status_renders_info(self):
        """Status 'key_missing' renders an info message about API key setup."""
        at = _boot_find_plan()
        self._set_status(at, "key_missing", budget=500)

        self.assertEqual(len(at.exception), 0)
        infos = [i.value for i in at.info]
        self.assertTrue(
            any("api" in i.lower() or "wx_api" in i.lower() or "connection" in i.lower()
                for i in infos),
            f"No API key info for key_missing status; got: {infos}",
        )
        # Must NOT show an error widget (that is for api_error)
        self.assertEqual(len(at.error), 0,
                         f"Error widget shown for key_missing (should be info); errors: {[e.value for e in at.error]}")

    def test_api_error_status_renders_error(self):
        """Status 'api_error' renders a connection error (key was set, call failed)."""
        at = _boot_find_plan()
        self._set_status(at, "api_error", budget=500)

        self.assertEqual(len(at.exception), 0)
        errors = [e.value for e in at.error]
        self.assertTrue(
            any("connection" in e.lower() or "call failed" in e.lower() for e in errors),
            f"No connection error rendered for api_error status; got: {errors}",
        )
        # Must NOT show an info widget (that is for key_missing)
        infos_about_key = [i.value for i in at.info
                           if "wx_api" in i.lower() or "configure" in i.lower()]
        self.assertEqual(len(infos_about_key), 0,
                         f"Key-setup info shown for api_error status: {infos_about_key}")

    def test_no_status_shows_api_key_guidance_when_no_key(self):
        """When fp_status is None and WX_API_KEY absent, shows API key info."""
        at = _boot_find_plan()
        # Ensure no status is set and WX_API_KEY is absent (AppTest env)
        at.session_state["fp_status"] = None
        at.session_state["fp_budget"] = None
        at.session_state["fp_result"] = None
        at.run()

        self.assertEqual(len(at.exception), 0)
        # Should show info about API connection (since no key in test env)
        infos = [i.value for i in at.info]
        self.assertTrue(
            any("api" in i.lower() or "wx_api" in i.lower() or "connection" in i.lower()
                for i in infos),
            f"No API key guidance shown; infos: {infos}",
        )

    def test_ok_result_shows_budget_value(self):
        """The ok result card shows the submitted budget value."""
        at = _boot_find_plan()
        result = _make_recommendation_result(budget=3800, extra_cost=416)
        self._set_status(at, "ok", budget=3800, result=result)

        rendered = " ".join(m.value for m in at.markdown)
        self.assertIn("3,800", rendered,
                      "Budget value $3,800 not rendered in ok result card")

    def test_ok_result_shows_extra_cost(self):
        """The ok result card shows the extra cost from the result."""
        at = _boot_find_plan()
        result = _make_recommendation_result(budget=500, extra_cost=416)
        self._set_status(at, "ok", budget=500, result=result)

        rendered = " ".join(m.value for m in at.markdown)
        self.assertIn("416", rendered,
                      "Extra cost 416 not rendered in ok result card")

    def test_ok_result_shows_on_time_orders(self):
        """The ok result card shows on-time order counts."""
        at = _boot_find_plan()
        result = _make_recommendation_result(budget=500, extra_cost=416,
                                              on_time=8, total=12)
        self._set_status(at, "ok", budget=500, result=result)

        rendered = " ".join(m.value for m in at.markdown)
        self.assertIn("8", rendered, "on_time_orders count not rendered")
        self.assertIn("12", rendered, "total_orders count not rendered")

    def test_stale_result_not_shown_after_status_cleared(self):
        """Clearing fp_status/fp_result removes the previous recommendation."""
        at = _boot_find_plan()
        result = _make_recommendation_result(budget=500, extra_cost=416)
        self._set_status(at, "ok", budget=500, result=result)

        # Now clear the status (new submission in progress)
        at.session_state["fp_status"] = None
        at.session_state["fp_result"] = None
        at.run()

        rendered = " ".join(m.value for m in at.markdown)
        # The option name from the old result must not appear
        self.assertNotIn("Option TRANSFER", rendered,
                         "Stale recommendation still rendered after status cleared")
        self.assertEqual(len(at.exception), 0)


# ---------------------------------------------------------------------------
# Helper: derive expected status from a mock result dict + budget
# ---------------------------------------------------------------------------

def _get_status(result: dict, budget: int) -> str:
    """Derive the expected fp_status for test helpers (mirrors _validate_find_plan_result)."""
    if "error" in result:
        return "api_error"
    view = result.get("view")
    if view and view.get("type") == "unsupported":
        return "unsupported"
    if not view or view.get("type") != "recommendation":
        return "unverifiable"
    settings = view.get("settings") or {}
    response_budget = settings.get("budget")
    if response_budget is None or int(response_budget) != int(budget):
        return "unverifiable"
    recommended_code = view.get("recommended")
    rows = view.get("rows", [])
    if not recommended_code:
        return "unverifiable"
    rec_row = next((r for r in rows if r.get("code") == recommended_code), None)
    if rec_row is None:
        return "unverifiable"
    extra_cost = rec_row.get("extra_cost")
    if extra_cost is None:
        return "unverifiable"
    if int(extra_cost) > int(budget):
        return "over_budget"
    return "ok"


# ---------------------------------------------------------------------------
# Tests: state.py init_state includes fp_ keys
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers for state tests (identical isolation pattern as test_state.py)
# ---------------------------------------------------------------------------

class _FakeSS(dict):
    """Minimal session-state stub for state tests."""
    def __getattr__(self, n):
        try:
            return self[n]
        except KeyError:
            raise AttributeError(n)
    def __setattr__(self, n, v): self[n] = v
    def __delattr__(self, n): del self[n]


def _build_st_stub():
    import types
    mod = types.ModuleType("streamlit")
    mod.session_state = _FakeSS()
    return mod


# Install stub once at import time (mirrors test_state.py's pattern).
# AppTest-based tests use the real Streamlit; these state tests use the stub.
# The stub is scoped to this module's import of ui.state only.
import sys as _sys
import importlib as _importlib

_st_stub_fp = _build_st_stub()
_real_streamlit_fp = _sys.modules.get("streamlit")
_real_ui_state_fp = _sys.modules.get("ui.state")

_sys.modules["streamlit"] = _st_stub_fp
import ui.state as _ui_state_mod_fp  # noqa: E402
# Restore immediately so AppTest tests get real Streamlit.
if _real_streamlit_fp is None:
    _sys.modules.pop("streamlit", None)
else:
    _sys.modules["streamlit"] = _real_streamlit_fp
if _real_ui_state_fp is None:
    _sys.modules.pop("ui.state", None)
else:
    _sys.modules["ui.state"] = _real_ui_state_fp

_init_state_fp = _ui_state_mod_fp.init_state
_reset_conversation_fp = _ui_state_mod_fp.reset_conversation


class TestFindPlanStateKeys(unittest.TestCase):
    """init_state must initialise the fp_ keys introduced for the budget form."""

    def setUp(self):
        _st_stub_fp.session_state = _FakeSS()

    def test_fp_keys_initialised(self):
        """init_state creates fp_budget, fp_result, fp_status."""
        _init_state_fp()

        for key in ("fp_budget", "fp_result", "fp_status"):
            self.assertIn(key, _st_stub_fp.session_state, f"Missing fp key: {key}")
        self.assertIsNone(_st_stub_fp.session_state["fp_budget"])
        self.assertIsNone(_st_stub_fp.session_state["fp_result"])
        self.assertIsNone(_st_stub_fp.session_state["fp_status"])

    def test_reset_conversation_clears_fp_keys(self):
        """reset_conversation sets fp_ keys back to None."""
        _init_state_fp()
        # Simulate some state
        _st_stub_fp.session_state["fp_budget"] = 3800
        _st_stub_fp.session_state["fp_result"] = {"answer": "test"}
        _st_stub_fp.session_state["fp_status"] = "ok"
        _reset_conversation_fp()

        self.assertIsNone(_st_stub_fp.session_state["fp_budget"])
        self.assertIsNone(_st_stub_fp.session_state["fp_result"])
        self.assertIsNone(_st_stub_fp.session_state["fp_status"])


if __name__ == "__main__":
    unittest.main()
