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


# ===========================================================================
# Stage A Regression Tests — Cases A through K
# Added to fix regressions A, B, and C (commit 495b7f5)
# ===========================================================================

# Indices in the find_plan selectbox (0 = placeholder):
_IDX_A = 1   # conv1_t1_i0  — $500 recommendation
_IDX_B = 2   # conv2_t1_i1  — $800 recommendation
_IDX_ERROR = 23  # converror_t1_i22 — error fixture (same question as _IDX_A)

# Exact question texts for the two non-error 500/800 fixtures
_Q_500 = "Our budget is 500 dollars. What should we do?"
_Q_800 = "We can spend up to $800. Which option?"

# Total number of non-placeholder fixture options
_TOTAL_FIXTURES = 23


class TestRegressionA_FirstSelectionDisplaysAnswer(unittest.TestCase):
    """Regression A: Every fixture displays its answer immediately after one
    selection interaction — no extra click or rerun required."""

    def _check_fixture_at_index(self, idx: int) -> None:
        """Select fixture at *idx* in a fresh session and verify answer rendered."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(idx)
        at.run()

        self.assertEqual(len(at.exception), 0,
                         f"App raised exception for fixture index {idx}: {list(at.exception)}")

        msgs = at.session_state.get("display_messages", [])
        self.assertGreaterEqual(len(msgs), 2,
                                f"Expected ≥2 messages for fixture {idx}, got {len(msgs)}")

        # Verify the assistant answer is actually rendered as markdown.
        # The last assistant message's answer text must appear in the
        # rendered markdown elements.
        last_assistant = next(
            (m for m in reversed(msgs) if m.get("type") == "assistant"), None
        )
        self.assertIsNotNone(last_assistant,
                             f"No assistant message in display_messages for fixture {idx}")

        # For error fixtures, the safe error answer is rendered.
        expected_answer = last_assistant["result"].get("answer", "")
        # At least the first 60 characters of the answer must appear in
        # the rendered markdown elements.
        rendered_texts = " ".join(m.value for m in at.markdown)
        snippet = expected_answer[:60]
        self.assertIn(snippet, rendered_texts,
                      f"Answer not rendered for fixture {idx}.\n"
                      f"Expected snippet: {snippet!r}\n"
                      f"Rendered: {rendered_texts[:300]!r}")

    def test_all_23_fixtures_display_answer_immediately(self):
        """All 23 fixtures show their answer after exactly one selection."""
        for idx in range(1, _TOTAL_FIXTURES + 1):
            with self.subTest(selector_index=idx):
                self._check_fixture_at_index(idx)


class TestRegressionB_SelectorDoesNotOverrideTypedQuestion(unittest.TestCase):
    """Regression B: A stale selector value does not override a new typed
    question on subsequent reruns."""

    def test_typed_500_then_800_keeps_800_as_current(self):
        """Select $500 fixture, then type the $800 question; $800 must stay current."""
        at = _boot()
        _go_to_find_plan(at)

        # Select $500 fixture (selector index 1)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv1_t1_i0",
            "submitted_request should point to $500 fixture after selection",
        )

        # Type the $800 question through the form
        at.text_input(key="free_text_find_plan").input(_Q_800)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()

        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
            "submitted_request should point to $800 fixture after form submission",
        )

        # Ordinary rerun — the selector widget still shows $500 but must
        # not replay that old selection.
        at.run()
        at.run()

        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
            "submitted_request reverted to $500 on ordinary rerun (Regression B)",
        )
        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(len(msgs), 4,
                         f"Expected exactly 4 messages (A+B), got {len(msgs)}")

        # Verify the $800 answer is rendered
        rendered_texts = " ".join(m.value for m in at.markdown)
        self.assertIn("$800", rendered_texts,
                      "$800 answer text not found after ordinary rerun")

        self.assertEqual(len(at.exception), 0,
                         f"App raised exception: {list(at.exception)}")

    def test_consecutive_different_fixtures_shows_newest(self):
        """Selecting A then B shows B as the current answer."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_B)
        at.run()

        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
            "After A→B, submitted_request should be B",
        )
        self.assertEqual(len(at.exception), 0)

    def test_explicit_a_b_a_selection_sequence(self):
        """Explicit A → B → A selector sequence keeps A as current result."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_B)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        # 6 messages: A user+assistant, B user+assistant, A user+assistant
        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(len(msgs), 6,
                         f"Expected 6 messages for A→B→A, got {len(msgs)}")

        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv1_t1_i0",
            "submitted_request should be A after explicit A→B→A selection",
        )

        user_fixture_ids = [
            m.get("fixture_id") for m in msgs if m.get("type") == "user"
        ]
        self.assertEqual(
            user_fixture_ids,
            ["conv1_t1_i0", "conv2_t1_i1", "conv1_t1_i0"],
            "Conversation order incorrect for A→B→A",
        )
        self.assertEqual(len(at.exception), 0)

    def test_ordinary_rerun_does_not_add_messages_after_selection(self):
        """An ordinary rerun after fixture selection does not add messages."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        base = len(at.session_state.get("display_messages", []))
        self.assertGreater(base, 0)

        at.run()
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])),
            base,
            "Ordinary rerun added messages (selector replay — Regression B)",
        )


