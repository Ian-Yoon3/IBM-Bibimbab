"""
ui/tests/test_state.py — Unit tests for ui/state.py

Covers (without Streamlit runtime — uses a minimal st stub):
- init_state populates expected keys with correct defaults.
- reset_conversation clears conversation keys but not mode/page.
- switch_mode changes mode and clears conversation.
- navigate_to changes page without resetting conversation.
- Switching modes does not carry over history or active_proposal.

Isolation note
--------------
The fake Streamlit module is installed into sys.modules only for the
duration of this module's import of ui.state.  It is restored afterwards
so that AppTest-based tests (which need the *real* Streamlit) are not
contaminated.
"""
import sys
import types
import unittest


# ---------------------------------------------------------------------------
# Minimal Streamlit stub — avoids importing the real Streamlit
# at test time (which requires a running server).
# ---------------------------------------------------------------------------

class _FakeSessionState(dict):
    """dict subclass that also supports attribute access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        del self[name]


def _build_st_stub():
    mod = types.ModuleType("streamlit")
    mod.session_state = _FakeSessionState()
    return mod


# ---------------------------------------------------------------------------
# Scoped injection: install the stub, import ui.state, then restore BOTH
# sys.modules["streamlit"] AND sys.modules["ui.state"] so that AppTest-based
# tests get a fresh ui.state that uses real Streamlit.
# ---------------------------------------------------------------------------
_st_stub = _build_st_stub()
_real_streamlit = sys.modules.get("streamlit")        # may be None or real module
_real_ui_state  = sys.modules.get("ui.state")         # None on first import

sys.modules["streamlit"] = _st_stub

# Import ui.state while the stub is in place.
import ui.state as _ui_state_module  # noqa: E402

# --- Restore real Streamlit -------------------------------------------------
if _real_streamlit is None:
    sys.modules.pop("streamlit", None)
else:
    sys.modules["streamlit"] = _real_streamlit

# --- Restore ui.state -------------------------------------------------------
# Remove the stub-linked cached module so that the next importer (AppTest's
# script runner) gets a fresh module object bound to real Streamlit.
if _real_ui_state is None:
    sys.modules.pop("ui.state", None)
else:
    sys.modules["ui.state"] = _real_ui_state

# Bring the public helpers into this test module's namespace.
# They still work because _ui_state_module keeps a reference to _st_stub.
init_state = _ui_state_module.init_state
navigate_to = _ui_state_module.navigate_to
reset_conversation = _ui_state_module.reset_conversation
switch_mode = _ui_state_module.switch_mode


class TestInitState(unittest.TestCase):
    def setUp(self):
        _st_stub.session_state = _FakeSessionState()

    def test_all_expected_keys_created(self):
        init_state()
        expected = [
            "mode", "current_page", "display_messages", "agent_history",
            "active_result", "active_proposal", "submitted_request",
            "request_pending", "last_failed_request",
        ]
        for key in expected:
            self.assertIn(key, _st_stub.session_state, f"Missing key: {key}")

    def test_default_mode_is_fixtures(self):
        init_state()
        self.assertEqual(_st_stub.session_state.mode, "fixtures")

    def test_default_page_is_overview(self):
        init_state()
        self.assertEqual(_st_stub.session_state.current_page, "overview")

    def test_does_not_overwrite_existing_values(self):
        _st_stub.session_state["mode"] = "live"
        init_state()
        self.assertEqual(_st_stub.session_state.mode, "live")


class TestResetConversation(unittest.TestCase):
    def setUp(self):
        _st_stub.session_state = _FakeSessionState()
        init_state()
        # Simulate some active state
        _st_stub.session_state.display_messages = [{"role": "user"}]
        _st_stub.session_state.agent_history = [{"role": "assistant"}]
        _st_stub.session_state.active_result = {"answer": "test"}
        _st_stub.session_state.active_proposal = {"proposal_id": "P01"}
        _st_stub.session_state.submitted_request = {"budget": 500}
        _st_stub.session_state.request_pending = True
        _st_stub.session_state.last_failed_request = {"budget": 500}

    def test_conversation_keys_cleared(self):
        reset_conversation()
        self.assertEqual(_st_stub.session_state.display_messages, [])
        self.assertIsNone(_st_stub.session_state.agent_history)
        self.assertIsNone(_st_stub.session_state.active_result)
        self.assertIsNone(_st_stub.session_state.active_proposal)
        self.assertIsNone(_st_stub.session_state.submitted_request)
        self.assertFalse(_st_stub.session_state.request_pending)
        self.assertIsNone(_st_stub.session_state.last_failed_request)

    def test_mode_preserved(self):
        _st_stub.session_state.mode = "live"
        reset_conversation()
        self.assertEqual(_st_stub.session_state.mode, "live")

    def test_page_preserved(self):
        _st_stub.session_state.current_page = "find_plan"
        reset_conversation()
        self.assertEqual(_st_stub.session_state.current_page, "find_plan")


class TestSwitchMode(unittest.TestCase):
    def setUp(self):
        _st_stub.session_state = _FakeSessionState()
        init_state()
        _st_stub.session_state.agent_history = [{"role": "assistant"}]
        _st_stub.session_state.active_proposal = {"proposal_id": "P01"}
        _st_stub.session_state.display_messages = [{"question": "test"}]

    def test_mode_changes(self):
        _st_stub.session_state.mode = "fixtures"
        switch_mode("live")
        self.assertEqual(_st_stub.session_state.mode, "live")

    def test_history_cleared_on_mode_switch(self):
        switch_mode("live")
        self.assertIsNone(_st_stub.session_state.agent_history)

    def test_active_proposal_cleared_on_mode_switch(self):
        switch_mode("live")
        self.assertIsNone(_st_stub.session_state.active_proposal)

    def test_display_messages_cleared_on_mode_switch(self):
        switch_mode("live")
        self.assertEqual(_st_stub.session_state.display_messages, [])

    def test_no_change_if_same_mode(self):
        _st_stub.session_state.mode = "fixtures"
        _st_stub.session_state.agent_history = ["old history"]
        switch_mode("fixtures")
        # History must not be cleared when mode does not change
        self.assertEqual(_st_stub.session_state.agent_history, ["old history"])


class TestNavigateTo(unittest.TestCase):
    def setUp(self):
        _st_stub.session_state = _FakeSessionState()
        init_state()
        _st_stub.session_state.display_messages = [{"role": "user"}]

    def test_page_changes(self):
        navigate_to("find_plan")
        self.assertEqual(_st_stub.session_state.current_page, "find_plan")

    def test_conversation_not_cleared(self):
        navigate_to("compare")
        self.assertEqual(_st_stub.session_state.display_messages, [{"role": "user"}])


if __name__ == "__main__":
    unittest.main()
