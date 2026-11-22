"""Tests for montecarlo.sample and montecarlo.run (stage 2, step 4b part 3)."""

import csv
import json
import pathlib
import random
import shutil
import tempfile
import unittest
from datetime import date, timedelta

from engine.loader import load_all
from montecarlo.estimate import estimate
from engine.episodes import derived_tags
from engine.loader import load_all as _load_all_for_tags
from montecarlo.sample import lhs_uniforms, _inv_own_delay, _inv_severity, sample_worlds
from montecarlo.run import run

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# 1. Inverse CDF point values
# ---------------------------------------------------------------------------

class TestInverseCDF(unittest.TestCase):
    """Check _inv_own_delay and _inv_severity against hand-computed values."""

    # Parameters: pe=0.2, po=0.3, pl=0.5, theta_e=0.5, theta_l=0.5
    PE, PO, PL = 0.2, 0.3, 0.5
    TE, TL     = 0.5, 0.5

    def _e(self, u):
        return _inv_own_delay(u, self.PE, self.PO, self.PL, self.TE, self.TL)

    def test_early_u001(self):  self.assertEqual(self._e(0.01), -5)
    def test_early_u004(self):  self.assertEqual(self._e(0.04), -3)
    def test_early_u006(self):  self.assertEqual(self._e(0.06), -2)
    def test_early_u015(self):  self.assertEqual(self._e(0.15), -1)
    def test_ontime_u030(self): self.assertEqual(self._e(0.30),  0)
    def test_late_u055(self):   self.assertEqual(self._e(0.55),  1)
    def test_late_u080(self):   self.assertEqual(self._e(0.80),  2)
    def test_late_u090(self):   self.assertEqual(self._e(0.90),  3)
    def test_late_u099(self):   self.assertEqual(self._e(0.99),  6)

    def test_severity_u040(self): self.assertEqual(_inv_severity(0.4,  0.5), 1)
    def test_severity_u050(self): self.assertEqual(_inv_severity(0.5,  0.5), 2)
    def test_severity_u080(self): self.assertEqual(_inv_severity(0.8,  0.5), 3)
    def test_severity_u090(self): self.assertEqual(_inv_severity(0.9,  0.5), 4)


# ---------------------------------------------------------------------------
# 2. lhs_uniforms: every column has exactly one value per stratum
# ---------------------------------------------------------------------------

class TestLhsUniforms(unittest.TestCase):

    def _check_strata(self, n, d, seed=0):
        rng  = random.Random(seed)
        rows = lhs_uniforms(n, d, rng)
        self.assertEqual(len(rows), n)
        self.assertEqual(len(rows[0]), d)
        for j in range(d):
            col = [rows[i][j] for i in range(n)]
            # Each stratum [k/n, (k+1)/n) must contain exactly one value
            strata = [0] * n
            for v in col:
                self.assertGreaterEqual(v, 0.0)
                self.assertLess(v, 1.0)
                k = int(v * n)
                strata[k] += 1
            for k in range(n):
                self.assertEqual(strata[k], 1,
                    f"column {j}, stratum {k}: count {strata[k]} != 1")

    def test_lhs_5x3(self):   self._check_strata(5, 3)
    def test_lhs_10x8(self):  self._check_strata(10, 8)
    def test_lhs_40x10(self): self._check_strata(40, 10)
    def test_lhs_1x1(self):   self._check_strata(1, 1)


# ---------------------------------------------------------------------------
# 3. run(M=50, N=40) on demo data: load with load_all, draws total N
# ---------------------------------------------------------------------------

