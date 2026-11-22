"""The "Add a file here" button on the overview page and its dialog.

The dialog shows where a data set is added and which data is in use.  The
upload is not connected, so the tests check that nothing in it can be
submitted and that the reason is visible.  agent.overview.get_data_overview is
replaced by a fake where the content matters; no test calls watsonx.ai.
"""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from agent.overview import get_data_overview

_APP_PATH = str(Path(__file__).parent.parent.parent / "app.py")


def _open_dialog(mode: str = "Fixtures") -> AppTest:
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    if mode != "Fixtures":
        at.radio(key="mode_radio").set_value(mode)
        at.run()
    at.button(key="cta_add_file").click()
    at.run()
    return at


def _text(at: AppTest) -> str:
    parts = []
    for group in (at.markdown, at.caption, at.info, at.warning, at.success, at.error):
        parts += [str(e.value) for e in group]
    return " ".join(parts)


def _fake(**changes):
    info = copy.deepcopy(get_data_overview())
    for key, value in changes.items():
        info[key] = value
    return lambda *a, **k: copy.deepcopy(info)


class Button(unittest.TestCase):
    def test_button_is_on_the_overview_page_in_both_modes(self):
        for mode in ("Fixtures", "Live agent"):
            with self.subTest(mode=mode):
                at = AppTest.from_file(_APP_PATH, default_timeout=30)
                at.run()
                at.radio(key="mode_radio").set_value(mode)
                at.run()
                self.assertEqual(at.session_state["current_page"], "overview")
                self.assertEqual(at.button(key="cta_add_file").label, "Add a file here")

    def test_dialog_is_closed_until_the_button_is_pressed(self):
        at = AppTest.from_file(_APP_PATH, default_timeout=30)
        at.run()
        self.assertEqual([b for b in at.button if b.key == "add_file_confirm"], [])


class Dialog(unittest.TestCase):
    def test_shows_every_file_of_the_data_overview(self):
        info = get_data_overview()
        for mode in ("Fixtures", "Live agent"):
            with self.subTest(mode=mode):
                at = _open_dialog(mode)
                self.assertEqual(len(at.exception), 0)
                text = _text(at)
                self.assertTrue(info["files"])
                for f in info["files"]:
                    self.assertIn(f["name"], text)
                self.assertIn(info["data_dir"], text)

    def test_upload_cannot_be_submitted_and_says_why(self):
        info = get_data_overview()
        self.assertIs(info["upload"]["enabled"], False)
        at = _open_dialog()
        self.assertTrue(at.button(key="add_file_confirm").disabled)
        uploaders = at.get("file_uploader")
        self.assertEqual(len(uploaders), 1)
        self.assertTrue(uploaders[0].proto.disabled)
        self.assertIn(info["upload"]["note"], [w.value for w in at.warning])

    def test_cancel_closes_the_dialog(self):
        at = _open_dialog()
        at.button(key="add_file_cancel").click()
        at.run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([b for b in at.button if b.key == "add_file_confirm"], [])
        self.assertEqual(at.session_state["current_page"], "overview")

    def test_stale_run_is_a_warning_with_the_details(self):
        run = {"status": "stale", "name": "runs/x", "message": "STALE-MESSAGE-31",
               "detail": "DETAIL-LINE-77", "settings": None, "grid": None,
               "created_at": None}
        with patch("agent.overview.get_data_overview", _fake(run=run)):
            at = _open_dialog()
            self.assertEqual(len(at.exception), 0)
            self.assertIn("STALE-MESSAGE-31", [w.value for w in at.warning])
            self.assertEqual([s.value for s in at.success], [])
            self.assertIn("DETAIL-LINE-77", " ".join(c.value for c in at.code))

    def test_no_run_is_an_info_line(self):
        run = {"status": "none", "name": None, "message": "NO-RUN-MESSAGE-12",
               "detail": "", "settings": None, "grid": None, "created_at": None}
        with patch("agent.overview.get_data_overview", _fake(run=run)):
            at = _open_dialog()
            self.assertIn("NO-RUN-MESSAGE-12", [i.value for i in at.info])
            self.assertEqual([s.value for s in at.success], [])

    def test_matching_run_shows_its_settings(self):
        run = {"status": "match", "name": "runs/x", "message": "MATCH-MESSAGE-08",
               "detail": "", "settings": {"M": 7, "N": 3, "seed": 99, "method": "lhs"},
               "grid": "absent", "created_at": "CREATED-STAMP"}
        with patch("agent.overview.get_data_overview", _fake(run=run)):
            at = _open_dialog()
            self.assertIn("MATCH-MESSAGE-08", [s.value for s in at.success])
            text = _text(at)
            for piece in ("M: 7", "N: 3", "seed: 99", "threshold grid: absent",
                          "CREATED-STAMP"):
                self.assertIn(piece, text)

    def test_synthetic_note_follows_the_flag(self):
        for flag in (True, False):
            with self.subTest(flag=flag):
                with patch("agent.overview.get_data_overview",
                           _fake(synthetic_history=flag)):
                    at = _open_dialog()
                    shown = any("synthetic" in i.value for i in at.info)
                    self.assertEqual(shown, flag)

    def test_failure_of_the_overview_is_shown(self):
        def boom(*a, **k):
            raise ValueError("OVERVIEW-FAILED-64")
        with patch("agent.overview.get_data_overview", boom):
            at = _open_dialog()
            self.assertEqual(len(at.exception), 0)
            self.assertIn("OVERVIEW-FAILED-64", [e.value for e in at.error])
            self.assertEqual([b for b in at.button if b.key == "add_file_confirm"], [])


if __name__ == "__main__":
    unittest.main()
