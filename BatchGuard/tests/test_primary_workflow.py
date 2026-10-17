from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from primary_workflow import followup_queue, chronological_coverage
from batchguard_engine import load_dataset
from refresh_data import main as refresh
from snapshot_store import ROOT, active_snapshot, publish_pointer, refresh_lock, validate_snapshot


def record(identity, month, manufacturer="FIRM A", product="Product", batch="Batch"):
    return {"build_record_id": identity, "collection_month": month, "manufacturer_name_normalized": manufacturer,
            "product": product, "batch_no": batch, "source_category": "central_nsq",
            "failure_categories": "assay", "failure_mapping_status": "keyword_mapped", "source_file": f"{month}_all.xlsx"}


class PrimaryWorkflowTests(unittest.TestCase):
    def test_queue_history_excludes_selected_and_future_months(self):
        initial = pd.DataFrame([record("a", "2026-01"), record("b", "2026-02"),
                                record("c", "2026-02", "FIRM B", "Other", "Other batch")])
        result = followup_queue(initial, "2026-02", 10)
        with_future = pd.concat([initial, pd.DataFrame([record(str(i), "2026-03", "FIRM B") for i in range(20)])])
        pd.testing.assert_frame_equal(result, followup_queue(with_future, "2026-02", 10))
        self.assertEqual(int(result.loc[result.manufacturer_key.eq("FIRM A"), "prior_nsq_records"].iloc[0]), 1)
        self.assertEqual(int(result.loc[result.manufacturer_key.eq("FIRM B"), "prior_nsq_records"].iloc[0]), 0)

    def test_unique_queue_preserves_multiple_source_records(self):
        df = pd.DataFrame([record("a", "2026-01"), record("b", "2026-01"),
                           record("c", "2026-01", batch="")])
        queue = followup_queue(df, "2026-01", 5)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.iloc[0].record_ids, "a | b")
        self.assertEqual(len(followup_queue(df, "2026-01", 0)), 0)
        self.assertTrue(followup_queue(df, "2026-01", 5, "spurious").empty)

    def test_chronological_coverage_accounts_for_new_manufacturers(self):
        df = pd.DataFrame([record("a", "2026-01"), record("b", "2026-02"),
                           record("c", "2026-02", "FIRM B")])
        row = chronological_coverage(df, 1).iloc[0]
        self.assertEqual(row.seen_manufacturer_records, 1)
        self.assertEqual(row.new_or_unavailable_manufacturer_records, 1)
        self.assertEqual(row.index_captured_records, 1)
        self.assertEqual(row.random_expected_captured_records, 1)
        self.assertEqual(row.training_through, "2026-01")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data" / "raw").mkdir(parents=True)
        for name in ("2025-08_all.xlsx", "2026-08_all.xlsx"):
            shutil.copy2(ROOT / "data" / "raw" / name, self.root / "data" / "raw" / name)

    def tearDown(self):
        self.temporary.cleanup()

    def build(self):
        with redirect_stdout(io.StringIO()):
            return refresh(self.root)

    def test_failure_keeps_previous_snapshot_and_releases_lock(self):
        old = self.build()
        with patch("refresh_data.run_pipeline", side_effect=RuntimeError("injected build failure")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.build()
        location, identity = active_snapshot(self.root)
        self.assertEqual(identity, old["snapshot_id"])
        validate_snapshot(location)
        self.assertFalse((self.root / "data" / ".refresh.lock").exists())
        self.assertFalse(list((self.root / "data" / "snapshots").glob(".build-*")))

    def test_removed_raw_month_does_not_survive_and_rollback_works(self):
        first = self.build()
        (self.root / "data" / "raw" / "2025-08_all.xlsx").unlink()
        second = self.build()
        self.assertEqual(second["summary"]["months"], ["2026-08"])
        self.assertEqual(second["summary"]["analytical_records"], 221)
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        publish_pointer(self.root, first["snapshot_id"])
        self.assertEqual(active_snapshot(self.root)[1], first["snapshot_id"])

    def test_legacy_layout_and_writer_lock(self):
        self.assertEqual(active_snapshot(self.root), (self.root, "legacy-local-files"))
        with refresh_lock(self.root):
            with self.assertRaisesRegex(RuntimeError, "locked"):
                with refresh_lock(self.root):
                    pass
        self.assertFalse((self.root / "data" / ".refresh.lock").exists())

    def test_reader_can_pin_old_snapshot_after_publication_switch(self):
        self.build()
        original = active_snapshot(self.root)
        (self.root / "data" / "raw" / "2025-08_all.xlsx").unlink()
        self.build()
        self.assertEqual(len(load_dataset(original)), 318)
        self.assertEqual(len(load_dataset(active_snapshot(self.root))), 221)

    def test_modified_snapshot_is_rejected(self):
        manifest = self.build()
        location, _ = active_snapshot(self.root)
        name = next(iter(manifest["outputs"]))
        with (location / name).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            validate_snapshot(location)


if __name__ == "__main__":
    unittest.main()