class TestRunBasic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = pathlib.Path(tempfile.mkdtemp())
        # Temp data dir for load_all tests (need a copy to swap worlds.csv)
        shutil.copytree(DATA_DIR, cls._tmpdir / "data", dirs_exist_ok=True)
        cls._out1 = cls._tmpdir / "out1"
        cls._record1 = run(DATA_DIR, cls._out1, M=50, N=40, seed=42)
        # Second run with same seed for reproducibility test
        cls._out2 = cls._tmpdir / "out2"
        cls._record2 = run(DATA_DIR, cls._out2, M=50, N=40, seed=42)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _worlds(self, out):
        with (out / "worlds.csv").open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def test_worlds_csv_exists(self):
        self.assertTrue((self._out1 / "worlds.csv").exists())

    def test_run_record_json_exists(self):
        self.assertTrue((self._out1 / "run_record.json").exists())

    def test_same_seed_identical_worlds(self):
        """Same seed produces identical worlds.csv."""
        w1 = self._worlds(self._out1)
        w2 = self._worlds(self._out2)
        self.assertEqual(w1, w2)

    def test_every_draw_totals_N(self):
        """Sum of weights for each draw equals N=40."""
        worlds = self._worlds(self._out1)
        draw_totals: dict = {}
        for row in worlds:
            d = int(row["draw"])
            draw_totals[d] = draw_totals.get(d, 0) + int(row["weight"])
        self.assertEqual(len(draw_totals), 50)   # M=50 draws
        for d, total in draw_totals.items():
            self.assertEqual(total, 40, f"draw {d} total {total} != 40")

    def test_load_all_accepts_worlds(self):
        """load_all succeeds when worlds.csv is replaced by run output."""
        # Copy worlds.csv into the temp data dir and load
        src = self._out1 / "worlds.csv"
        dst = self._tmpdir / "data" / "worlds.csv"
        shutil.copy(src, dst)
        db = load_all(self._tmpdir / "data")
        self.assertIsNotNone(db["worlds"])
        self.assertGreater(len(db["worlds"]), 0)

    def test_po01_receipts_are_business_days(self):
        """Every PO01 receipt_date in worlds.csv is a business day."""
        from engine.business_calendar import BusinessCalendar
        cal    = BusinessCalendar()
        worlds = self._worlds(self._out1)
        # Find the PO01 receipt_date column
        col = "purchase_order.PO01.receipt_date"
        self.assertIn(col, worlds[0])
        for row in worlds:
            d = date.fromisoformat(row[col])
            self.assertTrue(cal.is_business_day(d),
                f"PO01 receipt {d} is not a business day")

    def test_po01_receipts_at_least_planned(self):
        """Every PO01 receipt_date >= 2026-11-12 (planned = 2026-11-11, next biz day)."""
        # planned_receipt_date is 2026-11-11 (Veterans Day, closed) so next biz = 2026-11-12
        from engine.business_calendar import BusinessCalendar
        cal     = BusinessCalendar()
        db      = load_all(DATA_DIR)
        planned = db["purchase_orders"]["PO01"]["planned_receipt_date"]
        floor   = cal.next_business_day(planned)
        worlds  = self._worlds(self._out1)
        col     = "purchase_order.PO01.receipt_date"
        for row in worlds:
            d = date.fromisoformat(row[col])
            self.assertGreaterEqual(d, floor,
                f"PO01 receipt {d} is before planned floor {floor}")


# ---------------------------------------------------------------------------
# 4. Tag shares over M=400, N=100
# ---------------------------------------------------------------------------

