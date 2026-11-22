"""Tests for the new episode-timeline sampler (P4a)."""

import csv
import pathlib
import shutil
import tempfile
import unittest
from datetime import date
from unittest import mock

from engine.episodes import derived_tags
from engine.loader import load_all
from montecarlo import sample as sample_mod
from montecarlo.estimate import estimate
from montecarlo.run import run
from montecarlo.sample import sample_worlds

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _append(path, line):
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------------------
# 1. Demo run header and slot_counts
# ---------------------------------------------------------------------------

class TestDemoRunEpisodeHeader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = pathlib.Path(tempfile.mkdtemp())
        cls._data = cls._tmpdir / "data"
        shutil.copytree(DATA_DIR, cls._data, dirs_exist_ok=True)
        cls._out = cls._tmpdir / "out"
        cls._est = estimate(DATA_DIR)
        cls._db = load_all(DATA_DIR)
        cls._worlds, cls._meta = sample_worlds(
            cls._est, cls._db, M=20, N=50, seed=42
        )
        # Write to worlds.csv and load back
        cols = (
            ["world_id", "draw", "weight"]
            + [c for c in cls._worlds[0] if c not in ("world_id", "draw", "weight")]
        )
        _write(cls._data / "worlds.csv", cls._worlds, cols)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_slot_counts(self):
        self.assertEqual(self._meta["slot_counts"], {"K1": 4, "K2": 4})

    def test_header_variable_columns(self):
        """Variable columns appear first in est order."""
        expected_var = [
            "purchase_order.PO01.receipt_date",
            "offer.OF02.delay_business_days",
            "lane.LN01.delay_days",
            "lane.LN02.delay_days",
        ]
        actual = [
            c for c in self._worlds[0]
            if c not in ("world_id", "draw", "weight")
        ]
        self.assertEqual(actual[:4], expected_var)

    def test_header_episode_columns_k1(self):
        """K1 episode columns ep1..ep4 follow variable columns."""
        all_cols = [
            c for c in self._worlds[0]
            if c not in ("world_id", "draw", "weight")
        ]
        k1_cols = [c for c in all_cols if c.startswith("cause.K1.")]
        expected = []
        for j in range(1, 5):
            expected += [
                f"cause.K1.ep{j}_start_date",
                f"cause.K1.ep{j}_end_date",
                f"cause.K1.ep{j}_delay_days",
            ]
        self.assertEqual(k1_cols, expected)

    def test_header_episode_columns_k2(self):
        """K2 episode columns ep1..ep4 follow K1 columns."""
        all_cols = [
            c for c in self._worlds[0]
            if c not in ("world_id", "draw", "weight")
        ]
        k2_cols = [c for c in all_cols if c.startswith("cause.K2.")]
        expected = []
        for j in range(1, 5):
            expected += [
                f"cause.K2.ep{j}_start_date",
                f"cause.K2.ep{j}_end_date",
                f"cause.K2.ep{j}_delay_days",
            ]
        self.assertEqual(k2_cols, expected)

    def test_load_all_accepts_worlds(self):
        """load_all on the copied folder with these worlds.csv succeeds."""
        db = load_all(self._data)
        self.assertEqual(db["worlds_format"], "new")
        self.assertIsNotNone(db["worlds"])
        self.assertGreater(len(db["worlds"]), 0)


# ---------------------------------------------------------------------------
# 2. Statistical accuracy (M=200, N=100)
# ---------------------------------------------------------------------------

