"""Tests for montecarlo.estimate (stage 2, step 4b part 2).

The mini history is built in a temp copy of data/ for most tests;
only test_demo_history_runs uses the committed data/history/ files.
"""

import csv
import math
import pathlib
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from fractions import Fraction

from montecarlo.estimate import estimate
from montecarlo.estimate import predictive_size_pmf

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Mini history content
# ---------------------------------------------------------------------------

_CAUSES_CSV = """\
cause_id,day_unit,target_type,target_id
K1,business,purchase_order,PO01
K1,business,offer,OF02
K2,calendar,lane,LN01
K2,calendar,lane,LN02
"""

_EPISODES_CSV = """\
episode_id,cause_id,start_date,end_date,delay_days
E1,K1,2026-03-02,2026-03-04,2
E2,K1,2026-06-15,2026-06-16,4
E3,K2,2026-02-10,2026-02-11,1
"""

_SHIPMENTS_CSV = """\
shipment_id,source_id,ship_date,promised_date,receipt_date,episode_id
S1,OF01,2026-03-02,2026-03-09,2026-03-11,E1
S2,OF01,2026-04-06,2026-04-13,2026-04-16,
S3,OF01,2026-05-04,2026-05-11,2026-05-08,
S4,OF02,2026-06-15,2026-06-18,2026-06-24,E2
S5,OF02,2026-08-03,2026-08-06,2026-08-06,
S6,LN01,2026-02-10,2026-02-12,2026-02-13,E3
S7,LN01,2026-07-01,2026-07-03,2026-07-05,
S8,LN02,2026-09-01,2026-09-05,2026-09-05,
"""

