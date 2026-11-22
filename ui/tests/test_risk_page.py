"""
ui/tests/test_risk_page.py — Tests for the Risk under uncertainty page.

Covers:
- Opening the page shows every option code and every expected_late_orders
  value (two decimals) from get_overview() without selecting anything.
- Same holds in Live mode, where there is also no selectbox and the
  "not available" warning is present.
- When get_overview is patched to raise, an error element is shown and
  there is no uncaught exception.
- world_risk_chart_rows keeps row order and drops None values.
- Labels: no label starts with "Conv ", the error entry's label contains
  "connection error example", all labels in the list are distinct.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from agent.overview import get_overview
from ui.fixtures import get_fixture_options, label_for, load_fixtures
from ui.renderers import world_risk_chart_rows

_APP_PATH = str(Path(__file__).parent.parent.parent / "app.py")
_TIMEOUT = 30


# ===========================================================================
# Helpers
# ===========================================================================

def _boot() -> AppTest:
    at = AppTest.from_file(_APP_PATH, default_timeout=_TIMEOUT)
    at.run()
    return at


def _navigate_to_impact(at: AppTest) -> AppTest:
    at.button(key="nav_impact").click()
    at.run()
    return at


def _get_all_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown]
    parts += [c.value for c in at.caption]
    parts += [i.value for i in at.info]
    return " ".join(parts)


# ===========================================================================
# Part 1b: Overview auto-renders on impact page (Fixtures mode)
# ===========================================================================

class TestRiskPageOverviewFixturesMode(unittest.TestCase):
    """Opening the risk page in Fixtures mode shows the overview without selecting."""

    @classmethod
    def setUpClass(cls):
        cls.overview_result = get_overview()
        cls.overview_view = cls.overview_result.get("view") or cls.overview_result
        cls.at = _boot()
        _navigate_to_impact(cls.at)

    def test_no_exception(self):
        self.assertEqual(
            len(self.at.exception), 0,
            f"App raised exception: {list(self.at.exception)}",
        )

    def test_every_option_code_visible(self):
        """Every row code from get_overview() appears on the page."""
        all_text = _get_all_text(self.at)
        for row in self.overview_view.get("rows", []):
            code = row["code"]
            self.assertIn(
                code, all_text,
                f"Option code {code!r} not found on the risk page",
            )

    def test_every_expected_late_orders_visible(self):
        """Every expected_late_orders value (two decimals) from get_overview() appears."""
        all_text = _get_all_text(self.at)
        for row in self.overview_view.get("rows", []):
            exp_late = row.get("expected_late_orders")
            if exp_late is not None:
                expected_str = f"{exp_late:.2f}"
                self.assertIn(
                    expected_str, all_text,
                    f"expected_late_orders {expected_str!r} for {row['code']!r} "
                    f"not found on the risk page",
                )

    def test_selectbox_present_in_fixtures_mode(self):
        """In Fixtures mode the example selector is shown."""
        self.assertGreater(
            len(self.at.selectbox), 0,
            "No selectbox found on the risk page in Fixtures mode",
        )

    def test_no_unavailable_warning_in_fixtures_mode(self):
        """The 'not available' warning is absent in Fixtures mode."""
        warnings = [w.value for w in self.at.warning]
        self.assertFalse(
            any("not available" in w.lower() for w in warnings),
            f"Unexpected 'not available' warning in Fixtures mode: {warnings}",
        )


# ===========================================================================
# Part 1b: Overview auto-renders on impact page (Live mode)
# ===========================================================================

class TestRiskPageOverviewLiveMode(unittest.TestCase):
    """Opening the risk page in Live mode also shows the overview."""

    @classmethod
    def setUpClass(cls):
        cls.overview_result = get_overview()
        cls.overview_view = cls.overview_result.get("view") or cls.overview_result
        cls.at = _boot()
        cls.at.radio(key="mode_radio").set_value("Live agent")
        cls.at.run()
        _navigate_to_impact(cls.at)

    def test_no_exception(self):
        self.assertEqual(
            len(self.at.exception), 0,
            f"App raised exception: {list(self.at.exception)}",
        )

    def test_every_option_code_visible(self):
        """Every row code from get_overview() appears on the page in Live mode."""
        all_text = _get_all_text(self.at)
        for row in self.overview_view.get("rows", []):
            code = row["code"]
            self.assertIn(
                code, all_text,
                f"Option code {code!r} not found on the risk page (Live mode)",
            )

    def test_every_expected_late_orders_visible(self):
        """Every expected_late_orders value (two decimals) appears in Live mode."""
        all_text = _get_all_text(self.at)
        for row in self.overview_view.get("rows", []):
            exp_late = row.get("expected_late_orders")
            if exp_late is not None:
                expected_str = f"{exp_late:.2f}"
                self.assertIn(
                    expected_str, all_text,
                    f"expected_late_orders {expected_str!r} for {row['code']!r} "
                    f"not found on the risk page (Live mode)",
                )

    def test_no_selectbox_in_live_mode(self):
        """In Live mode there is no example selectbox on the risk page."""
        self.assertEqual(
            len(self.at.selectbox), 0,
            "Selectbox found on the risk page in Live mode (should be absent)",
        )

    def test_no_unavailable_warning_in_live_mode(self):
        """The impact page no longer shows 'not available' in Live mode.
        It now shows either the API key guidance or the risk question form.
        """
        warnings = [w.value for w in self.at.warning]
        self.assertFalse(
            any("not available" in w.lower() for w in warnings),
            f"Unexpected 'not available' warning in Live mode: {warnings}",
        )


# ===========================================================================
# Part 1b: get_overview raises → error shown, no uncaught exception
# ===========================================================================

class TestRiskPageGetOverviewRaises(unittest.TestCase):
    """When get_overview is patched to raise, an error element is shown and
    no uncaught exception propagates.

    Uses an AppTest instance with the impact page pre-navigated to verify that:
    1. The app shows an st.error element when get_overview raises.
    2. No uncaught exception is recorded.

    The test boots a fresh AppTest for each case so there is no state leakage
    between AppTest runs or between AppTest and bare Streamlit calls.
    """

    def _boot_impact_with_raising_overview(self, error_msg: str) -> AppTest:
        """Return an AppTest on the impact page where get_overview raises.

        Implementation: We use the fact that render_world_risk is called on a
        view returned by get_overview. We verify the full page-level error
        handling by injecting a fake result into session_state that causes the
        overview rendering to fail, then observing st.error.

        Since AppTest cannot easily inject a raising callable, we instead
        verify the behaviour indirectly: the page should not crash (no
        exception in at.exception) and should emit an error element.

        We use a custom AppTest path pointing at a minimal helper script that
        calls _page_impact with a raising _get_overview_fn.
        """
        # Use AppTest with the standard app.py but verify via the injectable
        # pattern that the error is caught. We write a temporary app wrapper.
        import tempfile, os

        wrapper_code = f"""