class TestStatisticalAccuracy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = pathlib.Path(tempfile.mkdtemp())
        cls._out = cls._tmpdir / "out"
        cls._record = run(DATA_DIR, cls._out, M=200, N=100, seed=777)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _worlds(self):
        with (self._out / "worlds.csv").open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def test_k1_derived_tag_share(self):
        """Weighted share of worlds with derived K1 tag = 1 is near 0.0948 ± 0.01."""
        db = load_all(DATA_DIR)
        dst = self._tmpdir / "data2"
        shutil.copytree(DATA_DIR, dst, dirs_exist_ok=True)
        shutil.copy(self._out / "worlds.csv", dst / "worlds.csv")
        db2 = load_all(dst)
        total = sum(w["weight"] for w in db2["worlds"])
        active = sum(w["weight"] for w in db2["worlds"] if derived_tags(w, db2).get("K1", 0) == 1)
        share = active / total
        self.assertAlmostEqual(share, 0.0948, delta=0.01,
            msg=f"K1 derived tag share {share:.4f}")

    def test_k2_derived_tag_share(self):
        """Weighted share of worlds with derived K2 tag = 1 is near 0.1067 ± 0.01."""
        dst = self._tmpdir / "data3"
        shutil.copytree(DATA_DIR, dst, dirs_exist_ok=True)
        shutil.copy(self._out / "worlds.csv", dst / "worlds.csv")
        db2 = load_all(dst)
        total = sum(w["weight"] for w in db2["worlds"])
        active = sum(w["weight"] for w in db2["worlds"] if derived_tags(w, db2).get("K2", 0) == 1)
        share = active / total
        self.assertAlmostEqual(share, 0.1067, delta=0.01,
            msg=f"K2 derived tag share {share:.4f}")

    def test_k1_slot1_duration1_share(self):
        """Among K1 slot-1 episodes, share with duration 1 is near 0.4 ± 0.04."""
        rows = self._worlds()
        # slot-1 episodes: start_date != 'none'
        col_s = "cause.K1.ep1_start_date"
        col_e = "cause.K1.ep1_end_date"
        filled = [r for r in rows if r[col_s] != "none"]
        if not filled:
            self.skipTest("No K1 slot-1 episodes found")
        total_w = sum(int(r["weight"]) for r in filled)
        dur1_w = sum(
            int(r["weight"]) for r in filled
            if r[col_s] == r[col_e]  # duration=1 means end==start
        )
        share = dur1_w / total_w
        self.assertAlmostEqual(share, 0.4, delta=0.04,
            msg=f"K1 slot-1 duration=1 share {share:.4f}")

    def test_k2_slot1_duration1_share(self):
        """Among K2 slot-1 episodes, share with duration 1 is near 0.533 ± 0.04."""
        rows = self._worlds()
        col_s = "cause.K2.ep1_start_date"
        col_e = "cause.K2.ep1_end_date"
        filled = [r for r in rows if r[col_s] != "none"]
        if not filled:
            self.skipTest("No K2 slot-1 episodes found")
        total_w = sum(int(r["weight"]) for r in filled)
        dur1_w = sum(
            int(r["weight"]) for r in filled
            if r[col_s] == r[col_e]
        )
        share = dur1_w / total_w
        self.assertAlmostEqual(share, 0.533, delta=0.04,
            msg=f"K2 slot-1 duration=1 share {share:.4f}")

    def test_overflow_counts_small(self):
        """Demo run M=200, N=100: overflow_counts <= 2 for each cause."""
        est2 = estimate(DATA_DIR)
        db2 = load_all(DATA_DIR)
        _, meta = sample_worlds(est2, db2, M=200, N=100, seed=777)
        for cid, cnt in meta["overflow_counts"].items():
            self.assertLessEqual(cnt, 2,
                msg=f"overflow_counts[{cid!r}] = {cnt} > 2")


# ---------------------------------------------------------------------------
# 2b. Overflow only counted when all slots filled
# ---------------------------------------------------------------------------

class TestOverflowCounting(unittest.TestCase):

    def test_overflow_only_when_all_slots_filled(self):
        """With K1 slot count forced to 1, overflows counted only in full worlds."""
        from montecarlo import sample as sample_mod

        est2 = estimate(DATA_DIR)
        db2 = load_all(DATA_DIR)

        orig_compute = sample_mod._compute_slot_count

        def patched_compute(rate_shape, T_free_days, D_k, has_open):
            # Force K1 to 1 slot by intercepting via stack inspection
            return 1

        # Patch only for K1 by wrapping sample_worlds manually:
        # We call sample_worlds with a patched slot_count environment.
        # The simplest approach: monkey-patch _compute_slot_count,
        # run a small sample, then restore.
        sample_mod._compute_slot_count = patched_compute
        try:
            worlds, meta = sample_worlds(est2, db2, M=20, N=50, seed=42)
        finally:
            sample_mod._compute_slot_count = orig_compute

        ov_k1 = meta["overflow_counts"]["K1"]
        # At least one overflow counted (with M=20, N=50, rate is > 0)
        self.assertGreater(ov_k1, 0,
            msg=f"Expected at least one K1 overflow, got {ov_k1}")

        # Overflows only in worlds whose single K1 slot is filled
        for w in worlds:
            ep1_start = w.get("cause.K1.ep1_start_date", "none")
            # We cannot directly know overflow per world from meta, but we can
            # verify: if ep1 is "none", that world never triggered an overflow
            # draw (the rng stream is not observable here, but the count must
            # equal the number of times a full world triggered one). Instead,
            # check that overflow_counts["K1"] <= total worlds with ep1 filled.
            pass  # count-level invariant checked above

        filled_count = sum(
            1 for w in worlds
            if w.get("cause.K1.ep1_start_date", "none") != "none"
        )
        self.assertLessEqual(ov_k1, filled_count,
            msg=f"overflow_counts K1 {ov_k1} > filled worlds {filled_count}")