class TestRegressionC_RepeatedErrorFixturesNoCrash(unittest.TestCase):
    """Regression C: Multiple historical error fixtures in one conversation
    must not crash with a duplicate element ID error."""

    def test_error_success_error_no_crash(self):
        """Error → success → error accumulates 6 messages without exception."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        self.assertEqual(len(at.exception), 0,
                         f"Exception after first error: {list(at.exception)}")

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertEqual(len(at.exception), 0,
                         f"Exception after success: {list(at.exception)}")

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        self.assertEqual(len(at.exception), 0,
                         f"Exception after second error (Regression C): {list(at.exception)}")

        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(len(msgs), 6,
                         f"Expected 6 messages for error→success→error, got {len(msgs)}")

        # Both error messages should be marked as errors
        error_msgs = [m for m in msgs if m.get("type") == "assistant" and m.get("is_error")]
        self.assertEqual(len(error_msgs), 2,
                         f"Expected 2 error assistant messages, got {len(error_msgs)}")

    def test_error_banner_text_distinct_from_app_exception(self):
        """The error fixture shows a warning banner, not an unhandled exception."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()

        # Must have zero unhandled exceptions
        self.assertEqual(len(at.exception), 0,
                         f"Unhandled exception: {list(at.exception)}")

        # The error answer text must be rendered
        rendered = " ".join(m.value for m in at.markdown)
        self.assertIn("AI service could not be reached", rendered,
                      "Error answer text not rendered")

    def test_retry_button_has_no_exception_for_accumulated_errors(self):
        """Retry buttons for accumulated error messages raise no exception."""
        at = _boot()
        _go_to_find_plan(at)

        # Accumulate two error fixtures
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()

        # Verify no duplicate-key exception from rendering two retry banners
        self.assertEqual(len(at.exception), 0,
                         f"Exception after accumulating two error messages: {list(at.exception)}")

        # Verify retry buttons are present (there should be 2 — one per error message)
        retry_buttons = [b for b in at.button if "retry_" in (b.key or "")]
        self.assertEqual(len(retry_buttons), 2,
                         f"Expected 2 retry buttons, got {len(retry_buttons)}: "
                         f"{[b.key for b in retry_buttons]}")


