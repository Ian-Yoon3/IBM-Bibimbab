"""Tests for montecarlo/grid.py, montecarlo/sample.py extensions, engine/runs.py grid support.

Build configuration: N=5, pilot_M=4, max_M=8, target_se=0.5 (tiny sizes).
One build in setUpClass reused by most tests.
Temporary folders only. Never writes into data/.
"""

import csv
import json
import math
import pathlib
import shutil
import tempfile
import unittest

_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def _copy_data(dest):
    shutil.copytree(_DATA_DIR, dest, dirs_exist_ok=True)


# ---------------------------------------------------------------------------
# Test 1 & 2: sample_worlds with rate_scale/rate_fixed/slot_counts overrides
# ---------------------------------------------------------------------------

class TestSampleOverrides(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from engine.loader import load_all
        from montecarlo.estimate import estimate
        from montecarlo.sample import sample_worlds

        cls.db = load_all(_DATA_DIR)
        cls.est = estimate(_DATA_DIR)
        cls.M = 5
        cls.N = 5
        cls.seed = 42

        # Default call
        cls.worlds_default, cls.meta_default = sample_worlds(
            cls.est, cls.db, cls.M, cls.N, cls.seed, "lhs"
        )

        # Compute default slot counts for reference
        from montecarlo.sample import _compute_slot_count
        db = cls.db
        est = cls.est
        day0 = db["DAY0"]
        cause_horizons = db.get("cause_horizons") or {}
        cls.default_slot_counts = {}
        for cid, cp in est["causes"].items():
            H_k = cause_horizons.get(cid, {}).get("H")
            D_k = (H_k - day0).days + 1 if H_k else 0
            has_open = cp.get("open_episode") is not None
            cls.default_slot_counts[cid] = _compute_slot_count(
                cp["rate_shape"], cp["T_free_days"], D_k, has_open
            )

    def test_1_rate_scale_1_slot_counts_default_identical(self):
        """rate_scale=1.0, slot_counts=default gives byte-identical output."""
        from montecarlo.sample import sample_worlds
        worlds_scaled, meta_scaled = sample_worlds(
            self.est, self.db, self.M, self.N, self.seed, "lhs",
            rate_scale=1.0,
            slot_counts=self.default_slot_counts,
        )
        self.assertEqual(len(worlds_scaled), len(self.worlds_default))
        for w1, w2 in zip(self.worlds_default, worlds_scaled):
            self.assertEqual(w1, w2)
        self.assertEqual(meta_scaled["slot_counts"], self.meta_default["slot_counts"])

    def test_2_rate_fixed_K1_zero_ep_cells_none(self):
        """rate_fixed={"K1": 0.0}: every cause.K1.ep*_ cell is "none"."""
        from montecarlo.sample import sample_worlds
        cause_ids = list(self.est["causes"].keys())
        # We need K1 to be in the causes
        if "K1" not in cause_ids:
            self.skipTest("K1 not in causes")

        worlds_fixed, meta_fixed = sample_worlds(
            self.est, self.db, self.M, self.N, self.seed, "lhs",
            rate_fixed={"K1": 0.0},
        )
        # Every K1 episode cell should be "none" (lam=0 means no events)
        k1_ep_cols = [
            col for col in worlds_fixed[0].keys()
            if col.startswith("cause.K1.ep")
        ]
        for w in worlds_fixed:
            for col in k1_ep_cols:
                self.assertEqual(w[col], "none",
                    f"Expected 'none' for K1 episode col {col}, got {w[col]!r}")

        # K2 and offer/lane cols should equal the default call
        # (same rng stream for non-K1 dims)
        k2_ep_cols = [col for col in worlds_fixed[0].keys()
                      if col.startswith("cause.K2.ep")]
        # Same slot counts for K2 -> same ep cols present
        default_dict = {w["world_id"]: w for w in self.worlds_default}
        # Can't compare world_ids (they're different groupings), but we can
        # check that K2 slot count is the same
        self.assertEqual(
            meta_fixed["slot_counts"].get("K2"),
            self.meta_default["slot_counts"].get("K2"),
        )

    def test_3_rate_fixed_and_rate_scale_raises(self):
        """rate_fixed and rate_scale together -> ValueError."""
        from montecarlo.sample import sample_worlds
        with self.assertRaises(ValueError) as ctx:
            sample_worlds(
                self.est, self.db, 2, 2, 0, "lhs",
                rate_fixed={"K1": 0.0},
                rate_scale=1.0,
            )
        self.assertIn("cannot be used together", str(ctx.exception))

    def test_3b_negative_rate_fixed_raises(self):
        """Negative value in rate_fixed -> ValueError."""
        from montecarlo.sample import sample_worlds
        cause_ids = list(self.est["causes"].keys())
        if not cause_ids:
            self.skipTest("no causes")
        cid = cause_ids[0]
        with self.assertRaises(ValueError):
            sample_worlds(
                self.est, self.db, 2, 2, 0, "lhs",
                rate_fixed={cid: -1.0},
            )

    def test_3c_nan_rate_fixed_raises(self):
        """NaN in rate_fixed -> ValueError."""
        from montecarlo.sample import sample_worlds
        cause_ids = list(self.est["causes"].keys())
        if not cause_ids:
            self.skipTest("no causes")
        cid = cause_ids[0]
        with self.assertRaises(ValueError):
            sample_worlds(
                self.est, self.db, 2, 2, 0, "lhs",
                rate_fixed={cid: float("nan")},
            )

    def test_3d_unknown_cause_rate_fixed_raises(self):
        """Unknown cause in rate_fixed -> ValueError."""
        from montecarlo.sample import sample_worlds
        with self.assertRaises(ValueError):
            sample_worlds(
                self.est, self.db, 2, 2, 0, "lhs",
                rate_fixed={"NONEXISTENT_CAUSE_XYZ": 0.0},
            )

    def test_3e_negative_rate_scale_raises(self):
        """Negative rate_scale -> ValueError."""
        from montecarlo.sample import sample_worlds
        with self.assertRaises(ValueError):
            sample_worlds(
                self.est, self.db, 2, 2, 0, "lhs",
                rate_scale=-0.1,
            )


# ---------------------------------------------------------------------------
# Test 4: slot_count_fixed_rate and slot_count_posterior
# ---------------------------------------------------------------------------

class TestSlotCountHelpers(unittest.TestCase):

    def test_slot_count_fixed_rate_p01_D9(self):
        """p=0.1, D=9: lam = -ln(0.9)/9; expected count 4."""
        from montecarlo.sample import slot_count_fixed_rate
        p = 0.1
        D = 9
        lam = -math.log(1 - p) / D
        result = slot_count_fixed_rate(lam, D, False)
        self.assertEqual(result, 4)

    def test_slot_count_fixed_rate_p05_D9(self):
        """p=0.5, D=9: expected count 7."""
        from montecarlo.sample import slot_count_fixed_rate
        p = 0.5
        D = 9
        lam = -math.log(1 - p) / D
        result = slot_count_fixed_rate(lam, D, False)
        self.assertEqual(result, 7)

    def test_slot_count_fixed_rate_p09_D9(self):
        """p=0.9, D=9: expected count 12."""
        from montecarlo.sample import slot_count_fixed_rate
        p = 0.9
        D = 9
        lam = -math.log(1 - p) / D
        result = slot_count_fixed_rate(lam, D, False)
        self.assertEqual(result, 12)

    def test_slot_count_fixed_rate_p099_D9(self):
        """p=0.99, D=9: expected count 18."""
        from montecarlo.sample import slot_count_fixed_rate
        p = 0.99
        D = 9
        lam = -math.log(1 - p) / D
        result = slot_count_fixed_rate(lam, D, False)
        self.assertEqual(result, 18)

    def test_slot_count_fixed_rate_zero_lam(self):
        """lam=0 -> 0."""
        from montecarlo.sample import slot_count_fixed_rate
        self.assertEqual(slot_count_fixed_rate(0.0, 9, False), 0)

    def test_slot_count_fixed_rate_zero_lam_has_open(self):
        """lam=0 with has_open -> 1."""
        from montecarlo.sample import slot_count_fixed_rate
        self.assertEqual(slot_count_fixed_rate(0.0, 9, True), 1)

    def test_slot_count_posterior_case1(self):
        """slot_count_posterior(4, 357, 9, False) == 4."""
        from montecarlo.sample import slot_count_posterior
        self.assertEqual(slot_count_posterior(4, 357, 9, False), 4)

    def test_slot_count_posterior_case2(self):
        """slot_count_posterior(8, 352, 5, False) == 4."""
        from montecarlo.sample import slot_count_posterior
        self.assertEqual(slot_count_posterior(8, 352, 5, False), 4)

    def test_slot_count_posterior_scale_zero(self):
        """scale=0 -> 0."""
        from montecarlo.sample import slot_count_posterior
        self.assertEqual(slot_count_posterior(4, 357, 9, False, scale=0.0), 0)

    def test_slot_count_posterior_scale_1_equals_compute(self):
        """slot_count_posterior(..., scale=1.0) == _compute_slot_count(...)."""
        from montecarlo.sample import slot_count_posterior, _compute_slot_count
        args = (4, 357, 9, False)
        self.assertEqual(slot_count_posterior(*args, scale=1.0),
                         _compute_slot_count(*args))


# ---------------------------------------------------------------------------
# Test 5: Prefix property
# ---------------------------------------------------------------------------

class TestSamplePrefix(unittest.TestCase):

    def test_prefix(self):
        """Rows of sample_worlds(M=6) with draw < 3 equal sample_worlds(M=3)."""
        from engine.loader import load_all
        from montecarlo.estimate import estimate
        from montecarlo.sample import sample_worlds

        db = load_all(_DATA_DIR)
        est = estimate(_DATA_DIR)
        seed = 77
        N = 5

        worlds6, _ = sample_worlds(est, db, 6, N, seed, "lhs")
        worlds3, _ = sample_worlds(est, db, 3, N, seed, "lhs")

        # Rows from worlds6 whose draw < 3
        rows6_early = [w for w in worlds6 if w["draw"] < 3]
        # Compare values (excluding world_id, which will differ due to numbering)
        self.assertEqual(len(rows6_early), len(worlds3))
        for w6, w3 in zip(rows6_early, worlds3):
            self.assertEqual(w6["draw"], w3["draw"])
            self.assertEqual(w6["weight"], w3["weight"])
            # Compare all value columns
            for col in w3:
                if col in ("world_id",):
                    continue
                self.assertEqual(w6[col], w3[col],
                    f"Mismatch in column {col}: {w6[col]!r} vs {w3[col]!r}")


# ---------------------------------------------------------------------------
# Test 6: find_crossings
# ---------------------------------------------------------------------------

class TestFindCrossings(unittest.TestCase):

    def test_crossing_linear(self):
        """diff_at(p) = 0.43 - p -> one bracket around 0.43."""
        from montecarlo.grid import find_crossings, P_GRID
        def diff_at(p):
            return 0.43 - p
        result = find_crossings(diff_at, P_GRID)
        self.assertEqual(len(result), 1)
        p_lo, p_hi, d_lo, d_hi = result[0]
        self.assertAlmostEqual(p_lo, 0.425, delta=0.02)
        self.assertAlmostEqual(p_hi, 0.4375, delta=0.02)

    def test_no_crossing_always_positive(self):
        """diff_at(p) = 1 - p -> no crossing (stays positive up to 0.99)."""
        from montecarlo.grid import find_crossings, P_GRID
        def diff_at(p):
            return 1.0 - p
        result = find_crossings(diff_at, P_GRID)
        self.assertEqual(result, [])

    def test_exact_zero_at_grid_point(self):
        """diff_at(p) = 0.5 - p -> exact zero at p=0.5."""
        from montecarlo.grid import find_crossings, P_GRID
        def diff_at(p):
            return 0.5 - p
        result = find_crossings(diff_at, P_GRID)
        # Should have exactly one crossing with p_lo == p_hi == 0.5
        self.assertGreaterEqual(len(result), 1)
        found = any(abs(lo - 0.5) < 1e-9 and abs(hi - 0.5) < 1e-9
                    for lo, hi, _dl, _dh in result)
        self.assertTrue(found, f"No exact crossing at 0.5 found in {result}")


# ---------------------------------------------------------------------------
# Shared build for tests 7-12
# ---------------------------------------------------------------------------

class TestGridBuild(unittest.TestCase):
    """One setUpClass build (N=5, pilot_M=4, max_M=8, target_se=0.5) reused."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        cls._base = pathlib.Path(cls._tmp_dir)

        # Copy data
        cls.data_copy = cls._base / "data"
        _copy_data(cls.data_copy)

        # Build run with grid
        from montecarlo.run import build_run
        cls.run_dir = cls._base / "runs" / "main"
        cls.record = build_run(
            cls.data_copy, cls.run_dir,
            M=5, N=5, seed=42, method="lhs",
            grid=True,
            target_se=0.5,
            pilot_M=4,
            max_M=8,
        )

        # Load the grid
        with (cls.run_dir / "grid.json").open(encoding="utf-8") as fh:
            cls.grid = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def test_7a_families_order(self):
        """Families: K1, K2, scale in that order (demo data)."""
        fam_names = [f["family"] for f in self.grid["families"]]
        # At minimum K1, K2, scale should be present
        self.assertIn("K1", fam_names)
        self.assertIn("K2", fam_names)
        self.assertIn("scale", fam_names)
        # Order: K1 before K2 before scale
        idx_k1 = fam_names.index("K1")
        idx_k2 = fam_names.index("K2")
        idx_scale = fam_names.index("scale")
        self.assertLess(idx_k1, idx_k2)
        self.assertLess(idx_k2, idx_scale)

    def test_7b_reference_cause_K2(self):
        """Scale family reference_cause == 'K2' on demo data."""
        scale_fam = next(f for f in self.grid["families"] if f["family"] == "scale")
        self.assertEqual(scale_fam["reference_cause"], "K2")

    def test_7c_each_family_has_11_p_grid_points(self):
        """Each family has at least 11 'grid' kind points (the P_GRID points)."""
        from montecarlo.grid import P_GRID
        for fam in self.grid["families"]:
            grid_pts = [pt for pt in fam["points"] if pt.get("kind") == "grid"]
            self.assertEqual(len(grid_pts), len(P_GRID),
                f"Family {fam['family']!r} has {len(grid_pts)} grid points, expected {len(P_GRID)}")

    def test_7d_scale_has_m1_point(self):
        """Scale family has exactly one m1 point."""
        scale_fam = next(f for f in self.grid["families"] if f["family"] == "scale")
        m1_pts = [pt for pt in scale_fam["points"] if pt.get("kind") == "m1"]
        self.assertEqual(len(m1_pts), 1)

    def test_7e_K1_p0_worlds_with_episode_zero(self):
        """K1 family at p=0: worlds_with_episode["K1"] == 0."""
        k1_fam = next(f for f in self.grid["families"] if f["family"] == "K1")
        p0_pt = next((pt for pt in k1_fam["points"] if pt["p"] == 0.0), None)
        self.assertIsNotNone(p0_pt)
        wwe = p0_pt["worlds_with_episode"]
        self.assertEqual(wwe.get("K1", None), 0.0,
            f"worlds_with_episode['K1'] at p=0 should be 0, got {wwe.get('K1')}")

    def test_7f_scale_p0_worlds_with_episode_zero(self):
        """Scale family at p=0: worlds_with_episode all zero."""
        scale_fam = next(f for f in self.grid["families"] if f["family"] == "scale")
        p0_pt = next((pt for pt in scale_fam["points"]
                      if pt.get("kind") == "grid" and pt["p"] == 0.0), None)
        self.assertIsNotNone(p0_pt)
        wwe = p0_pt["worlds_with_episode"]
        for cid, share in wwe.items():
            self.assertEqual(share, 0.0,
                f"Scale family p=0: worlds_with_episode[{cid!r}] should be 0, got {share}")

    def test_7g_K1_slot_counts_eq_18(self):
        """K1 family slot_counts["K1"] == 18 (p=0.99 max)."""
        k1_fam = next(f for f in self.grid["families"] if f["family"] == "K1")
        sc = k1_fam["slot_counts"]
        self.assertEqual(sc.get("K1"), 18,
            f"K1 family slot_counts['K1'] should be 18, got {sc.get('K1')}")

    def test_8_cache_equality(self):
        """build_grid with use_cache=True and use_cache=False give byte-identical grid.json."""
        from montecarlo.grid import build_grid
        from montecarlo.run import build_run

        # Build a second run folder (no grid) for use_cache=False test
        run_dir_nc = self._base / "runs" / "nc"
        build_run(self.data_copy, run_dir_nc,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)

        # Build with use_cache=False
        build_grid(self.data_copy, run_dir_nc, N=5, seed=42, method="lhs",
                   target_se=0.5, pilot_M=4, max_M=8,
                   families=["K2"], use_cache=False)
        grid_nc_bytes = (run_dir_nc / "grid.json").read_bytes()

        # Build another run folder and use use_cache=True
        run_dir_c = self._base / "runs" / "c"
        build_run(self.data_copy, run_dir_c,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)
        build_grid(self.data_copy, run_dir_c, N=5, seed=42, method="lhs",
                   target_se=0.5, pilot_M=4, max_M=8,
                   families=["K2"], use_cache=True)
        grid_c_bytes = (run_dir_c / "grid.json").read_bytes()

        self.assertEqual(grid_nc_bytes, grid_c_bytes,
            "grid.json with use_cache=True and use_cache=False should be byte-identical")

    def test_9a_check_run_passes_with_grid(self):
        """check_run passes on a run built with grid=True."""
        import engine.runs as runs_mod
        fp = runs_mod.check_run(self.run_dir, self.data_copy)
        self.assertIn("grid.json", fp.get("outputs", {}))

    def test_9b_changed_grid_json_fails(self):
        """One changed byte in grid.json -> check_run fails naming grid.json."""
        import engine.runs as runs_mod
        # Work on a copy of the run folder
        run_copy = self._base / "runs" / "copy_9b"
        shutil.copytree(self.run_dir, run_copy)
        try:
            grid_path = run_copy / "grid.json"
            orig = grid_path.read_bytes()
            # Flip one byte
            modified = orig[:10] + bytes([orig[10] ^ 1]) + orig[11:]
            grid_path.write_bytes(modified)
            with self.assertRaises(ValueError) as ctx:
                runs_mod.check_run(run_copy, self.data_copy)
            self.assertIn("grid.json", str(ctx.exception))
        finally:
            shutil.rmtree(run_copy, ignore_errors=True)

    def test_9c_deleted_grid_json_fails(self):
        """grid.json deleted -> check_run fails."""
        import engine.runs as runs_mod
        run_copy = self._base / "runs" / "copy_9c"
        shutil.copytree(self.run_dir, run_copy)
        try:
            (run_copy / "grid.json").unlink()
            with self.assertRaises(ValueError) as ctx:
                runs_mod.check_run(run_copy, self.data_copy)
            self.assertIn("grid.json", str(ctx.exception))
        finally:
            shutil.rmtree(run_copy, ignore_errors=True)

    def test_9d_uncovered_grid_json_fails(self):
        """grid.json not in fingerprint but present -> check_run fails 'not covered'."""
        import engine.runs as runs_mod
        from montecarlo.run import build_run
        # Build a run without grid
        run_no_grid = self._base / "runs" / "no_grid_9d"
        build_run(self.data_copy, run_no_grid,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)
        # Copy grid.json into it
        shutil.copy(self.run_dir / "grid.json", run_no_grid / "grid.json")
        with self.assertRaises(ValueError) as ctx:
            runs_mod.check_run(run_no_grid, self.data_copy)
        msg = str(ctx.exception)
        self.assertIn("not covered", msg)

    def test_10a_no_grid_no_file(self):
        """build_run with grid=False produces no grid.json."""
        from montecarlo.run import build_run
        run_ng = self._base / "runs" / "no_grid_10a"
        build_run(self.data_copy, run_ng,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)
        self.assertFalse((run_ng / "grid.json").exists())
        # check_run passes
        import engine.runs as runs_mod
        fp = runs_mod.check_run(run_ng, self.data_copy)
        self.assertNotIn("grid.json", fp.get("outputs", {}))

    def test_10b_rebuild_without_grid_removes_old(self):
        """Rebuilding a folder that had a grid with grid=False removes the old grid.json."""
        from montecarlo.run import build_run
        run_rb = self._base / "runs" / "rebuild_10b"
        # First build with grid
        build_run(self.data_copy, run_rb,
                  M=5, N=5, seed=42, method="lhs",
                  grid=True, target_se=0.5, pilot_M=4, max_M=8)
        self.assertTrue((run_rb / "grid.json").exists())
        # Rebuild without grid
        build_run(self.data_copy, run_rb,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)
        self.assertFalse((run_rb / "grid.json").exists())
        # check_run passes
        import engine.runs as runs_mod
        fp = runs_mod.check_run(run_rb, self.data_copy)
        self.assertNotIn("grid.json", fp.get("outputs", {}))

    def test_11a_grid_only(self):
        """grid_only on a grid=False run: grid.json appears, fingerprint lists it,
        main output hashes unchanged, check_run passes."""
        from montecarlo.run import build_run, grid_only
        import engine.runs as runs_mod

        run_go = self._base / "runs" / "grid_only_11a"
        build_run(self.data_copy, run_go,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)

        # Capture hashes of main outputs before grid_only
        fp_before_path = run_go / "fingerprint.json"
        with fp_before_path.open() as fh:
            fp_before = json.load(fh)
        hashes_before = {k: v for k, v in fp_before["outputs"].items()
                         if k != "grid.json"}

        grid_only(self.data_copy, run_go,
                  target_se=0.5, pilot_M=4, max_M=8)

        # grid.json now exists
        self.assertTrue((run_go / "grid.json").exists())

        # Fingerprint lists grid.json
        with fp_before_path.open() as fh:
            fp_after = json.load(fh)
        self.assertIn("grid.json", fp_after["outputs"])

        # Main output hashes unchanged
        for k, v in hashes_before.items():
            self.assertEqual(fp_after["outputs"].get(k), v,
                f"Hash changed for {k!r}")

        # check_run passes
        fp = runs_mod.check_run(run_go, self.data_copy)
        self.assertIn("grid.json", fp.get("outputs", {}))

    def test_11b_grid_only_changed_input_raises(self):
        """grid_only after changing an input file -> ValueError naming it."""
        from montecarlo.run import build_run, grid_only

        run_gi = self._base / "runs" / "grid_only_11b"
        data_copy2 = self._base / "data2"
        _copy_data(data_copy2)

        build_run(data_copy2, run_gi,
                  M=5, N=5, seed=42, method="lhs",
                  grid=False)

        # Change an input file
        orders_path = data_copy2 / "orders.csv"
        orig = orders_path.read_bytes()
        try:
            with open(orders_path, "a", encoding="utf-8", newline="") as fh:
                fh.write("SO_FAKE,P01,WH01,2026-11-09,1,2026-11-21,1\n")
            with self.assertRaises(ValueError) as ctx:
                grid_only(data_copy2, run_gi,
                          target_se=0.5, pilot_M=4, max_M=8)
            self.assertIn("orders.csv", str(ctx.exception))
        finally:
            orders_path.write_bytes(orig)
            shutil.rmtree(data_copy2, ignore_errors=True)

    def test_12_m1_check_all_scenarios_present_z_finite_or_null(self):
        """m1_check has an entry for every D01 scenario; z is finite or null."""
        from engine.loader import load_all
        db = load_all(self.data_copy)
        d01_sids = [sid for sid, s in db["scenarios"].items()
                    if s.get("disruption_id", "") == "D01"]

        m1_check = self.grid.get("m1_check", {})

        # Every D01 scenario must have an entry
        for sid in d01_sids:
            self.assertIn(sid, m1_check,
                f"m1_check missing entry for D01 scenario {sid!r}")
            z = m1_check[sid]["z"]
            # z must be finite or null (None in Python / null in JSON)
            # It must NOT be a non-null non-finite float (inf / -inf / nan)
            if z is not None:
                self.assertTrue(math.isfinite(z),
                    f"m1_check[{sid!r}]['z'] = {z} is not finite and not null")

        # At least some entries should be present
        self.assertGreater(len(m1_check), 0, "m1_check should have at least one entry")



# ---------------------------------------------------------------------------
# P5b-2: parallel workers, base-database evaluation, regression tests
# (written without Bob; see the Bob record)
# ---------------------------------------------------------------------------

_TINY = dict(target_se=0.5, pilot_M=4, max_M=8)


class TestGridParallelAndRegressions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from montecarlo.run import build_run
        cls._tmp_dir = tempfile.mkdtemp()
        cls._base = pathlib.Path(cls._tmp_dir)
        cls.data_copy = cls._base / "data"
        _copy_data(cls.data_copy)
        cls.run_dir = cls._base / "runs" / "main"
        build_run(cls.data_copy, cls.run_dir, M=10, N=5, seed=7, grid=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def _copy_run(self, name):
        dst = self._base / "runs" / name
        shutil.copytree(self.run_dir, dst)
        return dst

    def test_parallel_equals_serial(self):
        """grid.json is byte-identical for workers=1 and workers=2."""
        from montecarlo.grid import build_grid
        r1, r2 = self._copy_run("w1"), self._copy_run("w2")
        build_grid(self.data_copy, r1, N=5, seed=7, method="lhs",
                   families=["K1"], workers=1, **_TINY)
        build_grid(self.data_copy, r2, N=5, seed=7, method="lhs",
                   families=["K1"], workers=2, **_TINY)
        self.assertEqual((r1 / "grid.json").read_bytes(),
                         (r2 / "grid.json").read_bytes())

    def test_parallel_without_cache_equals_serial_with_cache(self):
        from montecarlo.grid import build_grid
        r1, r2 = self._copy_run("c1"), self._copy_run("c2")
        build_grid(self.data_copy, r1, N=5, seed=7, method="lhs",
                   families=["K2"], workers=1, use_cache=True, **_TINY)
        build_grid(self.data_copy, r2, N=5, seed=7, method="lhs",
                   families=["K2"], workers=2, use_cache=False, **_TINY)
        self.assertEqual((r1 / "grid.json").read_bytes(),
                         (r2 / "grid.json").read_bytes())

    def test_workers_invalid(self):
        from montecarlo.grid import build_grid
        for bad in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                build_grid(self.data_copy, self._copy_run(f"bad{bad}"), N=5, seed=7,
                           method="lhs", families=["K1"], workers=bad, **_TINY)

    def test_base_db_equals_world_db(self):
        """world_result on the base database equals the database loaded with the
        worlds file (wider SIM_END) for every world of a small run."""
        from engine.loader import load_all
        from engine.worlds import world_result
        d2 = self._base / "data_with_worlds"
        _copy_data(d2)
        shutil.copy(self.run_dir / "worlds.csv", d2 / "worlds.csv")
        dbw, dbb = load_all(d2), load_all(self.data_copy)
        sids = [s for s, x in dbb["scenarios"].items() if x["disruption_id"] == "D01"]
        for w in dbw["worlds"]:
            for sid in sids:
                self.assertEqual(world_result(dbb, "D01", sid, w),
                                 world_result(dbw, "D01", sid, w))

    def test_grid_only_twice_and_failed_check_changes_nothing(self):
        from engine.runs import check_run
        from montecarlo.run import grid_only
        run = self._copy_run("go")
        data = self._base / "data_go"
        _copy_data(data)
        # the copied run was built from data_copy; rebuild it from data_go
        from montecarlo.run import build_run
        build_run(data, run, M=10, N=5, seed=7, grid=False)
        grid_only(data, run, **_TINY)
        check_run(run, data)
        grid_only(data, run, **_TINY)
        check_run(run, data)
        g0 = (run / "grid.json").read_bytes()
        f0 = (run / "fingerprint.json").read_bytes()
        with open(data / "orders.csv", "a", encoding="utf-8", newline="") as fh:
            fh.write("SO_X,P01,WH01,2026-11-09,1,2026-11-21,1\n")
        with self.assertRaises(ValueError) as ctx:
            grid_only(data, run, **_TINY)
        self.assertIn("orders.csv", str(ctx.exception))
        self.assertEqual((run / "grid.json").read_bytes(), g0)
        self.assertEqual((run / "fingerprint.json").read_bytes(), f0)

    def test_pairs_only_within_a_disruption(self):
        from montecarlo.grid import _make_pair_keys
        keys = _make_pair_keys([("D01", "A"), ("D02", "C"), ("D01", "B"),
                                ("D02", "D"), ("D02", "E")])
        self.assertEqual(keys, ["A|B", "C|D", "C|E", "D|E"])

    def test_family_crossings_use_find_crossings(self):
        from montecarlo.grid import P_GRID, _compute_crossings, find_crossings
        f = {"A|B": lambda p: 0.43 - p, "C|D": lambda p: 1 - p}

        def res(p):
            return ({}, {}, {k: g(p) for k, g in f.items()},
                    {k: 0.01 for k in f}, {}, {})
        full = [{"kind": "grid", "p": p} for p in P_GRID]
        rec = {p: (res(p)[2], res(p)[3]) for p in P_GRID}
        _, crossings = _compute_crossings(
            full, rec, list(f), P_GRID, 10, eval_at_p=res,
            make_pt=lambda p, r: {"p": p})
        expected = find_crossings(f["A|B"], P_GRID)
        self.assertEqual(len(crossings), 1)
        self.assertEqual(crossings[0]["pair"], ["A", "B"])
        self.assertEqual((crossings[0]["p_lo"], crossings[0]["p_hi"],
                          crossings[0]["diff_lo"], crossings[0]["diff_hi"]),
                         expected[0])

    def test_m1_check_keeps_entry_when_se_is_zero(self):
        from montecarlo.grid import _build_m1_check
        point = {"kind": "m1", "expected_late": {"WAIT": 1.0}, "se": {"WAIT": 0.0}}
        out = _build_m1_check(self.run_dir,
                              [{"family": "scale", "points": [point]}], ["WAIT"])
        self.assertIn("WAIT", out)
        self.assertIsNone(out["WAIT"]["z"])

    def test_common_random_numbers_k2_family(self):
        """WAIT and ALT_BUY do not use the K2 lanes: identical at every K2 point."""
        from montecarlo.grid import build_grid
        r = self._copy_run("crn")
        g = build_grid(self.data_copy, r, N=5, seed=7, method="lhs",
                       families=["K2"], **_TINY)
        pts = [p for p in g["families"][0]["points"] if p["kind"] == "grid"]
        for sid in ("WAIT", "ALT_BUY"):
            self.assertEqual(len({p["expected_late"][sid] for p in pts}), 1, sid)


if __name__ == "__main__":
    import unittest
    unittest.main()
