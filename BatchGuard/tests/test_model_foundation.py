import copy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from model_foundation import (HISTORY_FEATURES, SCAN_FEATURES, HELDOUT_SCENARIOS,
                              HISTORY_TASK, history_examples, make_scan_corpus, validate_examples,
                              prepare, load_model_inputs)
from decision_core import build_decision_queue
from scan_features import extract_scan_features
from src.normalize_failure_types import classify
from src.process_month import normalize_sheet


def historical_fixture():
    rows = []
    for month in pd.period_range("2025-07", "2026-08", freq="M").astype(str):
        for manufacturer in ["CONTINUING", f"NEW-{month}"]:
            rows.append(dict(build_record_id=f"{month}-{manufacturer}", collection_month=month,
                             manufacturer_name_normalized=manufacturer, source_category="central_nsq",
                             product="Product", batch_no=f"BATCH-{month}", failure_mapping_status="keyword_mapped"))
    return pd.DataFrame(rows)


class FoundationTests(unittest.TestCase):
    def test_future_records_do_not_change_earlier_features(self):
        df = historical_fixture()
        initial = history_examples(df)
        future = df.iloc[[-1]].copy()
        future["collection_month"] = "2026-08"
        changed = history_examples(pd.concat([df, future, future], ignore_index=True))
        before = initial[initial.target_month.lt("2026-08")].reset_index(drop=True)
        after = changed[changed.target_month.lt("2026-08")].reset_index(drop=True)
        pd.testing.assert_frame_equal(before, after)

    def test_training_contract_and_split_isolation(self):
        df = historical_fixture()
        history = history_examples(df)
        scans, episodes = make_scan_corpus(df, episodes_per_scenario=3)
        validate_examples(history, scans, episodes)
        self.assertTrue(history.feature_cutoff_month.lt(history.target_month).all())
        self.assertFalse(set(HISTORY_FEATURES) & {"label", "target_report_count", "manufacturer_key", "split"})
        self.assertFalse(set(SCAN_FEATURES) & {"scenario", "label", "episode_id", "baseline_rule_prediction"})
        self.assertEqual(set(scans.loc[scans.scenario.isin(HELDOUT_SCENARIOS), "split"]), {"test"})

    def test_features_do_not_depend_on_identifying_strings(self):
        _, episodes = make_scan_corpus(historical_fixture(), episodes_per_scenario=2)
        episode = next(e for e in episodes if e["scenario"] == "clone_copy")
        events = copy.deepcopy(episode["events"])
        expected = extract_scan_features(events)
        for event in events:
            event["event_id"] = "RENAMED-"+event["event_id"]
            event["pack_id"] = "RENAMED-"+event["pack_id"]
            event["source_id"] = "RENAMED-"+event["source_id"]
            event["product"] = "Different reference product"
        self.assertEqual(expected, extract_scan_features(events))

    def test_events_after_decision_time_are_excluded(self):
        _, episodes = make_scan_corpus(historical_fixture(), episodes_per_scenario=2)
        episode = next(e for e in episodes if e["scenario"] == "clone_copy")
        events = sorted(episode["events"], key=lambda e: e["event_time"])
        cutoff = datetime.fromisoformat(events[0]["event_time"]).timestamp()
        self.assertEqual(extract_scan_features(events, cutoff), extract_scan_features(events[:1], cutoff))

    def test_retries_preserve_unique_counts_and_distribution_has_no_pack_travel(self):
        _, episodes = make_scan_corpus(historical_fixture(), episodes_per_scenario=2)
        episode = next(e for e in episodes if e["scenario"] == "legitimate_distribution")
        features = extract_scan_features(episode["events"])
        self.assertEqual(features["max_events_per_pack"], 1)
        self.assertEqual(features["max_pack_distance_km"], 0)
        retried = extract_scan_features(episode["events"]+[episode["events"][0]])
        self.assertEqual(retried["unique_events"], features["unique_events"])
        self.assertGreater(retried["retry_fraction"], 0)

    def test_synthetic_corpus_reproduces_exactly(self):
        a, ea = make_scan_corpus(historical_fixture(), episodes_per_scenario=2, seed=7)
        b, eb = make_scan_corpus(historical_fixture(), episodes_per_scenario=2, seed=7)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(ea, eb)
        self.assertFalse(a.scenario.str.contains("flood").any())

    def test_parser_rejects_missing_core_headers(self):
        with self.assertRaisesRegex(ValueError, "required headers"):
            normalize_sheet(pd.DataFrame({"Wrong column": [1]}), "central", "2026-08", "test.xlsx")

    def test_endotoxin_abbreviation_does_not_match_drug_name(self):
        categories, _ = classify({"source_category": "central_nsq", "failure_type": "Assay of Betamethasone"})
        self.assertNotIn("bacterial_endotoxins", categories)
        categories, _ = classify({"source_category": "central_nsq", "failure_type": "BET"})
        self.assertIn("bacterial_endotoxins", categories)

    def test_combined_queue_has_three_separate_signals_and_capacity(self):
        df = historical_fixture()
        df["failure_categories"] = "assay"
        _, episodes = make_scan_corpus(df, episodes_per_scenario=2)
        normal = next(e for e in episodes if e["scenario"] == "benign_repeat")
        clone = next(e for e in episodes if e["scenario"] == "clone_copy")
        queue = build_decision_queue(df, normal["events"] + clone["events"], capacity=1)
        self.assertEqual(len(queue), 1)
        for name in ["historical_risk", "scan_anomaly", "evidence_quality", "priority_score"]:
            self.assertIn(name, queue[0])
        self.assertIn("FOLLOWUP_SAMPLE_STATUS_UNKNOWN", queue[0]["reason_codes"])
        self.assertTrue(queue[0]["scan_simulated"])

    def test_bundle_separates_features_and_labels_and_reserves_test(self):
        df = historical_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "processed").mkdir(parents=True)
            pd.DataFrame({"build_record_id": df.build_record_id}).to_csv(root / "data" / "processed" / "all_months_provenance.csv", index=False)
            with patch("model_foundation.active_snapshot", return_value=(root, "test-snapshot")), \
                 patch("model_foundation.load_dataset", return_value=df):
                manifest = prepare(root / "bundle", episodes_per_scenario=2)
            self.assertFalse(manifest["training_performed"])
            x, y, metadata = load_model_inputs(root / "bundle", HISTORY_TASK)
            self.assertEqual(list(x.columns), HISTORY_FEATURES)
            self.assertEqual(len(x), len(y))
            with self.assertRaisesRegex(ValueError, "Reserve test"):
                load_model_inputs(root / "bundle", HISTORY_TASK, "test")
            load_model_inputs(root / "bundle", HISTORY_TASK, "test", final_evaluation=True)
            path = root / "bundle" / HISTORY_TASK / "train_X.csv"
            path.write_text(path.read_text()+"modified")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                load_model_inputs(root / "bundle", HISTORY_TASK)


if __name__ == "__main__":
    unittest.main()