class TestRegressionG_UnmatchedInputAfterResult(unittest.TestCase):
    """Regression G: Unmatched input does not reuse the previous active result."""

    def test_unmatched_after_fixture_keeps_limitation_message(self):
        """After a fixture selection, an unmatched typed question shows limitation."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertIsNotNone(at.session_state.get("active_result"))

        at.text_input(key="free_text_find_plan").input(_QUESTION_UNMATCHED)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()

        # active_result remains from the previous fixture (not cleared by unmatched)
        # but the limitation message must be shown — the previous answer is NOT
        # presented as the response to the new unmatched question.
        infos = [i.value for i in at.info]
        self.assertTrue(
            any("saved examples" in i.lower() for i in infos),
            f"Limitation message not shown after unmatched input; infos: {infos}",
        )

        msgs = at.session_state.get("display_messages", [])
        last_msg = msgs[-1] if msgs else None
        self.assertIsNotNone(last_msg)
        self.assertEqual(last_msg.get("type"), "unmatched",
                         "Last message should be 'unmatched' type")
        self.assertEqual(len(at.exception), 0)


class TestRegressionH_NewConversationClearsTracking(unittest.TestCase):
    """Regression H: New conversation clears selection-tracking state."""

    def test_new_conversation_clears_last_handled_selector(self):
        """New conversation deletes last_handled_selector_* keys."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertIn("last_handled_selector_find_plan", at.session_state)

        at.button(key="new_conv").click()
        at.run()

        self.assertNotIn("last_handled_selector_find_plan", at.session_state,
                         "last_handled_selector_find_plan persisted after New conversation")
        self.assertEqual(at.session_state.get("display_messages"), [])
        self.assertIsNone(at.session_state.get("active_result"))
        self.assertIsNone(at.session_state.get("submitted_request"))

    def test_new_conversation_then_re_select_works(self):
        """After New conversation, re-selecting the same fixture works again."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        at.button(key="new_conv").click()
        at.run()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(len(msgs), 2,
                         "Re-selecting after New conversation should produce 2 messages")
        self.assertEqual(len(at.exception), 0)


class TestRegressionI_LiveModeBlockedAllPages(unittest.TestCase):
    """Regression I: Live mode remains blocked on every page."""

    def test_live_blocks_find_plan_fixture_controls(self):
        """Live mode on find_plan blocks the fixture selector."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        at.button(key="nav_find_plan").click()
        at.run()

        self.assertEqual(len(at.selectbox), 0,
                         "Fixture selector visible in Live mode (find_plan)")
        self.assertEqual(len(at.exception), 0)

    def test_live_blocks_compare_fixture_controls(self):
        """Live mode on compare blocks the fixture selector."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        at.button(key="nav_compare").click()
        at.run()

        self.assertEqual(len(at.selectbox), 0,
                         "Fixture selector visible in Live mode (compare)")
        self.assertEqual(len(at.exception), 0)

    def test_live_blocks_impact_fixture_controls(self):
        """Live mode on impact blocks the fixture selector."""
        at = _boot()
        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        at.button(key="nav_impact").click()
        at.run()

        self.assertEqual(len(at.selectbox), 0,
                         "Fixture selector visible in Live mode (impact)")
        self.assertEqual(len(at.exception), 0)


class TestRegressionJ_ReturnFromLiveToFixtures(unittest.TestCase):
    """Regression J: Returning from Live to Fixtures starts cleanly."""

    def test_fixtures_live_fixtures_clean_start(self):
        """Fixtures → Live → Fixtures gives an empty conversation."""
        at = _boot()
        _go_to_find_plan(at)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertGreater(len(at.session_state.get("display_messages", [])), 0)

        at.radio(key="mode_radio").set_value("Live agent")
        at.run()
        at.radio(key="mode_radio").set_value("Fixtures")
        at.run()

        self.assertEqual(at.session_state.get("display_messages"), [],
                         "Messages not cleared after Fixtures→Live→Fixtures")
        self.assertIsNone(at.session_state.get("active_result"))
        self.assertIsNone(at.session_state.get("submitted_request"))
        # last_handled_selector must also be cleared
        self.assertNotIn("last_handled_selector_find_plan", at.session_state,
                         "last_handled_selector not cleared after mode switch cycle")


class TestRegressionK_SeparateSessionsDoNotShareState(unittest.TestCase):
    """Regression K: Separate sessions do not share mutable conversation state."""

    def test_two_independent_sessions(self):
        """Two AppTest instances start with independent empty conversation state."""
        at1 = _boot()
        at2 = _boot()

        _go_to_find_plan(at1)
        at1.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at1.run()

        # at2 must still have an empty conversation
        msgs2 = at2.session_state.get("display_messages", [])
        self.assertEqual(msgs2, [],
                         "Session 2 inherited state from Session 1 (shared mutable default)")

    def test_session1_mutation_not_visible_in_session2(self):
        """Mutations to session 1's display_messages do not affect session 2."""
        at1 = _boot()
        at2 = _boot()

        # Add a message to session 1
        at1.session_state["display_messages"].append({"type": "user", "text": "test"})

        # Session 2 must remain empty
        msgs2 = at2.session_state.get("display_messages", [])
        self.assertEqual(msgs2, [],
                         "Mutating session 1 display_messages affected session 2")