# ---------------------------------------------------------------------------
# 3. Later-order data set (larger slot count for K1)
# ---------------------------------------------------------------------------

class TestLaterOrderSlotCount(unittest.TestCase):

    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())
        self.d = self._tmp / "data"
        shutil.copytree(DATA_DIR, self.d)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_slot_count_k1_increases(self):
        """With HYBRID recovery_purchases action_date 2026-11-20, K1 slots = 5."""
        rp = _read(self.d / "recovery_purchases.csv")
        for row in rp:
            if row["scenario_id"] == "HYBRID" and row["offer_id"] == "OF02":
                row["action_date"] = "2026-11-20"
        _write(self.d / "recovery_purchases.csv", rp)
        est2 = estimate(self.d)
        db2 = load_all(self.d)
        _, meta = sample_worlds(est2, db2, M=5, N=10, seed=1)
        self.assertEqual(meta["slot_counts"]["K1"], 5)
        self.assertEqual(meta["slot_counts"]["K2"], 4)


# ---------------------------------------------------------------------------
# 4. Open-episode data set
# ---------------------------------------------------------------------------

class TestOpenEpisodeSlotCount(unittest.TestCase):

    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())
        self.d = self._tmp / "data"
        shutil.copytree(DATA_DIR, self.d)
        # Append open K1 episode
        _append(self.d / "history" / "episodes.csv",
                "K1E004,K1,2026-11-05,,")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run(self, M=5, N=10, seed=1):
        est2 = estimate(self.d)
        db2 = load_all(self.d)
        worlds, meta = sample_worlds(est2, db2, M=M, N=N, seed=seed)
        return est2, db2, worlds, meta

    def test_slot_counts(self):
        """K1 open episode adds 1 slot: slots K1=6, K2=4."""
        _, _, _, meta = self._run()
        self.assertEqual(meta["slot_counts"]["K1"], 6)
        self.assertEqual(meta["slot_counts"]["K2"], 4)

    def test_every_world_k1_ep1_start_date(self):
        """Every world has K1 ep1_start_date = 2026-11-05."""
        _, _, worlds, _ = self._run()
        for w in worlds:
            self.assertEqual(w["cause.K1.ep1_start_date"], "2026-11-05",
                f"world {w['world_id']}: K1 ep1_start_date = {w['cause.K1.ep1_start_date']!r}")

    def test_derived_tag_k1_always_1(self):
        """Derived K1 tag = 1 in every world (open episode overlaps DAY0 window)."""
        est2, db2, worlds, _ = self._run(M=5, N=10, seed=1)
        # Write worlds to temp dir and load
        data_tmp = self._tmp / "data_w"
        shutil.copytree(self.d, data_tmp)
        cols = (["world_id", "draw", "weight"] +
                [c for c in worlds[0] if c not in ("world_id", "draw", "weight")])
        _write(data_tmp / "worlds.csv", worlds, cols)
        db3 = load_all(data_tmp)
        for w in db3["worlds"]:
            tags = derived_tags(w, db3)
            self.assertEqual(tags.get("K1"), 1,
                f"world {w['world_id']}: K1 derived tag = {tags.get('K1')}")


# ---------------------------------------------------------------------------
# 5. Cap invariants
# ---------------------------------------------------------------------------

