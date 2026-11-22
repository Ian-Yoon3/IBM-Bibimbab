"""Tests for per-cause summaries and grid thresholds in world-risk (step 6b-1b).

Known answers:
  A. Hand-made episode worlds (K1-only activity): active_pct, without, with by hand.
  B. evaluate_run equals evaluate_worlds for "causes" structural fields (active_pct,
     without, with) and all earlier keys.
  C. rebuild_worlds_csv is byte-identical with active.* columns present.
  D. Tiny grid (build_run with grid=True): "grid" per cause and "common_scale" present;
     without a grid both are null.
  E. Stage-1 data and announced-date fallback: "causes" == [] and "common_scale" null.
"""

import csv
import json
import math
import pathlib
import shutil
import tempfile
import unittest
from fractions import Fraction

import engine.runs
from engine.loader import load_all
from engine.worlds import evaluate_worlds
from montecarlo.run import build_run
from scripts.stage1_data import make_stage1_data_dir, use_stage1_default_data

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

# worlds.csv header for 1-slot episode worlds (K1 and K2 each with 1 slot)
_EP_HEADER = (
    "world_id,draw,weight,"
    "purchase_order.PO01.receipt_date,"
    "offer.OF02.delay_business_days,"
    "lane.LN01.delay_days,"
    "lane.LN02.delay_days,"
    "cause.K1.ep1_start_date,cause.K1.ep1_end_date,cause.K1.ep1_delay_days,"
    "cause.K2.ep1_start_date,cause.K2.ep1_end_date,cause.K2.ep1_delay_days"
)


def _copy_real_data(tmp_dir):
    """Copy the real data/ folder (which includes causes.csv) to tmp_dir/data."""
    dest = pathlib.Path(tmp_dir) / "data"
    shutil.copytree(_DATA_DIR, dest, dirs_exist_ok=True)
    return dest


def _write_worlds_text(dd, text):
    (pathlib.Path(dd) / "worlds.csv").write_text(text, encoding="utf-8", newline="\n")


def _opt(result, sid):
    return next(o for o in result["options"] if o["scenario_id"] == sid)


def _cause(result, cid):
    return next(e for e in result["causes"] if e["cause_id"] == cid)


# ---------------------------------------------------------------------------
# A. Hand-made episode worlds (K1-only activity)
#
# Data: real data copy (includes causes.csv with K1→PO01,OF02 and K2→LN01,LN02).
#
# K1 H0 = max(revised_receipt_date=2026-11-17, next_biz(DAY0+OF02_lead=11-09+3=11-12))
#        = max(11-17, 11-12) = 2026-11-17
# K2 H0 = max(DAY0+LN01_lead=11-11, DAY0+LN02_lead=11-13) = 2026-11-13
#
# Episode design for K1 tag=1 WITHOUT affecting OF02 deliveries:
#   K1 ep: start=2026-11-17 (=H0_K1), end=2026-11-23, delay=1
#   OF02 recovery arrives DAY0+3=2026-11-12.
#   first_overlap_delay: start(11-17) <= promised(11-12)? NO → no delay applied. ✓
#
# 2 worlds, both with date override=2026-11-17 (announced date),
# OF02.delay_business_days=0, LN01.delay_days=0, LN02.delay_days=0:
#
# W1: draw=0, weight=1, date=2026-11-21, K1 active [11-17..11-23 delay=1], K2 "none"
# W2: draw=0, weight=1, date=2026-11-13, K1 "none", K2 "none"
#
# (K2 always tag=0 → K2 active_pct=0.0)
#
# Late orders per date (from what_if table, confirmed by test_worlds.py):
#   date       WAIT TRANSFER ALT_BUY HYBRID
#   2026-11-21  11       8       7      5
#   2026-11-13   3       1       1      0
#
# K1 active_pct = 1/(1+1)*100 = 50.0
# K1 without (W2, wt=1): WAIT=3.0, TRANSFER=1.0, ALT_BUY=1.0, HYBRID=0.0
# K1 with (W1, wt=1):    WAIT=11.0, TRANSFER=8.0, ALT_BUY=7.0, HYBRID=5.0
# K2 active_pct = 0.0
# K2 "with" = None (no K2-active world)
# K2 "without" = weighted avg over all worlds = (11+3)/2=7.0 for WAIT etc.
#   WAIT=(11+3)/2=7.0, TRANSFER=(8+1)/2=4.5, ALT_BUY=(7+1)/2=4.0, HYBRID=(5+0)/2=2.5
# ---------------------------------------------------------------------------

