"""Tests for engine/runs.py and montecarlo/run.py build_run.

Builds runs with M=20, N=10 in setUpClass, temporary folders only.
Never writes into data/. CSVs are written in with-blocks with newline="".
"""

import csv
import json
import pathlib
import shutil
import tempfile
import unittest

import engine.runs
from engine.loader import load_all
from engine.worlds import evaluate_worlds
from engine.tools import get_world_risk
from montecarlo.run import build_run

_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def _copy_data(dest):
    """Copy the real data/ folder to dest."""
    shutil.copytree(_DATA_DIR, dest, dirs_exist_ok=True)


def _append_line(path, line):
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(line + "\n")



# Fields that only a run can fill (from run_record.json and grid.json);
# evaluate_worlds leaves them null.  Compared separately in test_world_causes.
_RUN_ONLY_CAUSE_FIELDS = ("per_year_mean", "open_episode", "grid")


def _without_run_only(key, val):
    """Strip run-only fields so a run result compares to evaluate_worlds."""
    if key == "causes":
        return [{k: v for k, v in c.items() if k not in _RUN_ONLY_CAUSE_FIELDS}
                for c in val]
    return val

class TestRuns(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        cls._base = pathlib.Path(cls._tmp_dir)

        # Copy data to a temp folder.
        cls.data_copy = cls._base / "data_copy"
        _copy_data(cls.data_copy)

        # Build run.
        cls.run_dir = cls._base / "runs" / "t1"
        cls.record = build_run(cls.data_copy, cls.run_dir, M=20, N=10, seed=5)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    # ── Test 1: aggregation equals direct evaluation ──────────────────────────
    def test_01_aggregation_equals_direct(self):
        """evaluate_run equals evaluate_worlds for D01 in every key
        except weights_source and 'run'."""
        # Load a second copy with the run's worlds.csv.
        second_copy = self._base / "data_copy2"
        _copy_data(second_copy)
        shutil.copy(self.run_dir / "worlds.csv", second_copy / "worlds.csv")
        try:
            db_direct = load_all(second_copy)
            direct = evaluate_worlds("D01", db_direct)
            db_base = load_all(self.data_copy)
            run_result = engine.runs.evaluate_run("D01", db_base, self.run_dir)
        finally:
            shutil.rmtree(second_copy, ignore_errors=True)

        # Every key from direct is in run_result with the same value,
        # except weights_source (which is "run") and "run" (extra key).
        for key, val in direct.items():
            if key == "weights_source":
                self.assertEqual(run_result["weights_source"], "run")
            elif key == "common_scale":
                continue  # run-only (grid); null in evaluate_worlds
            else:
                self.assertIn(key, run_result,
                              msg=f"Key {key!r} missing from run_result")
                self.assertEqual(
                    _without_run_only(key, run_result[key]),
                    _without_run_only(key, val),
                    msg=f"Key {key!r}: expected {val!r}, got {run_result[key]!r}"
                )
        # run key is extra
        self.assertIn("run", run_result)

    # ── Test 2: rebuild_worlds_csv gives identical bytes ─────────────────────
    def test_02_rebuild_worlds_csv_bytes_equal(self):
        """rebuild_worlds_csv produces bytes equal to the run's worlds.csv."""
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

    # ── Test 3: row counts and weight sums ────────────────────────────────────
    def test_03_row_counts_and_weight_sums(self):
        """results.csv has distinct_worlds data rows; row_map has record['rows'] rows;
        sum of row_map weights equals sum of worlds.csv weights;
        every world_index in row_map exists in results.csv."""
        with open(self.run_dir / "results.csv", encoding="utf-8", newline="") as fh:
            results_rows = list(csv.DictReader(fh))
        with open(self.run_dir / "row_map.csv", encoding="utf-8", newline="") as fh:
            row_map_rows = list(csv.DictReader(fh))
        with open(self.run_dir / "worlds.csv", encoding="utf-8", newline="") as fh:
            worlds_rows = list(csv.DictReader(fh))

        self.assertEqual(len(results_rows), self.record["distinct_worlds"])
        self.assertEqual(len(row_map_rows), self.record["rows"])

        # Weight sums.
        worlds_weight_sum = sum(int(r["weight"]) for r in worlds_rows)
        row_map_weight_sum = sum(int(r["weight"]) for r in row_map_rows)
        self.assertEqual(worlds_weight_sum, row_map_weight_sum)

        # Every world_index in row_map exists in results.csv.
        results_indices = {r["world_index"] for r in results_rows}
        for rm in row_map_rows:
            self.assertIn(rm["world_index"], results_indices,
                          f"world_index {rm['world_index']} from row_map not in results")

    # ── Test 4: check_run passes on fresh run ─────────────────────────────────
    def test_04_check_run_passes_fresh(self):
        """check_run passes on the fresh run."""
        fp = engine.runs.check_run(self.run_dir, self.data_copy)
        self.assertIn("version", fp)

    # ── Test 5: check_run passes after CRLF and BOM ───────────────────────────
    def test_05_check_run_passes_crlf_and_bom(self):
        """check_run passes after converting orders.csv to CRLF and adding a BOM."""
        orders_path = self.data_copy / "orders.csv"
        orig = orders_path.read_bytes()
        try:
            # Normalise to LF first, then convert to CRLF.
            lf_content = orig.replace(b"\r\n", b"\n")
            crlf_content = lf_content.replace(b"\n", b"\r\n")
            orders_path.write_bytes(crlf_content)
            fp = engine.runs.check_run(self.run_dir, self.data_copy)
            self.assertIn("version", fp)

            # Add a UTF-8 BOM.
            bom_content = b"\xef\xbb\xbf" + crlf_content
            orders_path.write_bytes(bom_content)
            fp = engine.runs.check_run(self.run_dir, self.data_copy)
            self.assertIn("version", fp)
        finally:
            orders_path.write_bytes(orig)

    # ── Test 6: check_run fails after changing orders.csv ─────────────────────
    def test_06_check_run_fails_changed_orders(self):
        """check_run fails after changing a cell; message contains 'orders.csv'
        and 'python -m montecarlo.run'."""
        orders_path = self.data_copy / "orders.csv"
        orig = orders_path.read_bytes()
        try:
            with open(orders_path, "a", encoding="utf-8", newline="") as fh:
                fh.write("SO_FAKE,P01,WH01,2026-11-09,1,2026-11-21,1\n")
            with self.assertRaises(ValueError) as ctx:
                engine.runs.check_run(self.run_dir, self.data_copy)
            msg = str(ctx.exception)
            self.assertIn("orders.csv", msg)
            self.assertIn("python -m montecarlo.run", msg)
        finally:
            orders_path.write_bytes(orig)

    # ── Test 7: check_run on results.csv changes ──────────────────────────────
    def test_07_check_run_results_csv(self):
        """check_run fails after appending to results.csv (message has 'results.csv');
        passes after only converting results.csv to CRLF."""
        results_path = self.run_dir / "results.csv"
        orig = results_path.read_bytes()
        try:
            # Append a line.
            results_path.write_bytes(orig + b"extra_line\n")
            with self.assertRaises(ValueError) as ctx:
                engine.runs.check_run(self.run_dir, self.data_copy)
            self.assertIn("results.csv", str(ctx.exception))

            # Only CRLF conversion: should pass.
            crlf = orig.replace(b"\n", b"\r\n")
            results_path.write_bytes(crlf)
            fp = engine.runs.check_run(self.run_dir, self.data_copy)
            self.assertIn("version", fp)
        finally:
            results_path.write_bytes(orig)

    # ── Test 8: check_run reports changed/added code ──────────────────────────
    def test_08_check_run_reports_code_changes(self):
        """check_run reports 'engine/loader.py' when its hash is edited;
        reports a file under 'added:' when its entry is removed."""
        # Work on a copy of the run folder so we don't corrupt the original.
        run_copy = self._base / "run_copy_t8"
        shutil.copytree(self.run_dir, run_copy)
        try:
            with open(run_copy / "fingerprint.json", encoding="utf-8") as fh:
                fp = json.load(fh)

            # Edit the hash for engine/loader.py.
            loader_key = "engine/loader.py"
            fp["code"][loader_key] = "0" * 64
            with open(run_copy / "fingerprint.json", "w", encoding="utf-8") as fh:
                json.dump(fp, fh, indent=2, sort_keys=True)

            with self.assertRaises(ValueError) as ctx:
                engine.runs.check_run(run_copy, self.data_copy)
            self.assertIn(loader_key, str(ctx.exception))

            # Remove an entry from code (simulates added: file).
            with open(run_copy / "fingerprint.json", encoding="utf-8") as fh:
                fp2 = json.load(fh)
            removed_key = loader_key
            del fp2["code"][removed_key]
            with open(run_copy / "fingerprint.json", "w", encoding="utf-8") as fh:
                json.dump(fp2, fh, indent=2, sort_keys=True)

            with self.assertRaises(ValueError) as ctx2:
                engine.runs.check_run(run_copy, self.data_copy)
            msg = str(ctx2.exception)
            self.assertIn("added:", msg)
            self.assertIn(removed_key, msg)
        finally:
            shutil.rmtree(run_copy, ignore_errors=True)

    # ── Test 9: run folder without fingerprint.json ───────────────────────────
    def test_09_no_fingerprint_raises(self):
        """check_run raises with 'did not finish' when fingerprint.json is absent."""
        empty_dir = self._base / "empty_run"
        empty_dir.mkdir(exist_ok=True)
        with self.assertRaises(ValueError) as ctx:
            engine.runs.check_run(empty_dir, self.data_copy)
        self.assertIn("did not finish", str(ctx.exception))

    # ── Test 10: build_run raises when worlds.csv exists ─────────────────────
    def test_10_build_run_raises_with_worlds_csv(self):
        """build_run raises when the data folder contains worlds.csv."""
        copy = self._base / "data_with_worlds"
        _copy_data(copy)
        shutil.copy(self.run_dir / "worlds.csv", copy / "worlds.csv")
        try:
            with self.assertRaises(ValueError) as ctx:
                build_run(copy, self._base / "runs" / "t10", M=10, N=5, seed=5)
            self.assertIn("worlds.csv", str(ctx.exception))
        finally:
            shutil.rmtree(copy, ignore_errors=True)

    # ── Test 11: selection ───────────────────────────────────────────────────
    def test_11_selection(self):
        """Full selection scenario with SELECTION_PATH set to a temporary file."""
        import engine.runs as runs_mod

        sel_file = self._base / "run_selection.json"
        another_data = self._base / "another_data"
        _copy_data(another_data)

        orig_sel_path = runs_mod.SELECTION_PATH
        try:
            # Write selection file pointing to our run folder.
            with open(sel_file, "w", encoding="utf-8") as fh:
                json.dump({"run": str(self.run_dir)}, fh)
            runs_mod.SELECTION_PATH = sel_file

            # selected_run_for(copy) returns the run folder.
            result = runs_mod.selected_run_for(self.data_copy)
            self.assertEqual(result.resolve(), self.run_dir.resolve())

            # get_world_risk has weights_source "run".
            db_base = load_all(self.data_copy)
            wr = get_world_risk("D01", data_dir=self.data_copy)
            self.assertEqual(wr["weights_source"], "run")

            # expected_late_orders match test 1.
            second_copy = self._base / "data_copy_t11"
            _copy_data(second_copy)
            shutil.copy(self.run_dir / "worlds.csv", second_copy / "worlds.csv")
            try:
                db_direct = load_all(second_copy)
                direct = evaluate_worlds("D01", db_direct)
            finally:
                shutil.rmtree(second_copy, ignore_errors=True)

            for opt_r, opt_d in zip(wr["options"], direct["options"]):
                self.assertEqual(
                    opt_r["expected_late_orders"],
                    opt_d["expected_late_orders"],
                    msg=f"expected_late_orders mismatch for {opt_r['scenario_id']}"
                )

            # scope_note contains the run path.
            run_result = engine.runs.evaluate_run("D01", load_all(self.data_copy),
                                                  self.run_dir)
            run_path_in_note = run_result["run"]
            self.assertIn(run_path_in_note, wr["scope_note"])

            # selected_run_for another data folder returns None.
            self.assertIsNone(runs_mod.selected_run_for(another_data))

            # worlds.csv added to the copy -> ValueError.
            shutil.copy(self.run_dir / "worlds.csv",
                        self.data_copy / "worlds.csv")
            try:
                with self.assertRaises(ValueError):
                    runs_mod.selected_run_for(self.data_copy)
            finally:
                (self.data_copy / "worlds.csv").unlink()

            # Malformed JSON.
            sel_file.write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                runs_mod.selected_run_for(self.data_copy)

            # Missing "run" key.
            with open(sel_file, "w", encoding="utf-8") as fh:
                json.dump({"foo": "bar"}, fh)
            with self.assertRaises(ValueError):
                runs_mod.selected_run_for(self.data_copy)

            # Extra key.
            with open(sel_file, "w", encoding="utf-8") as fh:
                json.dump({"run": str(self.run_dir), "extra": 1}, fh)
            with self.assertRaises(ValueError):
                runs_mod.selected_run_for(self.data_copy)

            # Missing run folder.
            with open(sel_file, "w", encoding="utf-8") as fh:
                json.dump({"run": "/nonexistent/path/to/run"}, fh)
            with self.assertRaises(ValueError):
                runs_mod.selected_run_for(self.data_copy)

            # SELECTION_PATH = None -> None.
            runs_mod.SELECTION_PATH = None
            self.assertIsNone(runs_mod.selected_run_for(self.data_copy))

        finally:
            runs_mod.SELECTION_PATH = None
            shutil.rmtree(another_data, ignore_errors=True)

    def tearDown(self):
        # Restore SELECTION_PATH = None after each test.
        engine.runs.SELECTION_PATH = None

    # ── Test 12: two disruptions ──────────────────────────────────────────────
    def test_12_two_disruptions(self):
        """results.csv has columns for every scenario of D01 and D02;
        evaluate_run equals evaluate_worlds for both."""
        copy2 = self._base / "data_copy_d02"
        _copy_data(copy2)
        # Append rows.
        _append_line(copy2 / "purchase_orders.csv",
                     "PO02,OF03,WH01,2026-11-05,50,2026-11-10")
        _append_line(copy2 / "disruptions.csv",
                     "D02,PO02,2026-11-09,2026-11-13,test")
        _append_line(copy2 / "causes.csv",
                     "K1,business,purchase_order,PO02")

        run_dir2 = self._base / "runs" / "t12"
        try:
            rec2 = build_run(copy2, run_dir2, M=10, N=10, seed=5)

            with open(run_dir2 / "results.csv", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames
                result_rows = list(reader)

            # Find disrupted scenarios in db.
            db2 = load_all(copy2)
            disrupted_sids = [
                sid for sid, s in db2["scenarios"].items()
                if s.get("disruption_id", "") in db2["disruptions"]
            ]

            # results.csv must have late_orders and extra_cost for every disrupted sid.
            for sid in disrupted_sids:
                self.assertIn(f"late_orders.{sid}", header,
                              f"Missing late_orders.{sid} in results.csv header")
                self.assertIn(f"extra_cost.{sid}", header,
                              f"Missing extra_cost.{sid} in results.csv header")

            # evaluate_run equals evaluate_worlds for D01 and D02.
            for did in db2["disruptions"]:
                # Build a copy with worlds.csv for direct comparison.
                direct_copy = self._base / f"data_copy_direct_{did}"
                _copy_data(direct_copy)
                _append_line(direct_copy / "purchase_orders.csv",
                             "PO02,OF03,WH01,2026-11-05,50,2026-11-10")
                _append_line(direct_copy / "disruptions.csv",
                             "D02,PO02,2026-11-09,2026-11-13,test")
                _append_line(direct_copy / "causes.csv",
                             "K1,business,purchase_order,PO02")
                shutil.copy(run_dir2 / "worlds.csv",
                            direct_copy / "worlds.csv")
                try:
                    db_direct = load_all(direct_copy)
                    direct = evaluate_worlds(did, db_direct)
                    run_result = engine.runs.evaluate_run(did, db2, run_dir2)
                finally:
                    shutil.rmtree(direct_copy, ignore_errors=True)

                for key, val in direct.items():
                    if key in ("weights_source", "common_scale"):
                        continue
                    self.assertIn(key, run_result,
                                  msg=f"[{did}] Key {key!r} missing")
                    self.assertEqual(
                        _without_run_only(key, run_result[key]),
                        _without_run_only(key, val),
                        msg=f"[{did}] Key {key!r}: expected {val!r}, got {run_result[key]!r}"
                    )

        finally:
            shutil.rmtree(copy2, ignore_errors=True)
            shutil.rmtree(run_dir2, ignore_errors=True)


    # ── Test 13: evaluate_run unknown disruption_id ───────────────────────────
    def test_13_evaluate_run_unknown_disruption_id(self):
        """evaluate_run and get_world_risk raise ValueError for unknown disruption_id."""
        import engine.runs as runs_mod

        sel_file = self._base / "run_sel_t13.json"
        with open(sel_file, "w", encoding="utf-8") as fh:
            json.dump({"run": str(self.run_dir)}, fh)
        runs_mod.SELECTION_PATH = sel_file
        try:
            # Direct evaluate_run raises.
            db = load_all(self.data_copy)
            with self.assertRaises(ValueError) as ctx:
                engine.runs.evaluate_run("D99", db, self.run_dir)
            self.assertIn("D99", str(ctx.exception))

            # get_world_risk also raises (goes through evaluate_run).
            with self.assertRaises(ValueError):
                get_world_risk("D99", data_dir=self.data_copy)
        finally:
            runs_mod.SELECTION_PATH = None

    # ── Test 14: build_run refuses out_dir inside data_dir ───────────────────
    def test_14_build_run_refuses_out_inside_data(self):
        """build_run raises and creates no folder when out_dir is inside data_dir."""
        copy = self._base / "data_copy_t14"
        _copy_data(copy)
        out = copy / "runs" / "x"
        try:
            with self.assertRaises(ValueError) as ctx:
                build_run(copy, out, M=2, N=2, seed=5)
            self.assertIn("inside data_dir", str(ctx.exception))
            # The runs/ subfolder must not have been created.
            self.assertFalse((copy / "runs").exists(),
                             "build_run created a folder before the guard check")
        finally:
            shutil.rmtree(copy, ignore_errors=True)

    # ── Test 15: check_run --out path formatting ──────────────────────────────
    def test_15_rerun_command_path_formatting(self):
        """--out is absolute when run folder is outside REPO_ROOT;
        unit test for POSIX-relative formatting for a path inside REPO_ROOT."""
        # (a) Run folder is outside repo — existing tests use temp dirs.
        # Trigger a check_run failure and verify --out contains the absolute path.
        results_path = self.run_dir / "results.csv"
        orig = results_path.read_bytes()
        try:
            results_path.write_bytes(orig + b"extra\n")
            with self.assertRaises(ValueError) as ctx:
                engine.runs.check_run(self.run_dir, self.data_copy)
            msg = str(ctx.exception)
            # The run_dir is outside REPO_ROOT so --out must be its absolute str form.
            self.assertIn(str(self.run_dir), msg)
        finally:
            results_path.write_bytes(orig)

        # (b) Unit test of path formatting for a path inside REPO_ROOT
        #     (no folder needs to exist).
        inside_path = engine.runs.REPO_ROOT / "runs" / "demo"
        try:
            posix_rel = inside_path.relative_to(engine.runs.REPO_ROOT).as_posix()
        except ValueError:
            posix_rel = str(inside_path)
        self.assertEqual(posix_rel, "runs/demo")


if __name__ == "__main__":
    unittest.main()
