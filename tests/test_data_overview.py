"""get_data_overview(): the data files in use and the state of the selected run.

Expected values are built from the folder under test, so the tests hold for
other data sets in the same format.
"""
import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine.loader as loader
import engine.runs as runs
from agent.overview import get_data_overview

DATA = Path(loader._DEFAULT_DATA_DIR)
# The tests package switches the run selection off (tests/__init__.py).  The
# run tests switch it back on for the repository's own selection file.
SELECTION = runs.REPO_ROOT / "run_selection.json"


def _rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return max(len([r for r in csv.reader(fh) if r]) - 1, 0)


class Files(unittest.TestCase):
    def setUp(self):
        self.info = get_data_overview()

    def test_every_csv_file_is_listed_once_with_its_row_count(self):
        expected = {p.relative_to(DATA).as_posix(): _rows(p) for p in DATA.rglob("*.csv")}
        self.assertTrue(expected)
        got = {f["name"]: f["rows"] for f in self.info["files"]}
        self.assertEqual(got, expected)
        self.assertEqual(len(self.info["files"]), len(expected))

    def test_groups(self):
        for f in self.info["files"]:
            want = "history" if f["name"].startswith("history/") else "inputs"
            self.assertEqual(f["group"], want, f["name"])

    def test_upload_is_not_offered(self):
        self.assertIs(self.info["upload"]["enabled"], False)
        self.assertIn("Monte Carlo run", self.info["upload"]["note"])

    def test_synthetic_flag_follows_the_history_readme(self):
        readme = DATA / "history" / "README.md"
        want = readme.exists() and "synthetic" in readme.read_text(encoding="utf-8").lower()
        self.assertEqual(self.info["synthetic_history"], want)

    def test_header_only_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.csv").write_text("x,y\n", encoding="utf-8")
            (d / "b.csv").write_text("x,y\n1,2\n\n3,4\n", encoding="utf-8")
            (d / "history").mkdir()
            (d / "history" / "c.csv").write_text("", encoding="utf-8")
            with patch.object(runs, "SELECTION_PATH", None):
                info = get_data_overview(d)
        self.assertEqual({f["name"]: (f["group"], f["rows"]) for f in info["files"]},
                         {"a.csv": ("inputs", 0), "b.csv": ("inputs", 2),
                          "history/c.csv": ("history", 0)})


class RunState(unittest.TestCase):
    def setUp(self):
        if not SELECTION.exists():
            self.skipTest("the repository selects no Monte Carlo run")
        patcher = patch.object(runs, "SELECTION_PATH", SELECTION)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run_dir = runs.selected_run_for(DATA)
        self.assertIsNotNone(self.run_dir)

    def test_selected_run_matches_like_the_command_line_check(self):
        info = get_data_overview()
        run_dir = self.run_dir
        try:
            fp = runs.check_run(run_dir, DATA)
        except ValueError:
            self.assertEqual(info["run"]["status"], "stale")
            return
        self.assertEqual(info["run"]["status"], "match")
        self.assertEqual(info["run"]["settings"], fp["settings"])
        self.assertEqual(info["run"]["grid"], runs.grid_status(run_dir))
        self.assertIn(info["run"]["name"], info["run"]["message"])

    def test_no_selection(self):
        with patch.object(runs, "SELECTION_PATH", None):
            run = get_data_overview()["run"]
        self.assertEqual((run["status"], run["name"], run["settings"]), ("none", None, None))

    def test_changed_data_is_reported_as_stale(self):
        """One input file reads differently: the run no longer matches.  The
        file itself is not touched; its content hash is replaced for the check."""
        real = runs.normalised_sha256

        def changed(path):
            return "0" * 64 if Path(path).name == "orders.csv" else real(path)

        with patch.object(runs, "normalised_sha256", changed):
            run = get_data_overview()["run"]
        self.assertEqual(run["status"], "stale")
        self.assertIsNone(run["settings"])
        self.assertIn("orders.csv", run["detail"])
        self.assertIn("must not be used", run["message"])

    def test_a_copy_of_the_data_has_no_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "data"
            shutil.copytree(DATA, copy)
            run = get_data_overview(copy)["run"]
        self.assertEqual(run["status"], "none")

    def test_unreadable_selection_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "run_selection.json"
            bad.write_text("{not json", encoding="utf-8")
            with patch.object(runs, "SELECTION_PATH", bad):
                run = get_data_overview()["run"]
        self.assertEqual(run["status"], "invalid")
        self.assertTrue(run["detail"])


if __name__ == "__main__":
    unittest.main()