_EP_W1 = (
    "W1,0,1,2026-11-21,0,0,0,"
    "2026-11-17,2026-11-23,1,"
    "none,none,none"
)
_EP_W2 = (
    "W2,0,1,2026-11-13,0,0,0,"
    "none,none,none,"
    "none,none,none"
)

_K1_WITHOUT = {"WAIT": 3.0, "TRANSFER": 1.0, "ALT_BUY": 1.0, "HYBRID": 0.0}
_K1_WITH    = {"WAIT": 11.0, "TRANSFER": 8.0, "ALT_BUY": 7.0, "HYBRID": 5.0}
_K2_WITHOUT = {"WAIT": 7.0, "TRANSFER": 4.5, "ALT_BUY": 4.0, "HYBRID": 2.5}
_K2_WITH    = None  # no K2-active world


class TestEpisodeWorldsCauses(unittest.TestCase):
    """(A) Hand-made episode worlds: active_pct, without, with by hand."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        dd = _copy_real_data(cls._tmp)
        worlds_text = "\n".join([_EP_HEADER, _EP_W1, _EP_W2]) + "\n"
        _write_worlds_text(dd, worlds_text)
        db = load_all(dd)
        cls.result = evaluate_worlds("D01", db)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_a_causes_key_exists(self):
        self.assertIn("causes", self.result)
        self.assertIsInstance(self.result["causes"], list)

    def test_a_common_scale_null(self):
        """evaluate_worlds always sets common_scale=null."""
        self.assertIsNone(self.result["common_scale"])

    def test_a_two_causes(self):
        self.assertEqual(len(self.result["causes"]), 2,
                         f"expected 2 causes, got {len(self.result['causes'])}")

    def test_a_cause_order(self):
        """Causes in first-appearance order from causes.csv: K1 then K2."""
        ids = [e["cause_id"] for e in self.result["causes"]]
        self.assertEqual(ids, ["K1", "K2"])

    def test_a_k1_targets(self):
        k1 = _cause(self.result, "K1")
        # K1 targets: purchase_order PO01, offer OF02
        self.assertEqual(k1["targets"], [["purchase_order", "PO01"], ["offer", "OF02"]])

    def test_a_k2_targets(self):
        k2 = _cause(self.result, "K2")
        self.assertEqual(k2["targets"], [["lane", "LN01"], ["lane", "LN02"]])

    def test_a_k1_active_pct(self):
        k1 = _cause(self.result, "K1")
        self.assertEqual(k1["active_pct"], 50.0,
                         f"K1 active_pct: expected 50.0, got {k1['active_pct']}")

    def test_a_k2_active_pct(self):
        k2 = _cause(self.result, "K2")
        self.assertEqual(k2["active_pct"], 0.0,
                         f"K2 active_pct: expected 0.0, got {k2['active_pct']}")

    def _check_without(self, cid, sid, want):
        entry = _cause(self.result, cid)
        got = entry["without"][sid]
        if got != want:
            self.fail(f"{cid} without[{sid}]: expected {want}, got {got}")

    def _check_with(self, cid, sid, want):
        entry = _cause(self.result, cid)
        got = entry["with"][sid]
        if got != want:
            self.fail(f"{cid} with[{sid}]: expected {want}, got {got}")

    def test_a_k1_without_wait(self):       self._check_without("K1", "WAIT", 3.0)
    def test_a_k1_without_transfer(self):   self._check_without("K1", "TRANSFER", 1.0)
    def test_a_k1_without_alt_buy(self):    self._check_without("K1", "ALT_BUY", 1.0)
    def test_a_k1_without_hybrid(self):     self._check_without("K1", "HYBRID", 0.0)

    def test_a_k1_with_wait(self):       self._check_with("K1", "WAIT", 11.0)
    def test_a_k1_with_transfer(self):   self._check_with("K1", "TRANSFER", 8.0)
    def test_a_k1_with_alt_buy(self):    self._check_with("K1", "ALT_BUY", 7.0)
    def test_a_k1_with_hybrid(self):     self._check_with("K1", "HYBRID", 5.0)

    def test_a_k2_without_wait(self):       self._check_without("K2", "WAIT", 7.0)
    def test_a_k2_without_transfer(self):   self._check_without("K2", "TRANSFER", 4.5)
    def test_a_k2_without_alt_buy(self):    self._check_without("K2", "ALT_BUY", 4.0)
    def test_a_k2_without_hybrid(self):     self._check_without("K2", "HYBRID", 2.5)

    def test_a_k2_with_null(self):
        """K2 has no active worlds → 'with' values are all null."""
        k2 = _cause(self.result, "K2")
        for sid in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            self.assertIsNone(k2["with"][sid],
                              f"K2 with[{sid}] should be null")

    def test_a_causes_per_year_mean_null(self):
        """aggregate_options sets per_year_mean=null (filled only by evaluate_run)."""
        for entry in self.result["causes"]:
            self.assertIsNone(entry["per_year_mean"],
                              f"{entry['cause_id']} per_year_mean should be null")

    def test_a_causes_grid_null(self):
        for entry in self.result["causes"]:
            self.assertIsNone(entry["grid"],
                              f"{entry['cause_id']} grid should be null")

    def test_a_consistency_k1(self):
        """Weighted-average consistency: active_w*with + inactive_w*without = total_w * expected."""
        result = self.result
        total_w = sum(wt for _, wt in [(1, 1), (1, 1)])  # 2
        k1 = _cause(result, "K1")
        # active_pct = 50.0 → w1 = 1, w0 = 1
        for sid in ("WAIT", "TRANSFER", "ALT_BUY", "HYBRID"):
            opt = _opt(result, sid)
            exp = opt["expected_late_orders"]
            without = k1["without"][sid]
            with_ = k1["with"][sid]
            # 1 * with_ + 1 * without = 2 * exp (before rounding)
            lhs = with_ + without
            rhs = 2 * exp
            self.assertAlmostEqual(lhs, rhs, places=1,
                                   msg=f"K1 consistency {sid}: {with_}+{without}={lhs} vs 2*{exp}={rhs}")


# ---------------------------------------------------------------------------
# B. evaluate_run equals evaluate_worlds for "causes" fields (and all earlier keys).
#
# Build a small run (M=20, N=10) on a data copy, then compare run vs direct
# for: active_pct, without keys, with keys (excluding per_year_mean, grid,
# open_episode which are run-only).
# ---------------------------------------------------------------------------

class TestRunEqualsCauses(unittest.TestCase):
    """(B) evaluate_run causes structural fields equal evaluate_worlds."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data_copy = base / "data_copy"
        shutil.copytree(_DATA_DIR, cls.data_copy, dirs_exist_ok=True)
        cls.run_dir = base / "runs" / "tb"
        build_run(cls.data_copy, cls.run_dir, M=20, N=10, seed=9)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_b_causes_structural_equality(self):
        """causes active_pct, without, with match between run and direct."""
        base = pathlib.Path(self._tmp)
        direct_copy = base / "data_copy2"
        shutil.copytree(_DATA_DIR, direct_copy, dirs_exist_ok=True)
        shutil.copy(self.run_dir / "worlds.csv", direct_copy / "worlds.csv")
        try:
            db_direct = load_all(direct_copy)
            direct = evaluate_worlds("D01", db_direct)
            db_base = load_all(self.data_copy)
            run_result = engine.runs.evaluate_run("D01", db_base, self.run_dir)
        finally:
            shutil.rmtree(direct_copy, ignore_errors=True)

        # Compare causes
        d_causes = {e["cause_id"]: e for e in direct["causes"]}
        r_causes = {e["cause_id"]: e for e in run_result["causes"]}
        self.assertEqual(set(d_causes.keys()), set(r_causes.keys()),
                         "cause_ids differ")
        for cid in d_causes:
            d = d_causes[cid]
            r = r_causes[cid]
            self.assertEqual(r["cause_id"], d["cause_id"])
            self.assertEqual(r["targets"], d["targets"])
            self.assertEqual(r["active_pct"], d["active_pct"],
                             msg=f"{cid} active_pct mismatch")
            self.assertEqual(r["without"], d["without"],
                             msg=f"{cid} without mismatch")
            self.assertEqual(r["with"], d["with"],
                             msg=f"{cid} with mismatch")

    def test_b_all_earlier_keys_match(self):
        """All keys from previous steps (options, tradeoff_steps, ranking) still match."""
        base = pathlib.Path(self._tmp)
        direct_copy = base / "data_copy3"
        shutil.copytree(_DATA_DIR, direct_copy, dirs_exist_ok=True)
        shutil.copy(self.run_dir / "worlds.csv", direct_copy / "worlds.csv")
        try:
            db_direct = load_all(direct_copy)
            direct = evaluate_worlds("D01", db_direct)
            db_base = load_all(self.data_copy)
            run_result = engine.runs.evaluate_run("D01", db_base, self.run_dir)
        finally:
            shutil.rmtree(direct_copy, ignore_errors=True)

        for key in ("disruption_id", "po_id", "announced_receipt_date",
                    "world_count", "quantile_level", "options",
                    "what_if", "tradeoff_steps", "ranking"):
            self.assertEqual(
                run_result.get(key), direct.get(key),
                msg=f"Key {key!r}: run={run_result.get(key)!r}, direct={direct.get(key)!r}"
            )


