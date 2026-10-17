"""Regression checks for the staged-review failures found during source review."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import openpyxl

from review_integrity import check_integrity, read_source_records

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "PDF_CLEANING_REVIEW"


class ReviewIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = read_source_records(ROOT / "PDF")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="batchguard-review-regression-")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "review"
        shutil.copytree(OUTPUT, self.output, ignore=shutil.ignore_patterns("tools", "__pycache__"))

    def errors(self):
        return check_integrity(self.output, ROOT / "PDF", self.sources)

    def edit_provenance(self, change):
        path = self.output / "evidence/record_provenance.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        change(rows)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_corrected_staging_passes(self):
        self.assertEqual([], self.errors())

    def test_bad_overflow_repair_is_rejected(self):
        path = self.output / "workbooks/2024-10_all.xlsx"
        workbook = openpyxl.load_workbook(path)
        workbook["state"]["B14"] = "Co Vitamin B mplex Tablets N.F.I"
        workbook.save(path)
        workbook.close()
        self.assertTrue(any("Workbook/source content mismatch" in error for error in self.errors()))

    def test_wrong_product_in_review_report_is_rejected(self):
        path = self.output / "reports/manual_review.csv"
        text = path.read_text(encoding="utf-8-sig")
        text = text.replace("Vitamin C Injection IP and Vitamin B12, Folic Acid and Niacinamide Injection (Eldervit-12 Injection )", "Ibuprofen Tablets IP 400 mg")
        path.write_text(text, encoding="utf-8-sig")
        self.assertTrue(any("Incorrect manual-review product" in error for error in self.errors()))

    def test_missing_review_links_are_rejected(self):
        def change(rows):
            for row in rows:
                row["review_issue_ids"] = []
        self.edit_provenance(change)
        self.assertTrue(any("review linkage" in error for error in self.errors()))

    def test_duplicate_mapping_with_same_row_count_is_rejected(self):
        self.edit_provenance(lambda rows: rows.__setitem__(1, dict(rows[0])))
        self.assertIn("Duplicate provenance row mapping.", self.errors())

    def test_hash_mismatch_is_rejected(self):
        path = self.output / "reports/source_manifest.csv"
        text = path.read_text(encoding="utf-8-sig")
        import csv
        first = next(csv.DictReader(text.splitlines()))["sha256"]
        path.write_text(text.replace(first, "0" * 64), encoding="utf-8-sig")
        self.assertTrue(any("manifest hash mismatch" in error for error in self.errors()))

    def test_fabricated_raw_evidence_is_rejected(self):
        self.edit_provenance(lambda rows: rows[0].__setitem__("relevant_raw_text", "[]"))
        self.assertTrue(any("Raw PDF table evidence mismatch" in error for error in self.errors()))

    def test_unresolved_record_cannot_be_marked_clean(self):
        def change(rows):
            next(row for row in rows if "REV-004" in row["review_issue_ids"])["parse_status"] = "clean"
        self.edit_provenance(change)
        self.assertTrue(any("Review status mismatch" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
