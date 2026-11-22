"""
ui/tests/test_app_regression.py — AppTest-based regression tests for app.py

Covers the two verified Stage A defects and their fixes:

Defect 1 (Live mode does not block fixture interactions):
  - Switching to Live mode clears messages, active_result, active_proposal,
    submitted_request, and selector widget state.
  - Live mode shows the unavailable explanation and hides fixture controls.
  - Navigating between pages while Live is selected cannot bypass the guard.
  - Switching back to Fixtures starts cleanly.

Defect 2 (Answers from typed questions disappear on rerun):
  - A saved question submitted through the form remains visible after rerun.
  - Repeated reruns do not duplicate messages.
  - Navigation preserves the conversation state.
  - New conversation clears messages, results, proposals, and selections.

Additional coverage:
  - Selecting a proposal fixture then switching to Live removes the proposal.
  - Unmatched input shows the limitation message, not a substituted result.
  - Normal and error fixtures with identical question text are independently
    selectable (different fixture_ids).
  - Ordinary rerun does not duplicate messages after fixture selection.

Important: This module must NOT import ui.state through the fake-streamlit
stub in test_state.py.  Test isolation is enforced by that module restoring
sys.modules["streamlit"] after its own import.  These tests use the real
Streamlit AppTest runtime.
"""
import os
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

# Helpers ------------------------------------------------------------------
# AppTest.from_file resolves relative paths against the calling file's
# directory (ui/tests/), so we use an absolute path instead.
_APP_PATH = str(Path(__file__).parent.parent.parent / "app.py")
_TIMEOUT = 30

# Selector indices in the find_plan selectbox:
#   0  = placeholder "— select an example —"
#   1  = fixture 0  (conv1_t1_i0):  success, "Our budget is 500 dollars..."
#   22 = fixture 21 (conv19_t3_i21): proposal fixture "Go with it."
#   23 = fixture 22 (converror_t1_i22): error fixture "Our budget is 500 dollars..."
_IDX_SUCCESS_500 = 1
_IDX_PROPOSAL = 22
_IDX_ERROR_500 = 23

_QUESTION_MATCHED = "Our budget is 500 dollars. What should we do?"
_QUESTION_UNMATCHED = "This question does not match any saved example XYZ987"


def _boot() -> AppTest:
    """Create and run a fresh AppTest instance starting at the overview page."""
    at = AppTest.from_file(_APP_PATH, default_timeout=_TIMEOUT)
    at.run()
    return at


def _go_to_find_plan(at: AppTest) -> AppTest:
    at.button(key="nav_find_plan").click()
    at.run()
    return at


# ==========================================================================
# Defect 2 — Typed question answer persists across reruns
# ==========================================================================