import streamlit as st
# Minimal wrapper to test _page_impact with a raising get_overview
import sys, os
sys.path.insert(0, {repr(str(Path(_APP_PATH).parent))})
# Bootstrap Streamlit page config to avoid errors
try:
    st.set_page_config(page_title="test", page_icon="T")
except Exception:
    pass
from ui.state import init_state
from ui.renderers import inject_css
init_state()
inject_css()

import app as app_mod
def _failing_overview():
    raise RuntimeError({repr(error_msg)})

app_mod._page_impact(_get_overview_fn=_failing_overview)
"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        tmp.write(wrapper_code)
        tmp.close()

        try:
            at = AppTest.from_file(tmp.name, default_timeout=_TIMEOUT)
            at.run()
        finally:
            os.unlink(tmp.name)
        return at

    def test_error_shown_when_get_overview_raises(self):
        """An error element is shown when get_overview raises."""
        err_msg = "test overview failure unique XYZ"
        at = self._boot_impact_with_raising_overview(err_msg)

        # No uncaught exception
        self.assertEqual(
            len(at.exception), 0,
            f"App raised uncaught exception: {list(at.exception)}",
        )

        # An error element must be present with the exception text
        errors = [e.value for e in at.error]
        self.assertTrue(
            any(err_msg in e for e in errors),
            f"Expected error message {err_msg!r} not found; errors: {errors}",
        )

    def test_no_uncaught_exception_when_get_overview_raises(self):
        """No uncaught exception is emitted when get_overview raises."""
        at = self._boot_impact_with_raising_overview("deliberately raised")

        self.assertEqual(
            len(at.exception), 0,
            f"Uncaught exception found: {list(at.exception)}",
        )


# ===========================================================================
# Part 3b: world_risk_chart_rows
# ===========================================================================