# ---------------------------------------------------------------------------
# C. rebuild_worlds_csv is byte-identical with active.* columns present.
#    (The active.* columns appear in results.csv but are excluded from
#     worlds.csv reconstruction.)
# ---------------------------------------------------------------------------

class TestRebuildWithActiveCols(unittest.TestCase):
    """(C) rebuild_worlds_csv produces byte-identical worlds.csv."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data_copy = base / "data_copy"
        shutil.copytree(_DATA_DIR, cls.data_copy, dirs_exist_ok=True)
        cls.run_dir = base / "runs" / "tc"
        build_run(cls.data_copy, cls.run_dir, M=20, N=10, seed=11)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_c_rebuild_bytes_equal(self):
        orig = (self.run_dir / "worlds.csv").read_bytes()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            rebuilt_path = pathlib.Path(f.name)
        try:
            engine.runs.rebuild_worlds_csv(self.run_dir, rebuilt_path)
            rebuilt = rebuilt_path.read_bytes()
        finally:
            rebuilt_path.unlink(missing_ok=True)
        self.assertEqual(orig, rebuilt,
                         "rebuilt worlds.csv bytes differ from original")

    def test_c_results_has_active_cols(self):
        """results.csv must have active.K1 and active.K2 columns."""
        with open(self.run_dir / "results.csv", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames
        self.assertIn("active.K1", header,
                      f"active.K1 missing from results.csv header: {header}")
        self.assertIn("active.K2", header,
                      f"active.K2 missing from results.csv header: {header}")

    def test_c_worlds_no_active_cols(self):
        """worlds.csv must NOT have active.* columns."""
        with open(self.run_dir / "worlds.csv", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames
        active_cols = [c for c in header if c.startswith("active.")]
        self.assertEqual(active_cols, [],
                         f"worlds.csv should have no active.* columns, got {active_cols}")


# ---------------------------------------------------------------------------
# D. Tiny grid: "grid" per cause and "common_scale" present vs absent.
#
# Build a run with grid=True (small M/N), verify:
# - evaluate_run result["causes"] has non-null "grid" entries
# - result["common_scale"] is not null and has the required keys
# - Without grid (build_run grid=False), both are null
# ---------------------------------------------------------------------------

class TestGridCauses(unittest.TestCase):
    """(D) tiny grid: grid per cause and common_scale present; absent without grid."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)

        cls.data_grid = base / "data_grid"
        cls.data_nogrid = base / "data_nogrid"
        shutil.copytree(_DATA_DIR, cls.data_grid, dirs_exist_ok=True)
        shutil.copytree(_DATA_DIR, cls.data_nogrid, dirs_exist_ok=True)

        cls.run_grid   = base / "runs" / "td_grid"
        cls.run_nogrid = base / "runs" / "td_nogrid"

        build_run(cls.data_grid, cls.run_grid, M=20, N=10, seed=13,
                  grid=True, target_se=0.5, pilot_M=4, max_M=8)
        build_run(cls.data_nogrid, cls.run_nogrid, M=20, N=10, seed=13,
                  grid=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _run_result(self, run_dir, data_dir):
        db = load_all(data_dir)
        return engine.runs.evaluate_run("D01", db, run_dir)

    def test_d_with_grid_causes_non_null(self):
        result = self._run_result(self.run_grid, self.data_grid)
        for entry in result["causes"]:
            self.assertIsNotNone(entry["grid"],
                                 f"{entry['cause_id']} grid should be non-null with grid run")

    def test_d_with_grid_causes_grid_keys(self):
        result = self._run_result(self.run_grid, self.data_grid)
        for entry in result["causes"]:
            g = entry["grid"]
            self.assertIn("D0_days", g)
            self.assertIn("crossings", g)
            self.assertIn("max_p", g)
            self.assertIn("max_per_year", g)

    def test_d_with_grid_common_scale_non_null(self):
        result = self._run_result(self.run_grid, self.data_grid)
        self.assertIsNotNone(result["common_scale"],
                             "common_scale should be non-null with grid run")

    def test_d_with_grid_common_scale_keys(self):
        result = self._run_result(self.run_grid, self.data_grid)
        cs = result["common_scale"]
        self.assertIn("reference_cause", cs)
        self.assertIn("crossings", cs)
        self.assertIn("max_m", cs)

    def test_d_without_grid_causes_grid_null(self):
        result = self._run_result(self.run_nogrid, self.data_nogrid)
        for entry in result["causes"]:
            self.assertIsNone(entry["grid"],
                              f"{entry['cause_id']} grid should be null without grid")

    def test_d_without_grid_common_scale_null(self):
        result = self._run_result(self.run_nogrid, self.data_nogrid)
        self.assertIsNone(result["common_scale"],
                          "common_scale should be null without grid")

    def test_d_grid_formulas(self):
        """max_per_year = round(-ln(1-max_p) / D0_days * 365, 1)."""
        result = self._run_result(self.run_grid, self.data_grid)
        for entry in result["causes"]:
            g = entry["grid"]
            if g is None or g["max_p"] is None:
                continue
            D0 = g["D0_days"]
            max_p = g["max_p"]
            expected = round(-math.log(1 - max_p) / D0 * 365, 1)
            self.assertAlmostEqual(g["max_per_year"], expected, places=0,
                                   msg=f"{entry['cause_id']} max_per_year formula mismatch")

    def test_d_per_year_mean_non_null(self):
        result = self._run_result(self.run_grid, self.data_grid)
        for entry in result["causes"]:
            self.assertIsNotNone(entry["per_year_mean"],
                                 f"{entry['cause_id']} per_year_mean should be non-null")


# ---------------------------------------------------------------------------
# E. Stage-1 data and announced-date fallback: "causes" == [] and
#    "common_scale" is null.
# ---------------------------------------------------------------------------

class TestNoCauses(unittest.TestCase):
    """(E) Stage-1 data (no causes.csv) and announced-date: causes==[], common_scale null."""

    def test_e_stage1_causes_empty(self):
        with use_stage1_default_data():
            db = load_all()
            result = evaluate_worlds("D01", db)
        self.assertEqual(result["causes"], [],
                         f"stage1 causes: expected [], got {result['causes']}")

    def test_e_stage1_common_scale_null(self):
        with use_stage1_default_data():
            db = load_all()
            result = evaluate_worlds("D01", db)
        self.assertIsNone(result["common_scale"],
                          "stage1 common_scale should be null")

    def test_e_announced_date_causes_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = pathlib.Path(tmp) / "data"
            make_stage1_data_dir(dd)
            (dd / "worlds.csv").unlink()
            db = load_all(dd)
        result = evaluate_worlds("D01", db)
        self.assertEqual(result["causes"], [],
                         f"announced_date causes: expected [], got {result['causes']}")

    def test_e_announced_date_common_scale_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            dd = pathlib.Path(tmp) / "data"
            make_stage1_data_dir(dd)
            (dd / "worlds.csv").unlink()
            db = load_all(dd)
        result = evaluate_worlds("D01", db)
        self.assertIsNone(result["common_scale"],
                          "announced_date common_scale should be null")


# ---------------------------------------------------------------------------
# Additional: run_record.json has rate_shape, per_year_mean, open_episode
# ---------------------------------------------------------------------------

class TestRunRecordCauseKeys(unittest.TestCase):
    """run_record.json causes entries have rate_shape, per_year_mean, open_episode."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        base = pathlib.Path(cls._tmp)
        cls.data_copy = base / "data_copy"
        shutil.copytree(_DATA_DIR, cls.data_copy, dirs_exist_ok=True)
        cls.run_dir = base / "runs" / "trr"
        build_run(cls.data_copy, cls.run_dir, M=10, N=5, seed=17)
        with open(cls.run_dir / "run_record.json", encoding="utf-8") as fh:
            cls.record = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_rr_rate_shape_present(self):
        for cid, entry in self.record["causes"].items():
            self.assertIn("rate_shape", entry,
                          f"{cid} missing rate_shape in run_record.json")

    def test_rr_per_year_mean_present(self):
        for cid, entry in self.record["causes"].items():
            self.assertIn("per_year_mean", entry,
                          f"{cid} missing per_year_mean in run_record.json")

    def test_rr_per_year_mean_formula(self):
        """per_year_mean = round(rate_shape / T_free_days * 365, 6)."""
        for cid, entry in self.record["causes"].items():
            rs = entry["rate_shape"]
            T = entry["T_free_days"]
            if T > 0:
                want = round(rs / T * 365, 6)
                self.assertAlmostEqual(entry["per_year_mean"], want, places=5,
                                       msg=f"{cid} per_year_mean formula mismatch")

    def test_rr_open_episode_key_present(self):
        for cid, entry in self.record["causes"].items():
            self.assertIn("open_episode", entry,
                          f"{cid} missing open_episode in run_record.json")

    def test_rr_open_episode_null_when_no_open(self):
        """K1 and K2 have no open episode in the demo data."""
        for cid in ("K1", "K2"):
            if cid in self.record["causes"]:
                self.assertIsNone(self.record["causes"][cid]["open_episode"],
                                  f"{cid} open_episode should be null")


if __name__ == "__main__":
    unittest.main()