if __name__ == "__main__":
    unittest.main()

# ===========================================================================
# Issue 1 — Retry buttons are real, fixture-id-bound actions
# ===========================================================================
# These tests verify the fix for the retry no-op defect.
# _IDX_A   = conv1_t1_i0  (success, $500)
# _IDX_ERROR = conv_error_t1_i22 (error, same question as $500)
# ===========================================================================

class TestIssue1_RetryButtonProcessesFixture(unittest.TestCase):
    """Issue 1: Clicking a retry button appends the correct fixture exactly once."""

    def test_clicking_retry_appends_fixture_response(self):
        """Clicking the retry button on an error message appends a new entry."""
        at = _boot()
        _go_to_find_plan(at)

        # Load the error fixture
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()

        msgs_before = list(at.session_state.get("display_messages", []))
        self.assertGreater(len(msgs_before), 0)
        # Verify the last message is an error assistant message
        last = msgs_before[-1]
        self.assertEqual(last.get("type"), "assistant")
        self.assertTrue(last.get("is_error"), "Last message should be an error")
        error_fixture_id = last.get("fixture_id")
        self.assertIsNotNone(error_fixture_id)

        # Click the retry button for the error message (idx = 1 for the first pair)
        retry_key = "retry_1"
        retry_btn = at.button(key=retry_key)
        retry_btn.click()
        at.run()

        msgs_after = at.session_state.get("display_messages", [])
        self.assertGreater(
            len(msgs_after), len(msgs_before),
            "Clicking retry did not append a new message — retry is still a no-op",
        )
        # The new last assistant message must have the same fixture_id
        new_last = msgs_after[-1]
        self.assertEqual(new_last.get("type"), "assistant")
        self.assertEqual(
            new_last.get("fixture_id"), error_fixture_id,
            f"Retry appended wrong fixture: expected {error_fixture_id!r}, "
            f"got {new_last.get('fixture_id')!r}",
        )
        self.assertEqual(len(at.exception), 0, f"Exception after retry: {list(at.exception)}")

    def test_retry_adds_exactly_one_pair(self):
        """Clicking retry once adds exactly 2 messages (user + assistant)."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        count_before = len(at.session_state.get("display_messages", []))

        at.button(key="retry_1").click()
        at.run()

        count_after = len(at.session_state.get("display_messages", []))
        self.assertEqual(
            count_after - count_before, 2,
            f"Expected retry to add exactly 2 messages, added {count_after - count_before}",
        )
        self.assertEqual(len(at.exception), 0)

    def test_retry_updates_submitted_request(self):
        """Clicking retry updates submitted_request to the retried fixture_id."""
        at = _boot()
        _go_to_find_plan(at)

        # Load error fixture first
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        error_fixture_id = at.session_state.get("submitted_request", {}).get("fixture_id")

        # Then load a different fixture (success $500 is conv1_t1_i0 — same question
        # but different fixture_id, so it will be a different submitted_request)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_SUCCESS_500)
        at.run()
        self.assertNotEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            error_fixture_id,
        )

        # Retry the first error message (which is at display index 1)
        at.button(key="retry_1").click()
        at.run()

        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            error_fixture_id,
            "submitted_request not updated to retried fixture_id",
        )
        self.assertEqual(len(at.exception), 0)

    def test_retry_after_different_fixture_retries_original_error(self):
        """Historical error retry works even after another fixture is selected."""
        at = _boot()
        _go_to_find_plan(at)

        # Step 1: load error fixture (messages: [user idx0, asst idx1])
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        msgs_step1 = at.session_state.get("display_messages", [])
        error_fixture_id = msgs_step1[-1].get("fixture_id")

        # Step 2: load success fixture (messages: [.., user idx2, asst idx3])
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        msgs_step2 = at.session_state.get("display_messages", [])
        self.assertEqual(len(msgs_step2), 4)

        # Retry the original error (at display index 1)
        at.button(key="retry_1").click()
        at.run()

        msgs_final = at.session_state.get("display_messages", [])
        # Should have 6 messages: error, success, retried-error
        self.assertEqual(len(msgs_final), 6,
                         f"Expected 6 messages after historical retry, got {len(msgs_final)}")

        # The new last message must be the retried error fixture
        self.assertEqual(
            msgs_final[-1].get("fixture_id"), error_fixture_id,
            "Last message is not the retried error fixture",
        )

        # Verify the answer is actually rendered
        rendered = " ".join(m.value for m in at.markdown)
        error_answer = msgs_final[-1]["result"].get("answer", "")
        snippet = error_answer[:40]
        self.assertIn(snippet, rendered,
                      f"Retried error answer not rendered. Snippet: {snippet!r}")
        self.assertEqual(len(at.exception), 0)

    def test_no_additional_messages_on_rerun_after_retry(self):
        """An ordinary rerun after retry does not add more messages."""
        at = _boot()
        _go_to_find_plan(at)

        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR)
        at.run()
        at.button(key="retry_1").click()
        at.run()
        count_after_retry = len(at.session_state.get("display_messages", []))

        # Ordinary reruns must not add messages
        at.run()
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])),
            count_after_retry,
            "Ordinary rerun after retry duplicated messages",
        )
        self.assertEqual(len(at.exception), 0)

    def test_retry_fixture_id_not_identified_by_question_text(self):
        """Retry uses fixture_id, not question text: retrying an error fixture
        always reproduces the error, even if a success fixture shares the question."""
        at = _boot()
        _go_to_find_plan(at)

        # Load the error fixture (index 23), which shares question with success (index 1)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_ERROR_500)
        at.run()
        msgs = at.session_state.get("display_messages", [])
        error_msg = msgs[-1]
        self.assertTrue(error_msg.get("is_error"), "Expected error fixture")
        error_fixture_id = error_msg.get("fixture_id")

        # Click retry — it must reproduce the error, not the success fixture
        at.button(key="retry_1").click()
        at.run()

        msgs_after = at.session_state.get("display_messages", [])
        retried_msg = msgs_after[-1]
        self.assertTrue(
            retried_msg.get("is_error"),
            "Retry produced a success response instead of an error — "
            "fixture was identified by question text, not fixture_id",
        )
        self.assertEqual(
            retried_msg.get("fixture_id"), error_fixture_id,
            f"Retried fixture_id mismatch: expected {error_fixture_id!r}, "
            f"got {retried_msg.get('fixture_id')!r}",
        )
        self.assertEqual(len(at.exception), 0)


# ===========================================================================
# Issue 2 — Explicit fixture reselection is not ignored
# ===========================================================================
# These tests verify the fix for the stale-selector defect.
# ===========================================================================

class TestIssue2_ExplicitReselectionProcessed(unittest.TestCase):
    """Issue 2: Intentional reselection of the same fixture after placeholder
    navigation is correctly processed."""

    def test_500_typed800_placeholder_500_appends_500(self):
        """Select $500, submit $800 via form, choose placeholder, re-select $500.

        Expected: the $500 fixture is appended as the 5th and 6th messages,
        and submitted_request points to the $500 fixture_id.
        """
        at = _boot()
        _go_to_find_plan(at)

        # Step 1: select $500 fixture
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertEqual(len(at.session_state.get("display_messages", [])), 2)
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv1_t1_i0",
        )

        # Step 2: submit the saved $800 question through the text form
        at.text_input(key="free_text_find_plan").input(_Q_800)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        self.assertEqual(len(at.session_state.get("display_messages", [])), 4)
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
            "submitted_request should be $800 after form submission",
        )

        # Step 3: select the placeholder
        at.selectbox(key="fixture_selector_find_plan").select_index(0)
        at.run()
        # Messages and submitted_request must remain unchanged after placeholder
        self.assertEqual(len(at.session_state.get("display_messages", [])), 4,
                         "Placeholder selection changed message count")

        # Step 4: explicitly re-select $500
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(
            len(msgs), 6,
            f"Expected 6 messages after $500→$800→placeholder→$500, got {len(msgs)}. "
            "Explicit reselection was ignored.",
        )
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv1_t1_i0",
            "submitted_request not updated to $500 after explicit reselection",
        )

        # The final assistant message must render the $500 answer
        rendered = " ".join(m.value for m in at.markdown)
        last_asst = next(
            (m for m in reversed(msgs) if m.get("type") == "assistant"), None
        )
        self.assertIsNotNone(last_asst)
        snippet = last_asst["result"].get("answer", "")[:60]
        self.assertIn(snippet, rendered,
                      f"$500 answer not rendered after reselection. Snippet: {snippet!r}")

        # No duplicates on a plain rerun
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])), 6,
            "Plain rerun after reselection duplicated messages",
        )
        self.assertEqual(len(at.exception), 0)

    def test_cross_page_reselection_appends_response(self):
        """Select $500 on Find a plan, go to Compare and select $800,
        return to Find a plan and explicitly re-select $500.

        Expected: $500 response is appended, conversation has 6 messages,
        submitted_request = conv1_t1_i0.
        """
        at = _boot()
        _go_to_find_plan(at)

        # Step 1: select $500 on find_plan
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        self.assertEqual(len(at.session_state.get("display_messages", [])), 2)

        # Step 2: navigate to compare and select $800
        at.button(key="nav_compare").click()
        at.run()
        at.selectbox(key="fixture_selector_compare").select_index(_IDX_B)
        at.run()
        self.assertEqual(len(at.session_state.get("display_messages", [])), 4)
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
        )

        # Step 3: return to find_plan — the selector defaults back to placeholder (index=0)
        at.button(key="nav_find_plan").click()
        at.run()
        # Messages preserved
        self.assertEqual(len(at.session_state.get("display_messages", [])), 4,
                         "Navigation cleared display_messages")

        # Step 4: explicitly re-select $500 on find_plan
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        msgs = at.session_state.get("display_messages", [])
        self.assertEqual(
            len(msgs), 6,
            f"Expected 6 messages after cross-page $500→$800→$500 sequence, "
            f"got {len(msgs)}. Cross-page reselection was ignored.",
        )
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv1_t1_i0",
            "submitted_request not updated to $500 after cross-page reselection",
        )

        # Verify $500 answer rendered and no duplicates
        rendered = " ".join(m.value for m in at.markdown)
        last_asst = next(
            (m for m in reversed(msgs) if m.get("type") == "assistant"), None
        )
        self.assertIsNotNone(last_asst)
        snippet = last_asst["result"].get("answer", "")[:60]
        self.assertIn(snippet, rendered,
                      f"$500 answer not rendered after cross-page reselection. "
                      f"Snippet: {snippet!r}")

        # No duplicates on plain rerun
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])), 6,
            "Plain rerun after cross-page reselection duplicated messages",
        )
        self.assertEqual(len(at.exception), 0)

    def test_ordinary_rerun_still_cannot_replay_stale_selection(self):
        """Regression B behaviour preserved: an ordinary rerun after form
        submission does not replay the stale selector value."""
        at = _boot()
        _go_to_find_plan(at)

        # Select $500 fixture (selector index 1)
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        # Type the $800 question through the form
        at.text_input(key="free_text_find_plan").input(_Q_800)
        at.form_submit_button(
            key="FormSubmitter:free_text_form_find_plan-Submit"
        ).click()
        at.run()
        self.assertEqual(len(at.session_state.get("display_messages", [])), 4)

        # Ordinary reruns — the widget still shows $500 but must NOT replay
        at.run()
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])), 4,
            "Ordinary rerun replayed stale $500 selector (Regression B still broken)",
        )
        self.assertEqual(
            at.session_state.get("submitted_request", {}).get("fixture_id"),
            "conv2_t1_i1",
            "submitted_request reverted to $500 on ordinary rerun",
        )
        self.assertEqual(len(at.exception), 0)

    def test_no_duplicates_after_explicit_reselection_reruns(self):
        """After explicit reselection + rerun, no additional messages appear."""
        at = _boot()
        _go_to_find_plan(at)

        # Select, go to placeholder, re-select
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(0)
        at.run()
        at.selectbox(key="fixture_selector_find_plan").select_index(_IDX_A)
        at.run()

        count = len(at.session_state.get("display_messages", []))
        self.assertEqual(count, 4,
                         f"Expected 4 messages ($500 × 2), got {count}")

        # Subsequent reruns must not change count
        at.run()
        at.run()
        self.assertEqual(
            len(at.session_state.get("display_messages", [])), count,
            "Reruns after explicit reselection duplicated messages",
        )
        self.assertEqual(len(at.exception), 0)