class TestWorldRiskChartRows(unittest.TestCase):
    """world_risk_chart_rows preserves row order and drops None values."""

    _VIEW = {
        "rows": [
            {"code": "WAIT", "expected_late_orders": 7.42, "extra_cost": 0},
            {"code": "TRANSFER", "expected_late_orders": 5.55, "extra_cost": 416},
            {"code": "ALT_BUY", "expected_late_orders": None, "extra_cost": None},
            {"code": "HYBRID", "expected_late_orders": 3.34, "extra_cost": 1250},
        ]
    }

    def test_row_order_preserved_for_late(self):
        """Rows with values come back in view["rows"] order."""
        result = world_risk_chart_rows(self._VIEW, "expected_late_orders")
        codes = [code for code, _ in result]
        self.assertEqual(codes, ["WAIT", "TRANSFER", "HYBRID"],
                         f"Row order not preserved: {codes}")

    def test_none_values_dropped_for_late(self):
        """Rows with None expected_late_orders are excluded."""
        result = world_risk_chart_rows(self._VIEW, "expected_late_orders")
        codes = [code for code, _ in result]
        self.assertNotIn("ALT_BUY", codes)

    def test_row_order_preserved_for_cost(self):
        """Rows with values come back in view["rows"] order for extra_cost."""
        result = world_risk_chart_rows(self._VIEW, "extra_cost")
        codes = [code for code, _ in result]
        self.assertEqual(codes, ["WAIT", "TRANSFER", "HYBRID"],
                         f"Row order not preserved for cost: {codes}")

    def test_none_values_dropped_for_cost(self):
        """Rows with None extra_cost are excluded."""
        result = world_risk_chart_rows(self._VIEW, "extra_cost")
        codes = [code for code, _ in result]
        self.assertNotIn("ALT_BUY", codes)

    def test_values_match_source(self):
        """Values match the source data."""
        result = world_risk_chart_rows(self._VIEW, "expected_late_orders")
        self.assertEqual(result[0], ("WAIT", 7.42))
        self.assertEqual(result[1], ("TRANSFER", 5.55))
        self.assertEqual(result[2], ("HYBRID", 3.34))

    def test_empty_rows(self):
        """Empty rows list returns empty list."""
        result = world_risk_chart_rows({"rows": []}, "expected_late_orders")
        self.assertEqual(result, [])

    def test_all_none_returns_empty(self):
        """If all values are None, returns empty list."""
        view = {"rows": [{"code": "X", "expected_late_orders": None}]}
        result = world_risk_chart_rows(view, "expected_late_orders")
        self.assertEqual(result, [])

    def test_uses_get_overview_data(self):
        """world_risk_chart_rows works correctly on actual get_overview() data."""
        overview = get_overview()
        view = overview.get("view") or overview
        result = world_risk_chart_rows(view, "expected_late_orders")
        # At least one row should be returned
        self.assertGreater(len(result), 0)
        # All returned values must be non-None
        for code, val in result:
            self.assertIsNotNone(val, f"None value slipped through for {code!r}")


# ===========================================================================
# Part 2a: Label format
# ===========================================================================

class TestLabelFormat(unittest.TestCase):
    """Labels must not start with 'Conv ', error entry contains 'connection error example',
    and all labels in the list are distinct."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_fixtures()
        cls.options = get_fixture_options(cls.fixtures)

    def test_no_label_starts_with_conv(self):
        """No label in the selector should start with 'Conv '."""
        for fid, lbl in self.options:
            self.assertFalse(
                lbl.startswith("Conv "),
                f"Label starts with 'Conv ': {lbl!r}",
            )

    def test_error_label_contains_connection_error_example(self):
        """The error fixture's label contains 'connection error example'."""
        error_entries = [
            (i, e) for i, e in enumerate(self.fixtures) if "error" in e["result"]
        ]
        self.assertGreater(len(error_entries), 0, "No error fixture found")
        for i, entry in error_entries:
            lbl = label_for(entry, i)
            self.assertIn(
                "connection error example", lbl,
                f"Error label does not contain 'connection error example': {lbl!r}",
            )

    def test_all_labels_in_list_are_distinct(self):
        """All labels returned by get_fixture_options() are distinct."""
        labels = [lbl for _, lbl in self.options]
        self.assertEqual(
            len(labels), len(set(labels)),
            f"Duplicate labels found in fixture options: "
            f"{[l for l in labels if labels.count(l) > 1]}",
        )


if __name__ == "__main__":
    unittest.main()
