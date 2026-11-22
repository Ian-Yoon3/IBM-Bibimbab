"""Tests for episode-level checks and per-cause statistics in montecarlo.estimate.

Covers the new episode validation rules, shipment/episode delay check,
and new cause posterior fields: n, T_free_days, duration, prior shares,
open_episode.
"""

import pathlib
import shutil
import tempfile
import unittest
from fractions import Fraction

from montecarlo.estimate import estimate

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Demo history episodes (verbatim copy of data/history/episodes.csv content)
# ---------------------------------------------------------------------------

_DEMO_EPISODES = """\
episode_id,cause_id,start_date,end_date,delay_days
K1E001,K1,2026-04-12,2026-04-13,2
K1E002,K1,2026-07-01,2026-07-05,1
K1E003,K1,2026-07-17,2026-07-17,4
K2E001,K2,2025-11-10,2025-11-12,1
K2E002,K2,2025-11-25,2025-11-26,1
K2E003,K2,2026-02-07,2026-02-08,1
K2E004,K2,2026-04-13,2026-04-13,1
K2E005,K2,2026-08-14,2026-08-14,3
K2E006,K2,2026-08-27,2026-08-29,2
K2E007,K2,2026-10-02,2026-10-02,2
"""

_DEMO_SHIPMENTS_PATH = DATA_DIR / "history" / "shipments.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_demo_copy(episodes_csv=None, shipments_csv=None):
    """Copy data/ into a temp dir; optionally override history files.

    Returns the path to the temp data directory.
    """
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(DATA_DIR, tmpdir / "data", dirs_exist_ok=True)
    data = tmpdir / "data"
    hist = data / "history"
    if episodes_csv is not None:
        (hist / "episodes.csv").write_text(episodes_csv, encoding="utf-8")
    if shipments_csv is not None:
        (hist / "shipments.csv").write_text(shipments_csv, encoding="utf-8")
    return data, tmpdir


# ---------------------------------------------------------------------------
# Demo history values
# ---------------------------------------------------------------------------

