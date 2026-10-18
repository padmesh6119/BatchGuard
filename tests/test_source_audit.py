import json
import unittest

import pandas as pd

from src.source_audit import FIELDS, check_rows, compare, decode_response, field_text


class SourceAuditTests(unittest.TestCase):
    def official(self, **changes):
        fields = {name: "" for name in FIELDS["nsq"].values()}
        return {**fields, "str_product_name": "Product", "str_batch_no": "00123",
                "dt_reporting_month_year": "JUL-2025", "dt_manufacturing_date": "Jun-2025", **changes}

    def local(self, row, identity="record1"):
        return {**{field: row[remote] for field, remote in FIELDS["nsq"].items()},
                "build_record_id": identity, "collection_month": "2025-07", "source_category": "central_nsq"}

    def test_duplicate_counts_are_not_hidden_and_batch_codes_are_exact(self):
        row = self.official()
        local = self.local(row)
        result = compare(pd.DataFrame([local]), [row, row], "nsq", "2025-07")
        self.assertEqual((result["exact_field_matches"], result["official_records_not_represented"]), (1, 1))
        local["batch_no"] = "123"
        result = compare(pd.DataFrame([local]), [row], "nsq", "2025-07")
        self.assertEqual(result["exact_field_matches"], 0)
        self.assertEqual(result["discrepancies"][0]["exact_identity_candidates"], 0)

    def test_explicit_month_format_equivalence_does_not_drop_a_real_day(self):
        row = self.official()
        local = self.local(row)
        local["manufacture_date_raw"] = "2025-06-01 00:00:00"
        local["reporting_month"] = "2025-07-01"
        self.assertEqual(compare(pd.DataFrame([local]), [row], "nsq", "2025-07")["exact_field_matches"], 1)
        local["manufacture_date_raw"] = "2025-06-15 00:00:00"
        result = compare(pd.DataFrame([local]), [row], "nsq", "2025-07")
        self.assertEqual(result["exact_field_matches"], 0)
        self.assertIn("manufacture_date_raw", result["discrepancies"][0]["field_differences"])

    def test_labeled_spurious_cells_and_missing_markers_are_explicit(self):
        self.assertEqual(field_text("manufacture_date_raw", "Manufacturing Date: Sep-2024"), "2024-09")
        self.assertEqual(field_text("manufacturer_name_raw", "Manufacturer Name: N/A"), "")
        self.assertEqual(field_text("batch_no", "N/A"), "n/a")
        self.assertNotEqual(field_text("manufacturer_raw", "FIRM ? STREET"), field_text("manufacturer_raw", "FIRM – STREET"))

    def test_schema_wrong_month_and_encoding_are_checked(self):
        row = self.official()
        with self.assertRaisesRegex(ValueError, "different reporting month"):
            check_rows([row], "nsq", "2026-07")
        with self.assertRaisesRegex(ValueError, "schema"):
            check_rows([{}], "nsq", "2025-07")
        raw = json.dumps({"aaData": [self.official(str_product_name="Product ®")]}, ensure_ascii=False).encode("cp1252")
        rows, encoding = decode_response(raw)
        self.assertEqual(rows[0]["str_product_name"], "Product ®")
        self.assertEqual(encoding, "cp1252-fallback")


if __name__ == "__main__":
    unittest.main()
