"""Tests for montecarlo.generator (stage 2, step 4b part 1).

Coverage:
 1. Same seed → identical files; different seed → different files.
 2. Exact shipment counts per source; dates inside the period;
    business-day sources land on business days.
 3. episode_id set exactly when cause overlaps transit; episodes of one
    cause never overlap; durations and severities >= 1.
 4. Round-trip: own delay recomputed from files == internal value for
    unclamped shipments.
 5. Truth recovery over 2000 seeds (in memory, no files): mean episodes/year
    for K1 ~ 3.90 (tol 0.15), K2 ~ 4.90 (tol 0.15); category shares
    within 0.02; mean size within 0.05; mean severity within 0.10.
 6. Committed demo files (seed 20261109) match a fresh run.
 7. closed_days.csv override: a closed Monday is never a business-day date.
 8. causes.csv validation errors raise ValueError with file name.
"""

import csv
import math
import pathlib
import random
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from engine.business_calendar import BusinessCalendar
from engine.loader import load_all

# Module under test
from montecarlo.generator import (
    generate_history,
    _load_causes,
    _own_delay_sample,
    _geom_non_neg,
    _generate_episodes,
    _shipment_schedule,
    N_OF01, N_OF02, N_LN01, N_LN02,
    K1_RATE, K1_SEV_MEAN, K1_DUR_MEAN,
    K2_RATE, K2_SEV_MEAN, K2_DUR_MEAN,
    OF01_P_EARLY, OF01_P_ONTIME, OF01_P_LATE, OF01_MEAN_SIZE,
    OF02_P_EARLY, OF02_P_ONTIME, OF02_P_LATE, OF02_MEAN_SIZE,
    LN_P_EARLY, LN_P_ONTIME, LN_P_LATE, LN_MEAN_SIZE,
)

DATA_DIR   = pathlib.Path(__file__).resolve().parent.parent / "data"
DEMO_DIR   = DATA_DIR / "history"
DEMO_SEED  = 20261109

DAY0            = date(2026, 11, 9)
PERIOD_START    = DAY0 - timedelta(days=365)
PERIOD_END      = DAY0 - timedelta(days=1)

BIZ_SOURCES  = {"OF01", "OF02"}
CAL_SOURCES  = {"LN01", "LN02"}

EXPECTED_COUNTS = {"OF01": N_OF01, "OF02": N_OF02, "LN01": N_LN01, "LN02": N_LN02}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_demo():
    ships = _read_csv(DEMO_DIR / "shipments.csv")
    eps   = _read_csv(DEMO_DIR / "episodes.csv")
    return ships, eps


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _run_in_tmp(seed):
    """Run generator into a temp dir, return (shipments list, episodes list, internals)."""
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        internals = generate_history(DATA_DIR, td, seed)
        ships = _read_csv(td / "shipments.csv")
        eps   = _read_csv(td / "episodes.csv")
    return ships, eps, internals


_DEFAULT_CAL = BusinessCalendar()


def _is_biz(d: date) -> bool:
    return _DEFAULT_CAL.is_business_day(d)


# ---------------------------------------------------------------------------
# 1. Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility(unittest.TestCase):

    def test_same_seed_identical(self):
        """Two runs with the same seed must produce bit-for-bit identical files."""
        ships1, eps1, _ = _run_in_tmp(42)
        ships2, eps2, _ = _run_in_tmp(42)
        self.assertEqual(ships1, ships2)
        self.assertEqual(eps1, eps2)

    def test_different_seed_different(self):
        """Two different seeds must produce different output."""
        ships1, eps1, _ = _run_in_tmp(42)
        ships2, eps2, _ = _run_in_tmp(99)
        # At least one file differs (shipments or episodes or both)
        self.assertTrue(ships1 != ships2 or eps1 != eps2)


# ---------------------------------------------------------------------------
# 2. Shipment counts, dates, business days
# ---------------------------------------------------------------------------