class TestDemoCausePosteriors(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = estimate(DATA_DIR)

    def _cp(self, cid):
        return self.result["causes"][cid]

    # K1

    def test_k1_n(self):
        """Demo K1: n=3."""
        self.assertEqual(self._cp("K1")["n"], 3)

    def test_k1_T_free_days(self):
        """Demo K1: T_free_days=357."""
        self.assertEqual(self._cp("K1")["T_free_days"], 357)

    def test_k1_duration(self):
        """Demo K1: duration_a=4, duration_b=6."""
        cp = self._cp("K1")
        self.assertEqual(cp["duration_a"], 4)
        self.assertEqual(cp["duration_b"], 6)

    def test_k1_severity(self):
        """Demo K1: severity_a=4, severity_b=5."""
        cp = self._cp("K1")
        self.assertEqual(cp["severity_a"], 4)
        self.assertEqual(cp["severity_b"], 5)

    def test_k1_duration_prior_share(self):
        """Demo K1: duration_prior_share = 2/10 = 1/5."""
        cp = self._cp("K1")
        self.assertAlmostEqual(cp["duration_prior_share"],
                               float(Fraction(1, 5)), places=12)

    def test_k1_severity_prior_share(self):
        """Demo K1: severity_prior_share = 2/9."""
        cp = self._cp("K1")
        self.assertAlmostEqual(cp["severity_prior_share"],
                               float(Fraction(2, 9)), places=12)

    def test_k1_open_episode_none(self):
        """Demo K1: no open episode."""
        self.assertIsNone(self._cp("K1")["open_episode"])

    # K2

    def test_k2_n(self):
        """Demo K2: n=7."""
        self.assertEqual(self._cp("K2")["n"], 7)

    def test_k2_T_free_days(self):
        """Demo K2: T_free_days=352."""
        self.assertEqual(self._cp("K2")["T_free_days"], 352)

    def test_k2_duration(self):
        """Demo K2: duration_a=8, duration_b=7."""
        cp = self._cp("K2")
        self.assertEqual(cp["duration_a"], 8)
        self.assertEqual(cp["duration_b"], 7)

    def test_k2_severity(self):
        """Demo K2: severity_a=8, severity_b=5."""
        cp = self._cp("K2")
        self.assertEqual(cp["severity_a"], 8)
        self.assertEqual(cp["severity_b"], 5)

    def test_k2_duration_prior_share(self):
        """Demo K2: duration_prior_share = 2/15."""
        cp = self._cp("K2")
        self.assertAlmostEqual(cp["duration_prior_share"],
                               float(Fraction(2, 15)), places=12)

    def test_k2_severity_prior_share(self):
        """Demo K2: severity_prior_share = 2/13."""
        cp = self._cp("K2")
        self.assertAlmostEqual(cp["severity_prior_share"],
                               float(Fraction(2, 13)), places=12)


# ---------------------------------------------------------------------------
# V1: K2E000 starts before period_start (allowed, counts for coverage/duration
#     but not for n)
# ---------------------------------------------------------------------------

_V1_EPISODES = _DEMO_EPISODES + "K2E000,K2,2025-11-05,2025-11-09,2\n"


class TestV1EpisodeBeforePeriod(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        data, cls._tmpdir = _make_demo_copy(episodes_csv=_V1_EPISODES)
        cls.result = estimate(data)
        shutil.rmtree(str(cls._tmpdir), ignore_errors=True)

    def test_k2_n_unchanged(self):
        """V1 K2: n=7 (K2E000 started before period_start)."""
        self.assertEqual(self.result["causes"]["K2"]["n"], 7)

    def test_k2_T_free_days(self):
        """V1 K2: T_free_days=351."""
        self.assertEqual(self.result["causes"]["K2"]["T_free_days"], 351)

    def test_k2_duration(self):
        """V1 K2: duration_a=9, duration_b=7."""
        cp = self.result["causes"]["K2"]
        self.assertEqual(cp["duration_a"], 9)
        self.assertEqual(cp["duration_b"], 7)

    def test_k2_severity(self):
        """V1 K2: severity_a=9, severity_b=6."""
        cp = self.result["causes"]["K2"]
        self.assertEqual(cp["severity_a"], 9)
        self.assertEqual(cp["severity_b"], 6)

    def test_k1_unchanged(self):
        """V1 K1: n=3 (unchanged)."""
        self.assertEqual(self.result["causes"]["K1"]["n"], 3)


# ---------------------------------------------------------------------------
# V2: open episode added to K1 (end and delay empty)
# ---------------------------------------------------------------------------

_V2_EPISODES = _DEMO_EPISODES + "K1E004,K1,2026-11-05,,\n"


class TestV2OpenEpisode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        data, cls._tmpdir = _make_demo_copy(episodes_csv=_V2_EPISODES)
        cls.result = estimate(data)
        shutil.rmtree(str(cls._tmpdir), ignore_errors=True)

    def test_k1_n(self):
        """V2 K1: n=4."""
        self.assertEqual(self.result["causes"]["K1"]["n"], 4)

    def test_k1_T_free_days(self):
        """V2 K1: T_free_days=353."""
        self.assertEqual(self.result["causes"]["K1"]["T_free_days"], 353)

    def test_k1_duration(self):
        """V2 K1: duration_a=4, duration_b=10."""
        cp = self.result["causes"]["K1"]
        self.assertEqual(cp["duration_a"], 4)
        self.assertEqual(cp["duration_b"], 10)

    def test_k1_severity_unchanged(self):
        """V2 K1: severity_a=4, severity_b=5 (open episode has no delay)."""
        cp = self.result["causes"]["K1"]
        self.assertEqual(cp["severity_a"], 4)
        self.assertEqual(cp["severity_b"], 5)

    def test_k1_open_on_day0(self):
        """V2 K1: open_on_day0=True."""
        self.assertTrue(self.result["causes"]["K1"]["open_on_day0"])

    def test_k1_open_episode_start(self):
        """V2 K1: open_episode start_date=2026-11-05."""
        from datetime import date
        oe = self.result["causes"]["K1"]["open_episode"]
        self.assertIsNotNone(oe)
        self.assertEqual(oe["start_date"], date(2026, 11, 5))

    def test_k1_open_episode_end_none(self):
        """V2 K1: open_episode end_date=None."""
        oe = self.result["causes"]["K1"]["open_episode"]
        self.assertIsNone(oe["end_date"])

    def test_k1_open_episode_delay_none(self):
        """V2 K1: open_episode delay_days=None."""
        oe = self.result["causes"]["K1"]["open_episode"]
        self.assertIsNone(oe["delay_days"])


# ---------------------------------------------------------------------------
# V3: announced end for K1E004 (open_on_day0, with recorded delay)
# ---------------------------------------------------------------------------

_V3_EPISODES = _DEMO_EPISODES + "K1E004,K1,2026-11-05,2026-11-12,3\n"


class TestV3AnnouncedEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        data, cls._tmpdir = _make_demo_copy(episodes_csv=_V3_EPISODES)
        cls.result = estimate(data)
        shutil.rmtree(str(cls._tmpdir), ignore_errors=True)

    def test_k1_n(self):
        """V3 K1: n=4."""
        self.assertEqual(self.result["causes"]["K1"]["n"], 4)

    def test_k1_T_free_days(self):
        """V3 K1: T_free_days=353."""
        self.assertEqual(self.result["causes"]["K1"]["T_free_days"], 353)

    def test_k1_duration(self):
        """V3 K1: duration_a=5, duration_b=13."""
        cp = self.result["causes"]["K1"]
        self.assertEqual(cp["duration_a"], 5)
        self.assertEqual(cp["duration_b"], 13)

    def test_k1_severity(self):
        """V3 K1: severity_a=5, severity_b=7."""
        cp = self.result["causes"]["K1"]
        self.assertEqual(cp["severity_a"], 5)
        self.assertEqual(cp["severity_b"], 7)

    def test_k1_open_on_day0(self):
        """V3 K1: open_on_day0=True."""
        self.assertTrue(self.result["causes"]["K1"]["open_on_day0"])

    def test_k1_open_episode_end(self):
        """V3 K1: open_episode end_date=2026-11-12."""
        from datetime import date
        oe = self.result["causes"]["K1"]["open_episode"]
        self.assertIsNotNone(oe)
        self.assertEqual(oe["end_date"], date(2026, 11, 12))

    def test_k1_open_episode_delay(self):
        """V3 K1: open_episode delay_days=3."""
        oe = self.result["causes"]["K1"]["open_episode"]
        self.assertEqual(oe["delay_days"], 3)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestEpisodeErrors(unittest.TestCase):

    def _run(self, episodes_csv, shipments_csv=None):
        data, tmpdir = _make_demo_copy(episodes_csv=episodes_csv,
                                       shipments_csv=shipments_csv)
        try:
            return estimate(data)
        finally:
            shutil.rmtree(str(tmpdir), ignore_errors=True)

    def test_overlap_raises(self):
        """K1X (2026-07-03..2026-07-04) overlaps K1E002 (2026-07-01..2026-07-05)."""
        eps = _DEMO_EPISODES + "K1X,K1,2026-07-03,2026-07-04,1\n"
        with self.assertRaises(ValueError) as ctx:
            self._run(eps)
        msg = str(ctx.exception)
        self.assertIn("K1X", msg)
        self.assertIn("K1E002", msg)

    def test_adjacent_allowed(self):
        """K1X starting 2026-07-06 (day after K1E002 ends 2026-07-05) is adjacent — no error."""
        eps = _DEMO_EPISODES + "K1X,K1,2026-07-06,2026-07-06,1\n"
        result = self._run(eps)
        self.assertIn("K1", result["causes"])

    def test_entirely_before_period_raises(self):
        """Episode with end_date before period_start raises ValueError."""
        eps = _DEMO_EPISODES + "K1X,K1,2025-11-01,2025-11-08,1\n"
        with self.assertRaises(ValueError) as ctx:
            self._run(eps)
        msg = str(ctx.exception)
        self.assertIn("episodes.csv", msg)

    def test_end_before_start_raises(self):
        """Episode with end_date < start_date raises ValueError."""
        eps = _DEMO_EPISODES + "K1X,K1,2026-05-10,2026-05-09,1\n"
        with self.assertRaises(ValueError) as ctx:
            self._run(eps)
        msg = str(ctx.exception)
        self.assertIn("episodes.csv", msg)

    def test_delay_days_zero_raises(self):
        """Episode with delay_days=0 raises ValueError."""
        eps = _DEMO_EPISODES + "K1X,K1,2026-09-01,2026-09-02,0\n"
        with self.assertRaises(ValueError) as ctx:
            self._run(eps)
        msg = str(ctx.exception)
        self.assertIn("episodes.csv", msg)

    def test_empty_delay_on_closed_episode_raises(self):
        """Closed episode with empty delay_days raises ValueError."""
        eps = _DEMO_EPISODES + "K1X,K1,2026-09-01,2026-09-02,\n"
        with self.assertRaises(ValueError) as ctx:
            self._run(eps)
        msg = str(ctx.exception)
        self.assertIn("episodes.csv", msg)

    def test_shipment_to_no_delay_episode_raises(self):
        """Shipment referencing an open episode with no delay_days raises ValueError."""
        eps = _DEMO_EPISODES + "K1E004,K1,2026-11-05,,\n"
        # Read demo shipments and append a new shipment referencing K1E004
        demo_ships = _DEMO_SHIPMENTS_PATH.read_text(encoding="utf-8")
        new_ship = "OF01999,OF01,2026-11-01,2026-11-06,2026-11-07,K1E004\n"
        ships = demo_ships.rstrip("\n") + "\n" + new_ship
        with self.assertRaises(ValueError) as ctx:
            self._run(eps, shipments_csv=ships)
        msg = str(ctx.exception)
        self.assertIn("shipments.csv", msg)
        self.assertIn("OF01999", msg)
        self.assertIn("K1E004", msg)


if __name__ == "__main__":
    unittest.main()