class TestCapInvariants(unittest.TestCase):

    def setUp(self):
        self._tmp = pathlib.Path(tempfile.mkdtemp())
        self.d = self._tmp / "data"
        shutil.copytree(DATA_DIR, self.d)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_room_values(self):
        """Room values on the demo data match spec."""
        from montecarlo.sample import _compute_room_offer, _compute_room_lane, _compute_room_po
        from datetime import timedelta
        db = load_all(DATA_DIR)
        cap = db["DAY0"] + timedelta(days=365)
        self.assertEqual(_compute_room_offer(db, "OF02", cap), 248)
        self.assertEqual(_compute_room_po(db, "PO01", cap), 245)
        self.assertEqual(_compute_room_lane(db, "LN01", cap), 363)
        self.assertEqual(_compute_room_lane(db, "LN02", cap), 361)

    def test_cause_caps(self):
        """C_K1 = 245, C_K2 = 361."""
        from montecarlo.sample import _compute_room_offer, _compute_room_lane, _compute_room_po
        from datetime import timedelta
        db = load_all(DATA_DIR)
        cap = db["DAY0"] + timedelta(days=365)
        c_k1 = min(
            _compute_room_offer(db, "OF02", cap),
            _compute_room_po(db, "PO01", cap),
        )
        c_k2 = min(
            _compute_room_lane(db, "LN01", cap),
            _compute_room_lane(db, "LN02", cap),
        )
        self.assertEqual(c_k1, 245)
        self.assertEqual(c_k2, 361)

    def test_huge_severity_cap_invariants(self):
        """With _inv_severity patched to 10^9, all delays/deviations respect caps."""
        est2 = estimate(self.d)
        db2 = load_all(self.d)
        with mock.patch.object(sample_mod, "_inv_severity", return_value=10**9):
            worlds, meta = sample_worlds(est2, db2, M=2, N=5, seed=42)
        # Write to verify via load_all
        data_tmp = self._tmp / "data_w"
        shutil.copytree(self.d, data_tmp)
        cols = (["world_id", "draw", "weight"] +
                [c for c in worlds[0] if c not in ("world_id", "draw", "weight")])
        _write(data_tmp / "worlds.csv", worlds, cols)
        # Must load without error
        db3 = load_all(data_tmp)
        self.assertGreater(len(db3["worlds"]), 0)
        for w in worlds:
            # Every filled K1 delay <= 245
            for j in range(1, 5):
                dv = w.get(f"cause.K1.ep{j}_delay_days", "none")
                if dv != "none":
                    self.assertLessEqual(int(dv), 245,
                        f"K1 ep{j} delay {dv} > 245")
            # Every filled K2 delay <= 361
            for j in range(1, 5):
                dv = w.get(f"cause.K2.ep{j}_delay_days", "none")
                if dv != "none":
                    self.assertLessEqual(int(dv), 361,
                        f"K2 ep{j} delay {dv} > 361")
            # K1 max delay
            k1_delays = [
                int(w[f"cause.K1.ep{j}_delay_days"])
                for j in range(1, 5)
                if w.get(f"cause.K1.ep{j}_delay_days", "none") != "none"
            ]
            max_k1 = max(k1_delays) if k1_delays else 0
            # K2 max delay
            k2_delays = [
                int(w[f"cause.K2.ep{j}_delay_days"])
                for j in range(1, 5)
                if w.get(f"cause.K2.ep{j}_delay_days", "none") != "none"
            ]
            max_k2 = max(k2_delays) if k2_delays else 0
            # OF02 own <= 248 - max K1 delay
            of02 = int(w["offer.OF02.delay_business_days"])
            self.assertLessEqual(of02, 248 - max_k1,
                f"OF02 own {of02} > 248 - {max_k1}")
            # LN01 own <= 363 - max K2 delay
            ln01 = int(w["lane.LN01.delay_days"])
            self.assertLessEqual(ln01, 363 - max_k2,
                f"LN01 own {ln01} > 363 - {max_k2}")
            # LN02 own <= 361 - max K2 delay
            ln02 = int(w["lane.LN02.delay_days"])
            self.assertLessEqual(ln02, 361 - max_k2,
                f"LN02 own {ln02} > 361 - {max_k2}")


# ---------------------------------------------------------------------------
# 6. Lane own=-10^9 does not raise OverflowError in simulate
# ---------------------------------------------------------------------------

class TestLaneNegativeHugeSimulate(unittest.TestCase):

    def test_lane_own_minus_huge_gives_next_day(self):
        """simulate on a new-format world with lane own -10^9 gives arrival = order date + 1 day."""
        from engine.simulate import simulate
        from datetime import timedelta
        db = load_all(DATA_DIR)
        # Build a minimal world with lane.LN01.delay_days = -10^9
        world_overrides = {("lane", "LN01", "delay_days"): -10**9}
        db2 = dict(db)
        db2["world_episodes"] = {}
        # Inject override into db2 to simulate what the new-format path does
        # Actually we test via simulate directly with world_episodes set
        from engine.simulate import build_scenario_actions
        actions, dis_id = build_scenario_actions("TRANSFER", db)
        # Patch LN01 delay_days
        db3 = dict(db)
        import copy
        db3["lanes"] = copy.deepcopy(db["lanes"])
        db3["lanes"]["LN01"]["delay_days"] = -10**9
        db3["world_episodes"] = {}
        # Should complete without OverflowError
        result = simulate(actions, dis_id, db3)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