class TestShipmentCounts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ships, cls.eps, cls.internals = _run_in_tmp(DEMO_SEED)

    def test_exact_counts(self):
        from collections import Counter
        counts = Counter(s["source_id"] for s in self.ships)
        for src, expected in EXPECTED_COUNTS.items():
            self.assertEqual(counts[src], expected,
                             f"{src}: expected {expected}, got {counts[src]}")

    def test_ship_dates_in_period(self):
        for s in self.ships:
            ship = date.fromisoformat(s["ship_date"])
            self.assertGreaterEqual(ship, PERIOD_START,
                f"{s['shipment_id']} ship_date {ship} before period")
            self.assertLessEqual(ship, PERIOD_END,
                f"{s['shipment_id']} ship_date {ship} after period")

    def test_business_day_sources_on_business_days(self):
        """ship_date and promised_date of OF01/OF02 must be open days."""
        for s in self.ships:
            if s["source_id"] not in BIZ_SOURCES:
                continue
            sid = s["shipment_id"]
            ship = date.fromisoformat(s["ship_date"])
            prom = date.fromisoformat(s["promised_date"])
            self.assertTrue(_is_biz(ship),
                f"{sid} ship_date {ship} is not a business day")
            self.assertTrue(_is_biz(prom),
                f"{sid} promised_date {prom} is not a business day")


# ---------------------------------------------------------------------------
# 3. Episode properties
# ---------------------------------------------------------------------------

