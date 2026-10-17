import copy
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from inspection_stream import InspectionStream, ReferenceIndex, ScanEvent, make_scenarios
from replay import run_replay


def reference():
    df = pd.DataFrame([{
        "build_record_id": str(i), "product": f"Product {i}", "batch_no": f"Batch {i}",
        "manufacturer_name_normalized": f"FIRM {i}", "source_category": "central_nsq"
    } for i in range(12)])
    priorities = pd.DataFrame({"manufacturer_key": [f"FIRM {i}" for i in range(12)],
                               "priority_index": list(range(12))})
    return df, ReferenceIndex(df, priorities)


def event(index=0, **changes):
    value = dict(event_id=f"E-{index}", pack_id="P-1", product="Product 0", batch_no="Batch 0",
                 manufacturer_key="FIRM 0", event_time=f"2026-09-01T12:{index:02}:00+00:00",
                 source_id="SOURCE-1", latitude=13.08, longitude=80.27, simulated=True)
    value.update(changes)
    return value


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.df, self.reference = reference()
        self.stream = InspectionStream(self.reference)

    def tearDown(self):
        self.stream.close()

    def test_retry_and_restart_do_not_consume_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            stream = InspectionStream(self.reference, path)
            self.assertFalse(stream.ingest(event())["duplicate_delivery"])
            stream.close()
            stream = InspectionStream(self.reference, path)
            self.assertTrue(stream.ingest(event())["duplicate_delivery"])
            self.assertEqual(stream.queue()[0]["event_count"], 1)
            stream.close()

    def test_conflicting_event_id_is_rejected(self):
        self.stream.ingest(event())
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.stream.ingest(event(product="Another product"))
        self.assertEqual(self.stream.queue()[0]["event_count"], 1)

    def test_distinct_packs_distribute_legitimately(self):
        self.stream.ingest(event())
        result = self.stream.ingest(event(1, pack_id="P-2", source_id="SOURCE-2", latitude=28.61, longitude=77.21))
        self.assertFalse(result["scan_anomaly"])
        self.assertEqual(self.stream.queue()[0]["evidence_tier"], 0)

    def test_unknown_reference_is_coverage_only(self):
        result = self.stream.ingest(event(product="Unknown product"))
        self.assertFalse(result["reference_match"])
        self.assertFalse(result["scan_anomaly"])

    def test_single_source_flood_cannot_become_corroborated(self):
        for i in range(12):
            result = self.stream.ingest(event(i, event_time=f"2026-09-01T12:00:{i:02}+00:00"))
        self.assertEqual(result["evidence_tier"], 1)
        self.assertFalse(result["corroborated"])
        self.assertEqual(self.stream.queue()[0]["evidence_tier"], 1)

    def test_pack_travel_with_two_sources_is_review_signal(self):
        self.stream.ingest(event())
        result = self.stream.ingest(event(1, source_id="SOURCE-2", latitude=28.61, longitude=77.21))
        self.assertEqual(result["evidence_tier"], 3)
        self.assertIn("PACK_TRAVEL_CONFLICT", result["reason_codes"])

    def test_out_of_order_arrival_retains_evidence(self):
        self.stream.ingest(event(1, source_id="SOURCE-2", latitude=28.61, longitude=77.21))
        result = self.stream.ingest(event())
        self.assertTrue(result["corroborated"])
        self.assertEqual(self.stream.queue()[0]["evidence_tier"], 3)

    def test_expired_support_cannot_keep_candidate_corroborated(self):
        self.stream.ingest(event())
        self.stream.ingest(event(1, source_id="SOURCE-2", latitude=28.61, longitude=77.21))
        self.stream.ingest(event(31, pack_id="P-2"))
        # At 12:31, the 12:00 supporting scan has expired; two different packs remain.
        self.assertEqual(self.stream.queue()[0]["evidence_tier"], 0)

    def test_capacity_and_identity_boundaries(self):
        self.stream.ingest(event())
        self.stream.ingest(event(1, manufacturer_key="DIFFERENT FIRM"))
        self.assertEqual(len(self.stream.queue()), 2)
        self.assertEqual(len(self.stream.queue(1)), 1)
        self.assertEqual(self.stream.queue(0), [])
        with self.assertRaises(ValueError):
            self.stream.queue(-1)

    def test_reference_and_history_use_same_identity_normalization(self):
        result = self.stream.ingest(event(product="product 1", batch_no="batch 1", manufacturer_key="firm 1"))
        self.assertTrue(result["reference_match"])
        self.assertEqual(result["historical_priority"], 1.0)

    def test_input_contract_rejects_bad_values(self):
        for changes in ({"latitude": float("nan")}, {"longitude": 181},
                        {"event_time": "2026-09-01T12:00:00"}, {"source_id": ""},
                        {"simulated": "false"}, {"latitude": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ScanEvent.parse(event(**changes))

    def test_database_cannot_mix_reference_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite"
            stream = InspectionStream(self.reference, path)
            stream.close()
            changed = copy.copy(self.reference)
            changed.snapshot_id = "different snapshot"
            with self.assertRaisesRegex(ValueError, "reference/policy"):
                InspectionStream(changed, path)

    def test_deterministic_scenarios_and_known_miss(self):
        a, truth = make_scenarios(self.df)
        b, other_truth = make_scenarios(self.df)
        self.assertEqual(a, b)
        self.assertEqual(truth, other_truth)
        report, queues = run_replay(a, truth, self.reference, ":memory:", 2)
        self.assertEqual(report["duplicate_deliveries"], 1)
        self.assertEqual(report["active_unique_candidates"], 6)
        self.assertEqual(report["detector"]["true_positives"], 2)
        self.assertEqual(report["detector"]["false_positives"], 0)
        self.assertEqual(report["detector"]["false_negatives"], 1)
        self.assertEqual(report["budget_comparison"]["fused"]["simulated_clone_candidates_captured"], 2)
        self.assertEqual(report["budget_comparison"]["raw_volume"]["simulated_clone_candidates_captured"], 1)
        self.assertEqual(len({c["candidate_id"] for c in queues["fused"]}), 2)
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