# Mini history with an open K2 episode added
_EPISODES_WITH_OPEN_CSV = """\
episode_id,cause_id,start_date,end_date,delay_days
E1,K1,2026-03-02,2026-03-04,2
E2,K1,2026-06-15,2026-06-16,4
E3,K2,2026-02-10,2026-02-11,1
E4,K2,2026-11-05,,2
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mini_history(episodes_csv=_EPISODES_CSV) -> pathlib.Path:
    """Copy data/ into a temp dir and write the mini history files.

    Returns the path to the temp data directory.
    Caller is responsible for cleanup (use as context manager via tmpdir).
    """
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(DATA_DIR, tmpdir / "data", dirs_exist_ok=True)
    hist = tmpdir / "data" / "history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / "causes.csv").write_text(_CAUSES_CSV, encoding="utf-8")
    (hist / "episodes.csv").write_text(episodes_csv, encoding="utf-8")
    (hist / "shipments.csv").write_text(_SHIPMENTS_CSV, encoding="utf-8")
    return tmpdir / "data"


class _MiniHistoryBase(unittest.TestCase):
    """Base class: creates a temp mini history in setUpClass, removes in tearDownClass."""

    _EPISODES = _EPISODES_CSV

    @classmethod
    def setUpClass(cls):
        cls._tmpdir_obj = tempfile.mkdtemp()
        cls._tmpdir = pathlib.Path(cls._tmpdir_obj)
        shutil.copytree(DATA_DIR, cls._tmpdir / "data", dirs_exist_ok=True)
        hist = cls._tmpdir / "data" / "history"
        hist.mkdir(parents=True, exist_ok=True)
        (hist / "causes.csv").write_text(_CAUSES_CSV, encoding="utf-8")
        (hist / "episodes.csv").write_text(cls._EPISODES, encoding="utf-8")
        (hist / "shipments.csv").write_text(_SHIPMENTS_CSV, encoding="utf-8")
        cls.result = estimate(cls._tmpdir / "data")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir_obj, ignore_errors=True)


# ---------------------------------------------------------------------------
# Own delay computation
# ---------------------------------------------------------------------------

class TestOwnDelays(_MiniHistoryBase):
    """Check the own delay of each shipment matches the spec."""

    # Expected own delays from the spec
    EXPECTED = {
        "S1": 0,
        "S2": 3,
        "S3": -1,
        "S4": -1,  # Juneteenth 2026-06-19 is closed
        "S5": 0,
        "S6": 0,
        "S7": 2,
        "S8": 0,
    }

    def _compute_own_delays(self):
        """Recompute own delays from raw files and return {shipment_id: own}."""
        from engine.loader import load_all
        db  = load_all(self._tmpdir / "data")
        cal = db["calendar"]
        hist = self._tmpdir / "data" / "history"

        with (hist / "episodes.csv").open(encoding="utf-8") as fh:
            eps = {r["episode_id"]: r for r in csv.DictReader(fh)}

        # day unit per source (from causes.csv)
        source_day_unit = {
            "OF01": "business", "OF02": "business",
            "LN01": "calendar", "LN02": "calendar",
        }

        own_delays = {}
        with (hist / "shipments.csv").open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                sid  = row["shipment_id"]
                src  = row["source_id"]
                prom = date.fromisoformat(row["promised_date"])
                rcpt = date.fromisoformat(row["receipt_date"])
                eid  = row["episode_id"]
                sev  = int(eps[eid]["delay_days"]) if eid else 0

                dunit = source_day_unit[src]
                if dunit == "business":
                    if rcpt > prom:
                        raw = cal.business_days_between(prom, rcpt)
                    elif rcpt < prom:
                        raw = -cal.business_days_between(rcpt, prom)
                    else:
                        raw = 0
                else:
                    raw = (rcpt - prom).days

                own_delays[sid] = raw - sev
        return own_delays

    def test_own_delays_match_spec(self):
        own = self._compute_own_delays()
        for sid, expected in self.EXPECTED.items():
            self.assertEqual(own[sid], expected,
                f"{sid}: own delay {own[sid]} != expected {expected}")


# ---------------------------------------------------------------------------
# Variable posteriors
# ---------------------------------------------------------------------------

class TestVariablePosteriors(_MiniHistoryBase):

    def _vp(self, key):
        return self.result["variables"][key]

    def test_poo1_dirichlet(self):
        """PO01 (source OF01): Dirichlet (2,2,2)."""
        vp = self._vp("purchase_order.PO01")
        self.assertEqual(vp["dir_early"],  2)
        self.assertEqual(vp["dir_ontime"], 2)
        self.assertEqual(vp["dir_late"],   2)

    def test_po01_early_beta(self):
        """PO01 early: Beta(2, 1)."""
        vp = self._vp("purchase_order.PO01")
        self.assertEqual(vp["early_a"], 2)
        self.assertEqual(vp["early_b"], 1)

    def test_po01_late_beta(self):
        """PO01 late: Beta(2, 3)."""
        vp = self._vp("purchase_order.PO01")
        self.assertEqual(vp["late_a"], 2)
        self.assertEqual(vp["late_b"], 3)

    def test_po01_prior_share(self):
        """PO01 prior_share = 0.5 (3 records, 3/(3+3))."""
        vp = self._vp("purchase_order.PO01")
        self.assertAlmostEqual(vp["prior_share"], 0.5)

    def test_po01_new_fields(self):
        """PO01 variable has cause_id, day_unit, source_id."""
        vp = self._vp("purchase_order.PO01")
        self.assertEqual(vp["cause_id"],  "K1")
        self.assertEqual(vp["day_unit"],  "business")
        self.assertEqual(vp["source_id"], "OF01")

    def test_of02_dirichlet(self):
        """OF02: Dirichlet (2,2,1)."""
        vp = self._vp("offer.OF02")
        self.assertEqual(vp["dir_early"],  2)
        self.assertEqual(vp["dir_ontime"], 2)
        self.assertEqual(vp["dir_late"],   1)

    def test_of02_early_beta(self):
        """OF02 early: Beta(2, 1)."""
        vp = self._vp("offer.OF02")
        self.assertEqual(vp["early_a"], 2)
        self.assertEqual(vp["early_b"], 1)

    def test_of02_late_beta(self):
        """OF02 late: Beta(1, 1)."""
        vp = self._vp("offer.OF02")
        self.assertEqual(vp["late_a"], 1)
        self.assertEqual(vp["late_b"], 1)

    def test_of02_prior_share(self):
        """OF02 prior_share = 0.6 (2 records)."""
        vp = self._vp("offer.OF02")
        self.assertAlmostEqual(vp["prior_share"], 0.6)

    def test_ln01_dirichlet(self):
        """LN01: Dirichlet (1,2,2)."""
        vp = self._vp("lane.LN01")
        self.assertEqual(vp["dir_early"],  1)
        self.assertEqual(vp["dir_ontime"], 2)
        self.assertEqual(vp["dir_late"],   2)

    def test_ln01_late_beta(self):
        """LN01 late: Beta(2, 2)."""
        vp = self._vp("lane.LN01")
        self.assertEqual(vp["late_a"], 2)
        self.assertEqual(vp["late_b"], 2)

    def test_ln01_prior_share(self):
        """LN01 prior_share = 0.6 (2 records)."""
        vp = self._vp("lane.LN01")
        self.assertAlmostEqual(vp["prior_share"], 0.6)

    def test_ln02_dirichlet(self):
        """LN02: Dirichlet (1,2,1)."""
        vp = self._vp("lane.LN02")
        self.assertEqual(vp["dir_early"],  1)
        self.assertEqual(vp["dir_ontime"], 2)
        self.assertEqual(vp["dir_late"],   1)

    def test_ln02_prior_share(self):
        """LN02 prior_share = 0.75 (1 record)."""
        vp = self._vp("lane.LN02")
        self.assertAlmostEqual(vp["prior_share"], 0.75)


# ---------------------------------------------------------------------------
# Cause posteriors
# ---------------------------------------------------------------------------

class TestCausePosteriors(_MiniHistoryBase):

    def _cp(self, cid):
        return self.result["causes"][cid]

    def test_k1_n_S(self):
        """K1: n=2, S=4."""
        cp = self._cp("K1")
        self.assertEqual(cp["n"], 2)
        self.assertEqual(cp["S"], 4)

    def test_k1_rate(self):
        """K1: Gamma(shape=3, rate=T=365)."""
        cp = self._cp("K1")
        self.assertEqual(cp["rate_shape"], 3)
        self.assertEqual(cp["rate_rate"],  365)
        self.assertEqual(cp["T_days"],     365)

    def test_k1_severity(self):
        """K1: Beta(3, 5)."""
        cp = self._cp("K1")
        self.assertEqual(cp["severity_a"], 3)
        self.assertEqual(cp["severity_b"], 5)

    def test_k1_w_days(self):
        """K1: w = 8 days (DAY0 2026-11-09 to revised date 2026-11-17)."""
        cp = self._cp("K1")
        self.assertEqual(cp["w_days"], 8)

    def test_k1_p_active(self):
        """K1: P(active) ≈ 0.062973 (6 decimal places)."""
        cp = self._cp("K1")
        self.assertAlmostEqual(cp["p_active"], 0.062973, places=6)

    def test_k2_n_S(self):
        """K2: n=1, S=0."""
        cp = self._cp("K2")
        self.assertEqual(cp["n"], 1)
        self.assertEqual(cp["S"], 0)

    def test_k2_rate(self):
        """K2: Gamma(shape=2, rate=T=365)."""
        cp = self._cp("K2")
        self.assertEqual(cp["rate_shape"], 2)
        self.assertEqual(cp["rate_rate"],  365)
        self.assertEqual(cp["T_days"],     365)

    def test_k2_severity(self):
        """K2: Beta(2, 1)."""
        cp = self._cp("K2")
        self.assertEqual(cp["severity_a"], 2)
        self.assertEqual(cp["severity_b"], 1)

    def test_k2_w_days(self):
        """K2: w = 4 days (DAY0+4 for LN02)."""
        cp = self._cp("K2")
        self.assertEqual(cp["w_days"], 4)

    def test_k2_p_active(self):
        """K2: P(active) ≈ 0.021563 (6 decimal places)."""
        cp = self._cp("K2")
        self.assertAlmostEqual(cp["p_active"], 0.021563, places=6)


# ---------------------------------------------------------------------------
# Open episode makes P(active) exactly 1
# ---------------------------------------------------------------------------

class _MiniHistoryWithOpen(_MiniHistoryBase):
    _EPISODES = _EPISODES_WITH_OPEN_CSV


class TestOpenEpisode(_MiniHistoryWithOpen):

    def test_k2_open_n_S(self):
        """K2 with open episode: n=2, S=1."""
        cp = self.result["causes"]["K2"]
        self.assertEqual(cp["n"], 2)
        self.assertEqual(cp["S"], 1)

    def test_k2_open_severity(self):
        """K2 with open episode: Beta(3, 2)."""
        cp = self.result["causes"]["K2"]
        self.assertEqual(cp["severity_a"], 3)
        self.assertEqual(cp["severity_b"], 2)

    def test_k2_p_active_is_one(self):
        """K2 with open episode: P(active) = exactly 1."""
        cp = self.result["causes"]["K2"]
        self.assertEqual(cp["open_on_day0"], True)
        self.assertEqual(cp["p_active"], 1.0)


# ---------------------------------------------------------------------------
# predictive_size_pmf
# ---------------------------------------------------------------------------

class TestPredictiveSizePmf(unittest.TestCase):

    def test_pmf_3_5_0(self):
        """predictive_size_pmf(3, 5, 0) = 3/8."""
        result = predictive_size_pmf(3, 5, 0)
        self.assertIsInstance(result, Fraction)
        self.assertEqual(result, Fraction(3, 8))

    def test_pmf_3_5_1(self):
        """predictive_size_pmf(3, 5, 1) = 5/24."""
        result = predictive_size_pmf(3, 5, 1)
        self.assertIsInstance(result, Fraction)
        self.assertEqual(result, Fraction(5, 24))

    def test_pmf_sums_to_one(self):
        """Sum over sufficiently many k should be close to 1."""
        total = sum(predictive_size_pmf(3, 5, k) for k in range(500))
        self.assertAlmostEqual(float(total), 1.0, places=3)

    def test_pmf_is_fraction(self):
        """Return type is always Fraction."""
        for k in range(5):
            self.assertIsInstance(predictive_size_pmf(2, 3, k), Fraction)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidationErrors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir_obj = tempfile.mkdtemp()
        cls._tmpdir = pathlib.Path(cls._tmpdir_obj)
        shutil.copytree(DATA_DIR, cls._tmpdir / "data", dirs_exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir_obj, ignore_errors=True)

    def _write_history(self, episodes_csv=_EPISODES_CSV,
                       shipments_csv=_SHIPMENTS_CSV,
                       causes_csv=_CAUSES_CSV):
        hist = self._tmpdir / "data" / "history"
        hist.mkdir(parents=True, exist_ok=True)
        (hist / "causes.csv").write_text(causes_csv, encoding="utf-8")
        (hist / "episodes.csv").write_text(episodes_csv, encoding="utf-8")
        (hist / "shipments.csv").write_text(shipments_csv, encoding="utf-8")

    def test_unknown_episode_id_raises(self):
        """A shipment referencing a non-existent episode_id raises ValueError."""
        bad_shipments = _SHIPMENTS_CSV.replace("S1,OF01,2026-03-02,2026-03-09,2026-03-11,E1",
                                               "S1,OF01,2026-03-02,2026-03-09,2026-03-11,E99")
        self._write_history(shipments_csv=bad_shipments)
        with self.assertRaises(ValueError) as ctx:
            estimate(self._tmpdir / "data")
        self.assertIn("E99", str(ctx.exception))

    def test_wrong_cause_episode_raises(self):
        """A K2 episode assigned to an OF01 shipment raises ValueError."""
        # S1 is OF01 (K1 source), E3 is K2 — mismatch
        bad_shipments = _SHIPMENTS_CSV.replace("S1,OF01,2026-03-02,2026-03-09,2026-03-11,E1",
                                               "S1,OF01,2026-03-02,2026-03-09,2026-03-11,E3")
        self._write_history(shipments_csv=bad_shipments)
        with self.assertRaises(ValueError) as ctx:
            estimate(self._tmpdir / "data")
        # Error should mention the cause mismatch
        msg = str(ctx.exception)
        self.assertTrue("K1" in msg or "K2" in msg or "E3" in msg,
            f"Error message should reference the cause mismatch: {msg}")

    def test_bad_shipments_header_raises(self):
        """Wrong shipments header raises ValueError."""
        bad = "shipment_id,source_id,ship_date,promised_date,receipt_date\n"
        bad += "S1,OF01,2026-03-02,2026-03-09,2026-03-11\n"
        self._write_history(shipments_csv=bad)
        with self.assertRaises(ValueError) as ctx:
            estimate(self._tmpdir / "data")
        self.assertIn("shipments.csv", str(ctx.exception))

    def test_bad_episodes_header_raises(self):
        """Wrong episodes header raises ValueError."""
        bad = "episode_id,cause_id,start_date,end_date\n"
        bad += "E1,K1,2026-03-02,2026-03-04\n"
        self._write_history(episodes_csv=bad)
        with self.assertRaises(ValueError) as ctx:
            estimate(self._tmpdir / "data")
        self.assertIn("episodes.csv", str(ctx.exception))


# ---------------------------------------------------------------------------
# Demo history (committed data/history/)
# ---------------------------------------------------------------------------

class TestDemoHistory(unittest.TestCase):
    """estimate() runs without error on the committed demo history."""

    def test_runs_without_error(self):
        result = estimate(DATA_DIR)
        self.assertIn("causes",    result)
        self.assertIn("variables", result)
        # Both causes present
        self.assertIn("K1", result["causes"])
        self.assertIn("K2", result["causes"])
        # All four variables present under new keys
        expected_keys = {
            "purchase_order.PO01", "offer.OF02", "lane.LN01", "lane.LN02"
        }
        self.assertEqual(set(result["variables"].keys()), expected_keys)

    def test_p_active_in_range(self):
        result = estimate(DATA_DIR)
        for cid, cp in result["causes"].items():
            if cp["open_on_day0"]:
                self.assertEqual(cp["p_active"], 1.0)
            else:
                self.assertGreater(cp["p_active"], 0.0)
                self.assertLess(cp["p_active"], 1.0)

    def test_prior_shares_in_range(self):
        result = estimate(DATA_DIR)
        for src, vp in result["variables"].items():
            self.assertGreater(vp["prior_share"], 0.0)
            self.assertLessEqual(vp["prior_share"], 1.0)


if __name__ == "__main__":
    import unittest
    unittest.main()