class TestEpisodeProperties(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ships, cls.eps, cls.internals = _run_in_tmp(DEMO_SEED)
        # Build episode lookup
        cls.ep_by_id = {e["episode_id"]: e for e in cls.eps}

    def test_durations_at_least_one(self):
        """Every episode must last at least 1 day (end >= start)."""
        for e in self.eps:
            start = date.fromisoformat(e["start_date"])
            if e["end_date"]:
                end = date.fromisoformat(e["end_date"])
                self.assertGreaterEqual(end, start,
                    f"{e['episode_id']} end before start")

    def test_severities_at_least_one(self):
        for e in self.eps:
            self.assertGreaterEqual(int(e["delay_days"]), 1,
                f"{e['episode_id']} delay_days < 1")

    def test_no_overlap_within_cause(self):
        """Episodes of the same cause must not overlap."""
        from itertools import combinations
        cause_eps = {}
        for e in self.eps:
            cause_eps.setdefault(e["cause_id"], []).append(e)
        for cid, eps_list in cause_eps.items():
            # Sort by start_date
            eps_sorted = sorted(eps_list, key=lambda x: x["start_date"])
            for i in range(len(eps_sorted) - 1):
                a, b = eps_sorted[i], eps_sorted[i + 1]
                # end of a (use period_end for open episodes)
                a_end = date.fromisoformat(a["end_date"]) if a["end_date"] else PERIOD_END
                b_start = date.fromisoformat(b["start_date"])
                self.assertLess(a_end, b_start,
                    f"Cause {cid}: {a['episode_id']} (end {a_end}) "
                    f"overlaps {b['episode_id']} (start {b_start})")

    def test_episode_id_set_iff_cause_overlaps_transit(self):
        """episode_id is non-empty iff an episode of the source's cause
        overlaps [ship, promised]."""
        # Map cause per source
        source_cause = {
            "OF01": "K1", "OF02": "K1", "LN01": "K2", "LN02": "K2",
        }
        cause_eps = {}
        for e in self.eps:
            cause_eps.setdefault(e["cause_id"], []).append(e)

        for s in self.ships:
            src  = s["source_id"]
            cid  = source_cause[src]
            ship = date.fromisoformat(s["ship_date"])
            prom = date.fromisoformat(s["promised_date"])
            sid  = s["shipment_id"]
            eid  = s["episode_id"]

            # Find first overlapping episode
            first_match = None
            for ep in cause_eps.get(cid, []):
                ep_start = date.fromisoformat(ep["start_date"])
                ep_end   = (date.fromisoformat(ep["end_date"])
                            if ep["end_date"] else PERIOD_END)
                if ep_start <= prom and ep_end >= ship:
                    first_match = ep["episode_id"]
                    break

            if first_match is not None:
                self.assertEqual(eid, first_match,
                    f"{sid}: expected episode_id={first_match!r}, got {eid!r}")
            else:
                self.assertEqual(eid, "",
                    f"{sid}: expected no episode, got {eid!r}")


# ---------------------------------------------------------------------------
# 4. Round-trip: recompute own delay from files
# ---------------------------------------------------------------------------

class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ships, cls.eps, cls.internals = _run_in_tmp(DEMO_SEED)
        cls.ep_by_id = {e["episode_id"]: e for e in cls.eps}

    def _biz_signed(self, a: date, b: date) -> int:
        """Signed business-day distance: positive if b > a, negative if b < a."""
        cal = BusinessCalendar()
        if b > a:
            return cal.business_days_between(a, b)
        elif b < a:
            return -cal.business_days_between(b, a)
        return 0

    def test_own_delay_round_trip(self):
        """For unclamped shipments, own delay recomputed from files == internal."""
        source_biz = {"OF01": True, "OF02": True, "LN01": False, "LN02": False}

        for s in self.ships:
            sid  = s["shipment_id"]
            if self.internals["clamped"].get(sid, False):
                continue  # skip clamped

            prom = date.fromisoformat(s["promised_date"])
            rcpt = date.fromisoformat(s["receipt_date"])
            eid  = s["episode_id"]
            sev  = int(self.ep_by_id[eid]["delay_days"]) if eid else 0

            is_biz = source_biz[s["source_id"]]
            if is_biz:
                # signed business days from promised to receipt
                raw_delay = self._biz_signed(prom, rcpt)
            else:
                raw_delay = (rcpt - prom).days

            recomputed_own = raw_delay - sev
            expected_own   = self.internals["own_delays"][sid]

            self.assertEqual(recomputed_own, expected_own,
                f"{sid}: recomputed own={recomputed_own} != stored {expected_own} "
                f"(raw_delay={raw_delay}, sev={sev})")


# ---------------------------------------------------------------------------
# 5. Truth recovery over 2000 seeds (in-memory, no files)
# ---------------------------------------------------------------------------

class TestTruthRecovery(unittest.TestCase):
    """Check that generator statistics converge to true parameters.

    Runs 2000 independent periods in memory (no file I/O).
    """

    N_SEEDS = 2000

    @classmethod
    def setUpClass(cls):
        # Collect stats across seeds
        cls.k1_ep_counts = []
        cls.k2_ep_counts = []
        # Category counts per source
        cls.cat_counts = {src: {"early": 0, "ontime": 0, "late": 0}
                          for src in ("OF01", "OF02", "LN01", "LN02")}
        cls.size_sums  = {src: 0 for src in cls.cat_counts}
        cls.size_non0  = {src: 0 for src in cls.cat_counts}  # non-zero count
        cls.sev_sums   = {"K1": 0, "K2": 0}
        cls.sev_counts = {"K1": 0, "K2": 0}

        source_cause = {"OF01": "K1", "OF02": "K1", "LN01": "K2", "LN02": "K2"}

        for seed in range(cls.N_SEEDS):
            rng = random.Random(seed)
            cache: dict = {}

            k1_eps = _generate_episodes(rng, "K1", K1_RATE, K1_SEV_MEAN,
                                         K1_DUR_MEAN, PERIOD_START, PERIOD_END)
            k2_eps = _generate_episodes(rng, "K2", K2_RATE, K2_SEV_MEAN,
                                         K2_DUR_MEAN, PERIOD_START, PERIOD_END)

            cls.k1_ep_counts.append(len(k1_eps))
            cls.k2_ep_counts.append(len(k2_eps))

            # Accumulate severities
            for e in k1_eps:
                cls.sev_sums["K1"] += e["delay_days"]
                cls.sev_counts["K1"] += 1
            for e in k2_eps:
                cls.sev_sums["K2"] += e["delay_days"]
                cls.sev_counts["K2"] += 1

            # Accumulate own-delay category and size stats
            cause_eps = {"K1": k1_eps, "K2": k2_eps}

            source_configs = [
                ("OF01", N_OF01, True,  "K1",
                 OF01_P_EARLY, OF01_P_ONTIME, OF01_P_LATE, OF01_MEAN_SIZE),
                ("OF02", N_OF02, True,  "K1",
                 OF02_P_EARLY, OF02_P_ONTIME, OF02_P_LATE, OF02_MEAN_SIZE),
                ("LN01", N_LN01, False, "K2",
                 LN_P_EARLY, LN_P_ONTIME, LN_P_LATE, LN_MEAN_SIZE),
                ("LN02", N_LN02, False, "K2",
                 LN_P_EARLY, LN_P_ONTIME, LN_P_LATE, LN_MEAN_SIZE),
            ]

            for (src, n, biz, cause,
                 p_early, p_ontime, p_late, mean_size) in source_configs:
                for _ in range(n):
                    own = _own_delay_sample(rng, p_early, p_ontime, p_late, mean_size)
                    if own < 0:
                        cls.cat_counts[src]["early"] += 1
                        cls.size_sums[src] += abs(own)
                        cls.size_non0[src] += 1
                    elif own == 0:
                        cls.cat_counts[src]["ontime"] += 1
                    else:
                        cls.cat_counts[src]["late"] += 1
                        cls.size_sums[src] += own
                        cls.size_non0[src] += 1

    # --- Episode rate ---

    def test_k1_mean_episodes_per_year(self):
        # True Poisson rate = 4; renewal effect of durations reduces observed
        # mean to about 3.90 (see spec).
        mean = sum(self.k1_ep_counts) / len(self.k1_ep_counts)
        self.assertAlmostEqual(mean, 3.90, delta=0.15,
            msg=f"K1 mean episodes/year = {mean:.3f}, expected ~3.90")

    def test_k2_mean_episodes_per_year(self):
        mean = sum(self.k2_ep_counts) / len(self.k2_ep_counts)
        self.assertAlmostEqual(mean, 4.90, delta=0.15,
            msg=f"K2 mean episodes/year = {mean:.3f}, expected ~4.90")

    # --- Category shares ---

    def _shares(self, src):
        c = self.cat_counts[src]
        total = c["early"] + c["ontime"] + c["late"]
        return (c["early"] / total, c["ontime"] / total, c["late"] / total)

    def _assert_shares(self, src, true_early, true_ontime, true_late):
        e, o, l = self._shares(src)
        self.assertAlmostEqual(e, true_early,  delta=0.02,
            msg=f"{src} early share {e:.4f} vs truth {true_early}")
        self.assertAlmostEqual(o, true_ontime, delta=0.02,
            msg=f"{src} ontime share {o:.4f} vs truth {true_ontime}")
        self.assertAlmostEqual(l, true_late,   delta=0.02,
            msg=f"{src} late share {l:.4f} vs truth {true_late}")

    def test_of01_category_shares(self):
        self._assert_shares("OF01", OF01_P_EARLY, OF01_P_ONTIME, OF01_P_LATE)

    def test_of02_category_shares(self):
        self._assert_shares("OF02", OF02_P_EARLY, OF02_P_ONTIME, OF02_P_LATE)

    def test_ln01_category_shares(self):
        self._assert_shares("LN01", LN_P_EARLY, LN_P_ONTIME, LN_P_LATE)

    def test_ln02_category_shares(self):
        self._assert_shares("LN02", LN_P_EARLY, LN_P_ONTIME, LN_P_LATE)

    # --- Mean size (of non-zero delays) ---

    def test_of01_mean_size(self):
        mean = self.size_sums["OF01"] / self.size_non0["OF01"]
        self.assertAlmostEqual(mean, OF01_MEAN_SIZE, delta=0.05,
            msg=f"OF01 mean size {mean:.4f} vs {OF01_MEAN_SIZE}")

    def test_of02_mean_size(self):
        mean = self.size_sums["OF02"] / self.size_non0["OF02"]
        self.assertAlmostEqual(mean, OF02_MEAN_SIZE, delta=0.05,
            msg=f"OF02 mean size {mean:.4f} vs {OF02_MEAN_SIZE}")

    def test_ln01_mean_size(self):
        mean = self.size_sums["LN01"] / self.size_non0["LN01"]
        self.assertAlmostEqual(mean, LN_MEAN_SIZE, delta=0.05,
            msg=f"LN01 mean size {mean:.4f} vs {LN_MEAN_SIZE}")

    def test_ln02_mean_size(self):
        mean = self.size_sums["LN02"] / self.size_non0["LN02"]
        self.assertAlmostEqual(mean, LN_MEAN_SIZE, delta=0.05,
            msg=f"LN02 mean size {mean:.4f} vs {LN_MEAN_SIZE}")

    # --- Mean severity ---

    def test_k1_mean_severity(self):
        mean = self.sev_sums["K1"] / self.sev_counts["K1"]
        self.assertAlmostEqual(mean, K1_SEV_MEAN, delta=0.10,
            msg=f"K1 mean severity {mean:.4f} vs {K1_SEV_MEAN}")

    def test_k2_mean_severity(self):
        mean = self.sev_sums["K2"] / self.sev_counts["K2"]
        self.assertAlmostEqual(mean, K2_SEV_MEAN, delta=0.10,
            msg=f"K2 mean severity {mean:.4f} vs {K2_SEV_MEAN}")


# ---------------------------------------------------------------------------
# 6. Committed demo files match a fresh run with seed 20261109
# ---------------------------------------------------------------------------

class TestDemoFilesMatch(unittest.TestCase):

    def test_demo_files_match_fresh_run(self):
        """The committed demo history must equal a fresh generate_history run."""
        demo_ships, demo_eps = _read_demo()
        ships, eps, _ = _run_in_tmp(DEMO_SEED)

        self.assertEqual(demo_ships, ships,
            "shipments.csv differs from a fresh run with seed 20261109")
        self.assertEqual(demo_eps, eps,
            "episodes.csv differs from a fresh run with seed 20261109")


# ---------------------------------------------------------------------------
# 7. closed_days.csv override: closed Monday never appears in biz-day dates
# ---------------------------------------------------------------------------

class TestClosedDayOverride(unittest.TestCase):
    """A temp copy of data/ with closed_days.csv marking 2026-03-02 (Monday)
    as closed must produce a history where no business-day source date falls
    on that day."""

    CLOSED_DATE = date(2026, 3, 2)   # Monday — would normally be open

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        tmp = pathlib.Path(cls._tmpdir)

        # Copy the whole data directory tree (excluding data/history output files)
        shutil.copytree(DATA_DIR, tmp / "data", dirs_exist_ok=True)

        # Write closed_days.csv marking 2026-03-02 as closed
        closed_csv = tmp / "data" / "closed_days.csv"
        with closed_csv.open("w", newline="", encoding="utf-8") as fh:
            fh.write("date,closed\n")
            fh.write(f"{cls.CLOSED_DATE.isoformat()},1\n")

        out = tmp / "out"
        generate_history(tmp / "data", out, DEMO_SEED)

        cls.ships = []
        with (out / "shipments.csv").open(encoding="utf-8", newline="") as fh:
            cls.ships = list(csv.DictReader(fh))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_closed_monday_not_in_biz_source_dates(self):
        """No business-day source date should equal the overridden closed day."""
        for s in self.ships:
            if s["source_id"] not in BIZ_SOURCES:
                continue
            ship = date.fromisoformat(s["ship_date"])
            prom = date.fromisoformat(s["promised_date"])
            self.assertNotEqual(ship, self.CLOSED_DATE,
                f"{s['shipment_id']} ship_date fell on closed day {self.CLOSED_DATE}")
            self.assertNotEqual(prom, self.CLOSED_DATE,
                f"{s['shipment_id']} promised_date fell on closed day {self.CLOSED_DATE}")

    def test_closed_monday_not_in_biz_source_receipts(self):
        """Receipt dates of business-day sources should not fall on the closed day."""
        for s in self.ships:
            if s["source_id"] not in BIZ_SOURCES:
                continue
            rcpt = date.fromisoformat(s["receipt_date"])
            self.assertNotEqual(rcpt, self.CLOSED_DATE,
                f"{s['shipment_id']} receipt_date fell on closed day {self.CLOSED_DATE}")


# ---------------------------------------------------------------------------
# 8. causes.csv validation errors
# ---------------------------------------------------------------------------

class TestCausesValidation(unittest.TestCase):
    """_load_causes raises ValueError with the filename for bad causes.csv."""

    @classmethod
    def setUpClass(cls):
        # Load a real db once; validation tests only need offers, lanes, POs
        cls.db = load_all(DATA_DIR)

    def _write_causes(self, tmp: pathlib.Path, content: str) -> pathlib.Path:
        hist = tmp / "history"
        hist.mkdir(parents=True, exist_ok=True)
        p = hist / "causes.csv"
        p.write_text(content, encoding="utf-8")
        return tmp

    def _assert_raises(self, content: str, fragment: str = "causes.csv"):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            self._write_causes(td, content)
            with self.assertRaises(ValueError) as ctx:
                _load_causes(td, self.db)
            self.assertIn(fragment, str(ctx.exception))

    def test_bad_header_raises(self):
        """Wrong header raises ValueError naming the file."""
        content = "cause_id,day_unit,target_type\nK1,business,offer,OF02\n"
        self._assert_raises(content)

    def test_invalid_day_unit_raises(self):
        """day_unit 'weekly' raises ValueError."""
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,weekly,offer,OF02\n"
        )
        self._assert_raises(content)

    def test_conflicting_day_unit_same_cause_raises(self):
        """K1 listed with two different day_units raises ValueError."""
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,purchase_order,PO01\n"
            "K1,calendar,offer,OF02\n"
        )
        self._assert_raises(content)

    def test_unknown_lane_raises(self):
        """Lane LN99 not in transfer_lanes raises ValueError."""
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K2,calendar,lane,LN99\n"
        )
        self._assert_raises(content)

    def test_unknown_offer_raises(self):
        """Offer OF99 not in supplier_offers raises ValueError."""
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,offer,OF99\n"
        )
        self._assert_raises(content)

    def test_unknown_purchase_order_raises(self):
        """PO99 not in purchase_orders raises ValueError."""
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,purchase_order,PO99\n"
        )
        self._assert_raises(content)


if __name__ == "__main__":
    import unittest
    unittest.main()