class TestTypedQuestionPersistence(unittest.TestCase):

    def test_answer_visible_after_submit(self):
        """Submitting a matched typed question shows messages immediately."""
        at = _boot()
        _go_to_find_plan(at)
        at.text_input(key="free_text_find_plan").input(_QUESTION_MATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        msgs = at.session_state.get("display_messages", [])
        self.assertGreater(len(msgs), 0, "No messages stored after form submission")
        self.assertEqual(len(at.exception), 0, f"App raised exception: {list(at.exception)}")

    def test_answer_persists_after_ordinary_rerun(self):
        """The answer survives a plain rerun without change."""
        at = _boot()
        _go_to_find_plan(at)
        at.text_input(key="free_text_find_plan").input(_QUESTION_MATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        count_after_submit = len(at.session_state.get("display_messages", []))
        self.assertGreater(count_after_submit, 0)

        # Plain rerun
        at.run()
        count_after_rerun = len(at.session_state.get("display_messages", []))
        self.assertEqual(
            count_after_submit,
            count_after_rerun,
            "Message count changed on a plain rerun — answer either vanished or duplicated",
        )

    def test_repeated_reruns_do_not_duplicate_messages(self):
        """Three consecutive reruns must not inflate message count."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        base = len(at.session_state.get("display_messages", []))
        self.assertGreater(base, 0)

        at.run()
        at.run()
        after = len(at.session_state.get("display_messages", []))
        self.assertEqual(base, after, "Messages were duplicated across reruns")

    def test_fixture_selection_stores_in_display_messages(self):
        """Selecting a fixture populates display_messages with user + assistant msgs."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        msgs = at.session_state.get("display_messages", [])
        types = [m["type"] for m in msgs]
        self.assertIn("user", types)
        self.assertIn("assistant", types)

    def test_navigation_preserves_conversation(self):
        """Navigating away and back keeps existing display_messages."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        count_before = len(at.session_state.get("display_messages", []))
        self.assertGreater(count_before, 0)

        # Navigate to compare, then back to find_plan
        at.button(key="nav_compare").click()
        at.run()
        at.button(key="nav_find_plan").click()
        at.run()
        count_after = len(at.session_state.get("display_messages", []))
        self.assertEqual(count_before, count_after, "Navigation cleared display_messages")

    def test_new_conversation_clears_state(self):
        """New conversation resets messages, active_result, proposal, and selection."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        self.assertGreater(len(at.session_state.get("display_messages", [])), 0)

        at.button(key="new_conv").click()
        at.run()

        self.assertEqual(at.session_state.get("display_messages"), [])
        self.assertIsNone(at.session_state.get("active_result"))
        self.assertIsNone(at.session_state.get("active_proposal"))
        self.assertIsNone(at.session_state.get("submitted_request"))
        # Selector widget key must have been removed
        self.assertNotIn("fixture_selector_find_plan", at.session_state)
        self.assertEqual(at.session_state.get("current_page"), "overview")


# ==========================================================================
# Defect 1 — Live mode blocks fixture interactions
# ==========================================================================

class TestLiveModeBlocking(unittest.TestCase):

    def test_live_mode_shows_unavailable_warning(self):
        """Switching to Live on the find_plan page shows the unavailable warning."""
        at = _boot()
        _go_to_find_plan(at)
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        warnings = [w.value for w in at.warning]
        self.assertTrue(
            any("not available" in w.lower() for w in warnings),
            f"Expected unavailable warning; got warnings: {warnings}",
        )

    def test_live_mode_hides_fixture_selector(self):
        """In Live mode the fixture selectbox must not be rendered."""
        at = _boot()
        _go_to_find_plan(at)
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertEqual(len(at.selectbox), 0, "Fixture selector visible in Live mode")

    def test_live_mode_hides_text_input(self):
        """In Live mode the free-text question form must not be rendered."""
        at = _boot()
        _go_to_find_plan(at)
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertEqual(len(at.text_input), 0, "Text input visible in Live mode")

    def test_live_mode_clears_prior_fixture_result(self):
        """Switching to Live clears active_result loaded while in Fixtures mode."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        self.assertIsNotNone(at.session_state.get("active_result"))

        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertIsNone(at.session_state.get("active_result"))

    def test_live_mode_clears_prior_proposal(self):
        """Switching to Live removes an active_proposal from a proposal fixture."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_PROPOSAL)
        at.run()
        self.assertIsNotNone(at.session_state.get("active_proposal"))

        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertIsNone(at.session_state.get("active_proposal"))

    def test_live_mode_clears_display_messages(self):
        """Switching to Live removes all display_messages."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        self.assertGreater(len(at.session_state.get("display_messages", [])), 0)

        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertEqual(at.session_state.get("display_messages"), [])

    def test_live_mode_clears_selector_widget(self):
        """Switching to Live deletes the selector widget key from session_state."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()

        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        self.assertNotIn("fixture_selector_find_plan", at.session_state)

    def test_live_mode_blocked_on_all_non_overview_pages(self):
        """The live guard fires on compare and impact pages too."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()

        for page_btn_key in ("nav_compare", "nav_impact"):
            at.button(key=page_btn_key).click()
            at.run()
            self.assertEqual(len(at.selectbox), 0,
                             f"Fixture selector visible on {page_btn_key} in Live mode")
            warnings = [w.value for w in at.warning]
            self.assertTrue(
                any("not available" in w.lower() for w in warnings),
                f"No unavailable warning on {page_btn_key} in Live mode",
            )

    def test_live_mode_overview_shows_unavailable(self):
        """Overview page also shows the unavailable message in Live mode."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        # Still on overview
        self.assertEqual(at.session_state.get("current_page"), "overview")
        warnings = [w.value for w in at.warning]
        self.assertTrue(
            any("not available" in w.lower() for w in warnings),
            f"No unavailable warning on overview in Live mode; got: {warnings}",
        )

    def test_switch_back_to_fixtures_starts_cleanly(self):
        """Switching Fixtures → Live → Fixtures gives a clean, empty conversation."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        at.radio(key="mode_radio").set_value("Fixtures")
        at.run()

        self.assertEqual(at.session_state.get("mode"), "fixtures")
        self.assertEqual(at.session_state.get("display_messages"), [])
        self.assertIsNone(at.session_state.get("active_result"))

        # Navigating to find_plan should show the fixture selector.
        _go_to_find_plan(at)
        self.assertGreater(len(at.selectbox), 0, "No fixture selector after returning to Fixtures")


# ==========================================================================
# Error and success fixtures with identical question text
# ==========================================================================

class TestDuplicateQuestionFixtures(unittest.TestCase):

    def test_error_and_success_fixture_independently_selectable(self):
        """Select success fixture first, new conversation, then select error fixture."""
        at = _boot()
        _go_to_find_plan(at)

        # Select the success fixture (index 1)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        success_msgs = list(at.session_state.get("display_messages", []))
        self.assertTrue(success_msgs, "No messages after selecting success fixture")
        success_last = success_msgs[-1]
        self.assertFalse(success_last.get("is_error"), "Success fixture marked as error")

        # New conversation then select error fixture (index 23)
        at.button(key="new_conv").click()
        at.run()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR_500)
        at.run()
        error_msgs = list(at.session_state.get("display_messages", []))
        self.assertTrue(error_msgs, "No messages after selecting error fixture")
        error_last = error_msgs[-1]
        self.assertTrue(error_last.get("is_error"), "Error fixture not marked as error")

        # The two fixture_ids must differ
        self.assertNotEqual(
            success_msgs[-1].get("fixture_id"),
            error_msgs[-1].get("fixture_id"),
            "Success and error fixtures share fixture_id",
        )


# ==========================================================================
# Unmatched input
# ==========================================================================

class TestUnmatchedInput(unittest.TestCase):

    def test_unmatched_input_shows_limitation_message(self):
        """Submitting an unmatched question shows the info limitation message."""
        at = _boot()
        _go_to_find_plan(at)
        at.text_input(key="free_text_find_plan").input(_QUESTION_UNMATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        infos = [i.value for i in at.info]
        self.assertTrue(
            any("saved examples" in i.lower() for i in infos),
            f"Expected limitation info message; got: {infos}",
        )

    def test_unmatched_input_does_not_set_active_result(self):
        """Submitting an unmatched question must not populate active_result."""
        at = _boot()
        _go_to_find_plan(at)
        at.text_input(key="free_text_find_plan").input(_QUESTION_UNMATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        self.assertIsNone(
            at.session_state.get("active_result"),
            "active_result was set for an unmatched question",
        )

    def test_unmatched_message_persists_after_rerun(self):
        """The unmatched limitation message is stored and persists on rerun."""
        at = _boot()
        _go_to_find_plan(at)
        at.text_input(key="free_text_find_plan").input(_QUESTION_UNMATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        msgs1 = len(at.session_state.get("display_messages", []))
        at.run()
        msgs2 = len(at.session_state.get("display_messages", []))
        self.assertEqual(msgs1, msgs2, "Unmatched message count changed on rerun")
        self.assertGreater(msgs1, 0, "No messages recorded for unmatched input")


if __name__ == "__main__":
    unittest.main()
