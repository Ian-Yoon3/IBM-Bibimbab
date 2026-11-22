"""
ui/tests/test_fixtures.py — Unit tests for ui/fixtures.py

Covers:
- Fixture file loads and contains the expected number of entries.
- Every entry receives a unique fixture_id.
- Successful and error entries with identical question text have different IDs.
- get_result_copy returns a deep copy (mutations do not affect the catalog).
- Unrecognised fixture_id returns None.
- is_error_fixture correctly identifies error entries.
- Label format distinguishes error entries and multi-turn entries.
- No default-to-first fallback: unmatched text does not silently return a result.
"""
import copy
import unittest

from ui.fixtures import (
    UNMATCHED_MESSAGE,
    build_fixture_catalog,
    get_fixture_options,
    get_result_copy,
    is_error_fixture,
    label_for,
    load_fixtures,
    make_fixture_id,
)


class TestLoadFixtures(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()

    def test_loads_nonzero_entries(self):
        self.assertGreater(len(self.fixtures), 0)

    def test_fixture_list_coverage(self):
        # The fixture file is not empty, has exactly one error entry, and covers
        # every expected view type at least once.
        self.assertGreater(len(self.fixtures), 0, "Fixture list must not be empty")

        error_entries = [e for e in self.fixtures if is_error_fixture(e["result"])]
        self.assertEqual(
            len(error_entries), 1,
            f"Expected exactly 1 error entry, found {len(error_entries)}",
        )

        expected_view_types = {
            "recommendation", "comparison", "option", "order",
            "proposal", "unsupported", "world_risk",
        }
        present_view_types = set()
        for e in self.fixtures:
            view = e["result"].get("view")
            if view and view.get("type"):
                present_view_types.add(view["type"])
        missing = expected_view_types - present_view_types
        self.assertFalse(
            missing,
            f"These view types are missing from fixtures: {missing}",
        )

    def test_all_entries_have_required_keys(self):
        for entry in self.fixtures:
            for key in ("conversation", "turn", "question", "result"):
                self.assertIn(key, entry, f"Missing '{key}' in entry {entry}")

    def test_all_results_have_answer(self):
        for entry in self.fixtures:
            self.assertIn("answer", entry["result"])


class TestFixtureIds(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()
        self.catalog = build_fixture_catalog(self.fixtures)

    def test_all_ids_unique(self):
        ids = [make_fixture_id(e, i) for i, e in enumerate(self.fixtures)]
        self.assertEqual(len(ids), len(set(ids)), "fixture_ids are not unique")

    def test_catalog_length_matches_fixture_count(self):
        self.assertEqual(len(self.catalog), len(self.fixtures))

    def test_error_and_success_same_question_different_ids(self):
        """The error fixture and the success fixture for the same question must
        have different fixture_ids."""
        error_entries = [
            (i, e) for i, e in enumerate(self.fixtures) if "error" in e["result"]
        ]
        self.assertGreater(len(error_entries), 0, "No error fixture found")

        for err_i, err_entry in error_entries:
            q = err_entry["question"]
            # Find success entries with the same question
            success_matches = [
                (j, e)
                for j, e in enumerate(self.fixtures)
                if e["question"] == q and "error" not in e["result"]
            ]
            self.assertGreater(
                len(success_matches), 0,
                f"No success fixture with question: {q!r}"
            )
            err_id = make_fixture_id(err_entry, err_i)
            for ok_j, ok_entry in success_matches:
                ok_id = make_fixture_id(ok_entry, ok_j)
                self.assertNotEqual(
                    err_id, ok_id,
                    f"Error and success share fixture_id: {err_id}"
                )


class TestGetResultCopy(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()
        self.catalog = build_fixture_catalog(self.fixtures)
        self.options = get_fixture_options(self.fixtures)

    def test_known_id_returns_dict(self):
        fid, _ = self.options[0]
        result = get_result_copy(self.catalog, fid)
        self.assertIsInstance(result, dict)

    def test_unknown_id_returns_none(self):
        result = get_result_copy(self.catalog, "conv999_t9_i999")
        self.assertIsNone(result)

    def test_returns_deep_copy(self):
        fid, _ = self.options[0]
        r1 = get_result_copy(self.catalog, fid)
        r1["_mutated"] = True
        r2 = get_result_copy(self.catalog, fid)
        self.assertNotIn("_mutated", r2, "get_result_copy did not return a deep copy")

    def test_no_default_to_first_for_unmatched(self):
        """An unknown fixture_id must return None, not silently fall back to
        the first fixture."""
        result = get_result_copy(self.catalog, "DOES_NOT_EXIST")
        self.assertIsNone(result)


class TestIsErrorFixture(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()

    def test_error_fixture_detected(self):
        error_entries = [e for e in self.fixtures if "error" in e["result"]]
        self.assertGreater(len(error_entries), 0)
        for entry in error_entries:
            self.assertTrue(is_error_fixture(entry["result"]))

    def test_success_fixture_not_error(self):
        success_entries = [e for e in self.fixtures if "error" not in e["result"]]
        self.assertGreater(len(success_entries), 0)
        for entry in success_entries:
            self.assertFalse(is_error_fixture(entry["result"]))


class TestLabelFor(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()

    def test_error_label_contains_error_marker(self):
        for i, entry in enumerate(self.fixtures):
            if "error" in entry["result"]:
                lbl = label_for(entry, i)
                self.assertIn("error", lbl.lower())

    def test_multi_turn_label_contains_turn(self):
        for i, entry in enumerate(self.fixtures):
            if entry["turn"] > 1:
                lbl = label_for(entry, i)
                self.assertIn("turn", lbl.lower())

    def test_all_labels_are_strings(self):
        for i, entry in enumerate(self.fixtures):
            lbl = label_for(entry, i)
            self.assertIsInstance(lbl, str)
            self.assertGreater(len(lbl), 0)


class TestGetFixtureOptions(unittest.TestCase):
    def setUp(self):
        self.fixtures = load_fixtures()
        self.options = get_fixture_options(self.fixtures)

    def test_options_count_matches_fixtures(self):
        self.assertEqual(len(self.options), len(self.fixtures))

    def test_options_are_tuples_of_two_strings(self):
        for fid, label in self.options:
            self.assertIsInstance(fid, str)
            self.assertIsInstance(label, str)

    def test_all_option_ids_unique(self):
        ids = [fid for fid, _ in self.options]
        self.assertEqual(len(ids), len(set(ids)))


class TestUnmatchedMessage(unittest.TestCase):
    def test_unmatched_message_is_string(self):
        self.assertIsInstance(UNMATCHED_MESSAGE, str)
        self.assertGreater(len(UNMATCHED_MESSAGE), 0)


if __name__ == "__main__":
    unittest.main()