class TestTagShares(unittest.TestCase):
    """Pooled shares across all worlds.csv rows should be near p_active."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = pathlib.Path(tempfile.mkdtemp())
        cls._out = cls._tmpdir / "out"
        cls._record = run(DATA_DIR, cls._out, M=400, N=100, seed=99)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _derived_tag_share(self, cause_id):
        dst = self._tmpdir / f"data_{cause_id}"
        dst.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(DATA_DIR, dst, dirs_exist_ok=True)
        shutil.copy(self._out / "worlds.csv", dst / "worlds.csv")
        db2 = _load_all_for_tags(dst)
        total = sum(w["weight"] for w in db2["worlds"])
        active = sum(w["weight"] for w in db2["worlds"]
                     if derived_tags(w, db2).get(cause_id, 0) == 1)
        return active / total

    def test_k1_tag_share(self):
        """K1 derived-tag share ≈ 0.0948 ± 0.01."""
        share = self._derived_tag_share("K1")
        self.assertAlmostEqual(share, 0.0948, delta=0.01,
            msg=f"K1 derived tag share {share:.4f}")

    def test_k2_tag_share(self):
        """K2 derived-tag share ≈ 0.1067 ± 0.01."""
        share = self._derived_tag_share("K2")
        self.assertAlmostEqual(share, 0.1067, delta=0.01,
            msg=f"K2 derived tag share {share:.4f}")

    def test_of02_delay_share_given_k1_zero(self):
        """Unconditional share of OF02 own deviation=0 ≈ 0.444 ± 0.02."""
        with (self._out / "worlds.csv").open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        total = sum(int(r["weight"]) for r in rows)
        zero_delay = sum(int(r["weight"]) for r in rows
                         if r["offer.OF02.delay_business_days"] == "0")
        share = zero_delay / total
        self.assertAlmostEqual(share, 0.444, delta=0.02,
            msg=f"OF02 delay=0 unconditional share: {share:.4f}")

    def test_ln02_lead_share_given_k2_zero(self):
        """Unconditional share of LN02 delay_days=0 ≈ 0.538 ± 0.02."""
        with (self._out / "worlds.csv").open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        total = sum(int(r["weight"]) for r in rows)
        zero_delay = sum(int(r["weight"]) for r in rows
                         if r["lane.LN02.delay_days"] == "0")
        share = zero_delay / total
        self.assertAlmostEqual(share, 0.538, delta=0.02,
            msg=f"LN02 delay=0 unconditional share: {share:.4f}")


# ---------------------------------------------------------------------------
# 5. LHS vs plain variance comparison
# ---------------------------------------------------------------------------

class TestLhsVsPlain(unittest.TestCase):
    """LHS should give a smaller standard deviation of per-draw mean OF02 delay."""

    def _per_draw_means(self, method, n_reps=100, N=200):
        """Run n_reps independent inner-level samples with fixed draw params.

        Measures the OF02 own deviation only (new dimension layout).
        """
        est = estimate(DATA_DIR)
        db  = load_all(DATA_DIR)
        from montecarlo.sample import _draw_parameters, lhs_uniforms, _compute_slot_count
        from engine.loader import load_all as _la
        # Fix one parameter draw
        rng_params = random.Random(0)
        draw_params = _draw_parameters(est, rng_params)

        cause_ids = list(est["causes"].keys())
        cause_horizons = db.get("cause_horizons") or {}
        n_vars = len(est["variables"])
        d = n_vars + sum(
            3 * _compute_slot_count(
                est["causes"][cid]["rate_shape"],
                est["causes"][cid]["T_free_days"],
                (cause_horizons[cid]["H"] - db["DAY0"]).days + 1
                if cid in cause_horizons else 0,
                est["causes"][cid].get("open_episode") is not None,
            )
            for cid in cause_ids
        )

        var_keys = list(est["variables"].keys())
        vi_of02 = next(vi for vi, vkey in enumerate(var_keys) if vkey == "offer.OF02")
        vp = draw_params["variables"]["offer.OF02"]

        means = []
        for rep in range(n_reps):
            rng_inner = random.Random(rep + 1000)
            if method == "lhs":
                uniforms = lhs_uniforms(N, d, rng_inner)
            else:
                uniforms = [[rng_inner.random() for _ in range(d)]
                            for _ in range(N)]

            delays = []
            for row_u in uniforms:
                E = _inv_own_delay(row_u[vi_of02], vp["pe"], vp["po"], vp["pl"],
                                   vp["theta_e"], vp["theta_l"])
                delays.append(E)
            means.append(sum(delays) / len(delays))
        return means

    def test_lhs_has_lower_variance_than_plain(self):
        """Standard deviation of per-draw mean with LHS < 0.7 * that with plain."""
        import math
        lhs_means   = self._per_draw_means("lhs")
        plain_means = self._per_draw_means("plain")
        std_lhs   = math.sqrt(sum((x - sum(lhs_means)/len(lhs_means))**2
                                  for x in lhs_means) / len(lhs_means))
        std_plain = math.sqrt(sum((x - sum(plain_means)/len(plain_means))**2
                                  for x in plain_means) / len(plain_means))
        ratio = std_lhs / std_plain if std_plain > 0 else 0
        self.assertLess(ratio, 0.7,
            f"LHS std {std_lhs:.4f} / plain std {std_plain:.4f} = {ratio:.3f} >= 0.7")


# ---------------------------------------------------------------------------
# 6. out_dir inside data_dir raises ValueError
# ---------------------------------------------------------------------------

class TestOutDirInsideDataRaises(unittest.TestCase):

    def test_out_inside_data_raises(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            shutil.copytree(DATA_DIR, td / "data", dirs_exist_ok=True)
            with self.assertRaises(ValueError) as ctx:
                run(td / "data", td / "data" / "runs", M=2, N=2)
            self.assertIn("inside data_dir", str(ctx.exception))


# ---------------------------------------------------------------------------
# 7. Demo run: M=1000, N=200, seed=20261109, lhs
# ---------------------------------------------------------------------------

class TestDemoRun(unittest.TestCase):
    """Full demo run against committed data/history/ — checks exact meta values."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = pathlib.Path(tempfile.mkdtemp())
        cls._out = cls._tmpdir / "out"
        cls._record = run(DATA_DIR, cls._out, M=1000, N=200, seed=20261109,
                          method="lhs")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_cut_count(self):
        """Demo run: cut_count == 0."""
        self.assertEqual(self._record["cut_count"], 0)

    def test_distinct_worlds(self):
        """Demo run: distinct_worlds == 44006."""
        self.assertEqual(self._record["distinct_worlds"], 44006)

    def test_rows(self):
        """Demo run: rows == 156609."""
        self.assertEqual(self._record["rows"], 156609)

    def test_raised_count(self):
        """Demo run: raised_count == 12422."""
        self.assertEqual(self._record["raised_count"], 12422)

    def test_load_all_accepts_worlds(self):
        """load_all accepts the demo worlds.csv."""
        dst_data = self._tmpdir / "data"
        shutil.copytree(DATA_DIR, dst_data, dirs_exist_ok=True)
        shutil.copy(self._out / "worlds.csv", dst_data / "worlds.csv")
        db = load_all(dst_data)
        self.assertIsNotNone(db["worlds"])
        self.assertGreater(len(db["worlds"]), 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
