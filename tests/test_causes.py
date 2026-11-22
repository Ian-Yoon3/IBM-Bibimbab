"""Tests for engine.causes.load_causes (stage 2, step P1)."""

import pathlib
import shutil
import tempfile
import unittest

from engine.causes import load_causes
from engine.loader import load_all
from montecarlo.estimate import estimate

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"


def _db():
    return load_all(DATA_DIR)


def _make_data_copy(causes_content=None) -> pathlib.Path:
    """Copy DATA_DIR to a temp dir and optionally write causes_content."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(DATA_DIR, tmp / "data", dirs_exist_ok=True)
    if causes_content is not None:
        (tmp / "data" / "causes.csv").write_text(causes_content, encoding="utf-8")
    return tmp / "data"


class TestLoadCausesDemoData(unittest.TestCase):
    """The demo data gives 4 rows in the expected order."""

    @classmethod
    def setUpClass(cls):
        db = _db()
        cls.rows = load_causes(DATA_DIR, db)

    def test_returns_four_rows(self):
        self.assertEqual(len(self.rows), 4)

    def test_row0_K1_purchase_order_PO01(self):
        r = self.rows[0]
        self.assertEqual(r["cause_id"],    "K1")
        self.assertEqual(r["day_unit"],    "business")
        self.assertEqual(r["target_type"], "purchase_order")
        self.assertEqual(r["target_id"],   "PO01")
        self.assertEqual(r["source_id"],   "OF01")
        self.assertTrue(r["business"])

    def test_row1_K1_offer_OF02(self):
        r = self.rows[1]
        self.assertEqual(r["cause_id"],    "K1")
        self.assertEqual(r["day_unit"],    "business")
        self.assertEqual(r["target_type"], "offer")
        self.assertEqual(r["target_id"],   "OF02")
        self.assertEqual(r["source_id"],   "OF02")
        self.assertTrue(r["business"])

    def test_row2_K2_lane_LN01(self):
        r = self.rows[2]
        self.assertEqual(r["cause_id"],    "K2")
        self.assertEqual(r["day_unit"],    "calendar")
        self.assertEqual(r["target_type"], "lane")
        self.assertEqual(r["target_id"],   "LN01")
        self.assertEqual(r["source_id"],   "LN01")
        self.assertFalse(r["business"])

    def test_row3_K2_lane_LN02(self):
        r = self.rows[3]
        self.assertEqual(r["cause_id"],    "K2")
        self.assertEqual(r["day_unit"],    "calendar")
        self.assertEqual(r["target_type"], "lane")
        self.assertEqual(r["target_id"],   "LN02")
        self.assertEqual(r["source_id"],   "LN02")
        self.assertFalse(r["business"])

    def test_lead_days_populated(self):
        """lead_days comes from the referenced offer or lane."""
        db = _db()
        rows = self.rows
        # row0: PO01 -> offer OF01 -> lead_days of OF01
        of01_lead = db["offers"]["OF01"]["lead_days"]
        self.assertEqual(rows[0]["lead_days"], of01_lead)
        # row1: offer OF02 -> lead_days of OF02
        of02_lead = db["offers"]["OF02"]["lead_days"]
        self.assertEqual(rows[1]["lead_days"], of02_lead)
        # row2: lane LN01 -> lead_days
        ln01_lead = db["lanes"]["LN01"]["lead_days"]
        self.assertEqual(rows[2]["lead_days"], ln01_lead)
        # row3: lane LN02 -> lead_days
        ln02_lead = db["lanes"]["LN02"]["lead_days"]
        self.assertEqual(rows[3]["lead_days"], ln02_lead)


class TestLoadCausesNoCsv(unittest.TestCase):
    """No causes.csv gives None, and load_all still works."""

    def test_no_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            shutil.copytree(DATA_DIR, td / "data", dirs_exist_ok=True)
            (td / "data" / "causes.csv").unlink()
            db = _db()
            result = load_causes(td / "data", db)
            self.assertIsNone(result)

    def test_load_all_without_causes_csv(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            shutil.copytree(DATA_DIR, td / "data", dirs_exist_ok=True)
            (td / "data" / "causes.csv").unlink()
            db = load_all(td / "data")
            self.assertIsNone(db["causes"])


# ---------------------------------------------------------------------------
# Validation rules a – i
# ---------------------------------------------------------------------------

class TestValidationRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = _db()

    def _assert_error(self, content: str, *fragments):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            (td / "causes.csv").write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_causes(td, self.db)
            msg = str(ctx.exception)
            self.assertTrue(msg.startswith("data/causes.csv: "),
                f"message does not start with 'data/causes.csv: ': {msg!r}")
            for frag in fragments:
                self.assertIn(frag, msg)

    # (a) header exactly cause_id,day_unit,target_type,target_id
    def test_a_bad_header(self):
        content = "cause_id,day_unit,target_type\nK1,business,offer,OF02\n"
        self._assert_error(content)

    # (b) no empty field in any row
    def test_b_empty_cause_id(self):
        content = "cause_id,day_unit,target_type,target_id\n,business,offer,OF02\n"
        self._assert_error(content, "cause_id")

    def test_b_empty_day_unit(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,,offer,OF02\n"
        self._assert_error(content, "day_unit")

    def test_b_empty_target_type(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,business,,OF02\n"
        self._assert_error(content, "target_type")

    def test_b_empty_target_id(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,business,offer,\n"
        self._assert_error(content, "target_id")

    # (c) day_unit is "business" or "calendar"
    def test_c_invalid_day_unit(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,weekly,offer,OF02\n"
        self._assert_error(content, "day_unit")

    # (d) target_type is purchase_order, offer or lane
    def test_d_invalid_target_type(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,business,ship,OF02\n"
        self._assert_error(content, "target_type")

    # (e) purchase_order and offer require business, lane requires calendar
    def test_e_offer_requires_business(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,calendar,offer,OF02\n"
        self._assert_error(content, "business", "OF02")

    def test_e_purchase_order_requires_business(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,calendar,purchase_order,PO01\n"
        self._assert_error(content, "business", "PO01")

    def test_e_lane_requires_calendar(self):
        content = "cause_id,day_unit,target_type,target_id\nK2,business,lane,LN01\n"
        self._assert_error(content, "calendar", "LN01")

    # (f) one cause has one day_unit
    def test_f_conflicting_day_unit_in_same_cause(self):
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,purchase_order,PO01\n"
            "K1,calendar,lane,LN01\n"
        )
        self._assert_error(content, "K1")

    # (g) the pair (target_type, target_id) appears at most once
    def test_g_duplicate_target_pair(self):
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K2,calendar,lane,LN01\n"
            "K2,calendar,lane,LN01\n"
        )
        self._assert_error(content, "LN01", "more than once")

    # (h) target_id exists
    def test_h_unknown_purchase_order(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,business,purchase_order,PO99\n"
        self._assert_error(content, "PO99")

    def test_h_unknown_offer(self):
        content = "cause_id,day_unit,target_type,target_id\nK1,business,offer,OF99\n"
        self._assert_error(content, "OF99")

    def test_h_unknown_lane(self):
        content = "cause_id,day_unit,target_type,target_id\nK2,calendar,lane,LN99\n"
        self._assert_error(content, "LN99")

    # (i) a source belongs to one cause only
    def test_i_source_in_two_causes(self):
        # PO01 source = OF01; offer.OF01 source = OF01 — same source in K1 and K2
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,purchase_order,PO01\n"
            "K2,business,offer,OF01\n"
        )
        self._assert_error(content, "OF01")


class TestEstimatorRejectsOfferBusiness(unittest.TestCase):
    """A cause with an offer (business) and a lane (calendar) is rejected
    by the estimator path (via load_causes in load_all)."""

    def test_mixed_day_unit_cause_rejected(self):
        content = (
            "cause_id,day_unit,target_type,target_id\n"
            "K1,business,purchase_order,PO01\n"
            "K1,calendar,lane,LN01\n"
        )
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            shutil.copytree(DATA_DIR, td / "data", dirs_exist_ok=True)
            (td / "data" / "causes.csv").write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                estimate(td / "data")
            self.assertIn("data/causes.csv: ", str(ctx.exception))


class TestEstimatorNoCauses(unittest.TestCase):
    """estimate() on a data folder without causes.csv raises the step 3 error."""

    def test_no_causes_raises(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            shutil.copytree(DATA_DIR, td / "data", dirs_exist_ok=True)
            (td / "data" / "causes.csv").unlink()
            with self.assertRaises(ValueError) as ctx:
                estimate(td / "data")
            self.assertIn("data/causes.csv: file not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
