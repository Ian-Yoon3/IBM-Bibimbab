"""Review tests for step 6b-1b (written without Bob, after Claude's review).

They check the VALUES of the run-only cause fields, which the 6b-1b tests only
checked for presence:
- grid per cause: crossings and max values converted from grid.json with
  per_year = -ln(1 - p) / D0_days * 365;
- common_scale: the multiplier m taken from the recorded grid points (the first
  version divided m by lam_bar * D0 a second time);
- per_year_mean: taken from run_record.json, never filled with a default.
"""

import json
import math
import pathlib
import shutil
import tempfile
import unittest

import engine.runs
from engine.loader import load_all
from montecarlo.run import build_run

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _r(x, d):
    return engine.runs._round_half_away_float(x, d)


class TestRunOnlyCauseValues(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data = base / "data"
        shutil.copytree(_DATA_DIR, cls.data)
        cls.run_dir = base / "runs" / "g"
        build_run(cls.data, cls.run_dir, M=20, N=10, seed=13,
                  grid=True, target_se=0.5, pilot_M=4, max_M=8)
        cls.result = engine.runs.evaluate_run("D01", load_all(cls.data), cls.run_dir)
        with (cls.run_dir / "grid.json").open(encoding="utf-8") as fh:
            cls.grid = json.load(fh)
        with (cls.run_dir / "run_record.json").open(encoding="utf-8") as fh:
            cls.record = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _family(self, name):
        return next(f for f in self.grid["families"] if f["family"] == name)

    def test_per_year_mean_from_record(self):
        for entry in self.result["causes"]:
            want = _r(self.record["causes"][entry["cause_id"]]["per_year_mean"], 1)
            self.assertEqual(entry["per_year_mean"], want)

    def test_cause_grid_values(self):
        for entry in self.result["causes"]:
            fam = self._family(entry["cause_id"])
            d0 = fam["D0_days"]
            g = entry["grid"]
            self.assertEqual(g["D0_days"], d0)
            max_p = max(p["p"] for p in fam["points"] if p["kind"] == "grid")
            self.assertEqual(g["max_p"], max_p)
            self.assertEqual(g["max_per_year"],
                             _r(-math.log(1 - max_p) / d0 * 365, 1))
            want = [
                {"pair": c["pair"], "p_lo": c["p_lo"], "p_hi": c["p_hi"],
                 "per_year_lo": _r(-math.log(1 - c["p_lo"]) / d0 * 365, 1),
                 "per_year_hi": _r(-math.log(1 - c["p_hi"]) / d0 * 365, 1)}
                for c in fam["crossings"]
            ]
            self.assertEqual(g["crossings"], want)

    def test_common_scale_uses_recorded_m(self):
        fam = self._family("scale")
        cs = self.result["common_scale"]
        self.assertEqual(cs["reference_cause"], fam["reference_cause"])
        grid_ms = [p["m"] for p in fam["points"] if p["kind"] == "grid"]
        self.assertEqual(cs["max_m"], _r(max(grid_ms), 2))
        m_at = {p["p"]: p["m"] for p in fam["points"]}
        want = [
            {"pair": c["pair"], "p_lo": c["p_lo"], "p_hi": c["p_hi"],
             "m_lo": _r(m_at[c["p_lo"]], 2), "m_hi": _r(m_at[c["p_hi"]], 2)}
            for c in fam["crossings"]
        ]
        self.assertEqual(cs["crossings"], want)

    def test_per_year_mean_missing_stays_none(self):
        """A record without per_year_mean gives None, not a made-up value."""
        run2 = pathlib.Path(self._tmp) / "runs" / "g2"
        shutil.copytree(self.run_dir, run2)
        rec = json.loads((run2 / "run_record.json").read_text(encoding="utf-8"))
        for c in rec["causes"].values():
            c.pop("per_year_mean", None)
            c.pop("rate_shape", None)
        (run2 / "run_record.json").write_text(json.dumps(rec), encoding="utf-8")
        orig = engine.runs.check_run
        engine.runs.check_run = lambda run_dir, data_dir=None: json.loads(
            (pathlib.Path(run_dir) / "fingerprint.json").read_text(encoding="utf-8"))
        try:
            res = engine.runs.evaluate_run("D01", load_all(self.data), run2)
        finally:
            engine.runs.check_run = orig
        for entry in res["causes"]:
            self.assertIsNone(entry["per_year_mean"])


if __name__ == "__main__":
    unittest.main()
