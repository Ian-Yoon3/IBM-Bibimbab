"""Tests for the stage 1 data fixture and use_stage1_default_data context manager."""

import tempfile
import unittest
from pathlib import Path

import engine.loader
import engine.tools
from scripts.stage1_data import make_stage1_data_dir, use_stage1_default_data

_REPO_DATA = Path(__file__).resolve().parent.parent / "data"


class TestStage1Folder(unittest.TestCase):
    """The stage 1 folder loads and delivers the expected world-risk numbers."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._stage1_dir = make_stage1_data_dir(Path(cls._tmp) / "data")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_stage1_folder_loads(self):
        from engine.loader import load_all
        db = load_all(self._stage1_dir)
        self.assertIsNotNone(db["worlds"])
        self.assertEqual(len(db["worlds"]), 11)

    def test_stage1_world_risk_wait(self):
        result = engine.tools.get_world_risk("D01", data_dir=self._stage1_dir)
        opts = {o["scenario_id"]: o for o in result["options"]}
        self.assertEqual(round(opts["WAIT"]["expected_late_orders"], 2), 6.53)

    def test_stage1_world_risk_transfer(self):
        result = engine.tools.get_world_risk("D01", data_dir=self._stage1_dir)
        opts = {o["scenario_id"]: o for o in result["options"]}
        self.assertEqual(round(opts["TRANSFER"]["expected_late_orders"], 2), 3.73)

    def test_stage1_world_risk_alt_buy(self):
        result = engine.tools.get_world_risk("D01", data_dir=self._stage1_dir)
        opts = {o["scenario_id"]: o for o in result["options"]}
        self.assertEqual(round(opts["ALT_BUY"]["expected_late_orders"], 2), 2.99)

    def test_stage1_world_risk_hybrid(self):
        result = engine.tools.get_world_risk("D01", data_dir=self._stage1_dir)
        opts = {o["scenario_id"]: o for o in result["options"]}
        self.assertEqual(round(opts["HYBRID"]["expected_late_orders"], 2), 1.36)


class TestRepoDataNoWorlds(unittest.TestCase):
    """The repository's data/ has no worlds.csv; get_world_risk reports announced_date."""

    def test_repo_data_no_worlds_csv(self):
        worlds_path = _REPO_DATA / "worlds.csv"
        self.assertFalse(worlds_path.exists(),
                         "data/worlds.csv must not exist in the repository data/")

    def test_repo_data_world_risk_announced_date(self):
        result = engine.tools.get_world_risk("D01", data_dir=_REPO_DATA)
        self.assertEqual(result["weights_source"], "announced_date")


class TestContextManagerRestores(unittest.TestCase):
    """use_stage1_default_data() restores the previous _DEFAULT_DATA_DIR on exit."""

    def test_default_data_dir_restored(self):
        original = engine.loader._DEFAULT_DATA_DIR
        with use_stage1_default_data():
            inside = engine.loader._DEFAULT_DATA_DIR
            self.assertNotEqual(inside, original)
        self.assertEqual(engine.loader._DEFAULT_DATA_DIR, original)

    def test_default_data_dir_is_repo_data_after_exit(self):
        with use_stage1_default_data():
            pass
        self.assertEqual(
            engine.loader._DEFAULT_DATA_DIR.resolve(),
            _REPO_DATA.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
