from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from decision_core import TrainedModels, build_decision_queue, fuse, rank_candidates
from inspection_stream import ScanEvent
from model_foundation import HISTORY_FEATURES, HISTORY_TASK, history_features, load_model_inputs, make_scan_corpus, prepare
from snapshot_store import ROOT
from test_model_foundation import historical_fixture
from train_models import choose_threshold, selection_weights, train
import replay


def build_bundle(root, df):
    (root / "data" / "processed").mkdir(parents=True)
    pd.DataFrame({"build_record_id": df.build_record_id}).to_csv(root / "data" / "processed" / "all_months_provenance.csv", index=False)
    with patch("model_foundation.active_snapshot", return_value=(root, "test-snapshot")), \
         patch("model_foundation.load_dataset", return_value=df):
        prepare(root / "bundle", episodes_per_scenario=6)
    return root / "bundle"


def fixture():
    df = historical_fixture()
    df["failure_categories"] = "assay"
    return df


class SelectionTests(unittest.TestCase):
    def test_tied_scores_share_remaining_slots(self):
        np.testing.assert_allclose(selection_weights([3, 1, 1, 1, 0], 2), [1, 1/3, 1/3, 1/3, 0])
        np.testing.assert_allclose(selection_weights([0, 0, 0, 0], 1), [.25]*4)
        np.testing.assert_allclose(selection_weights([2, 1], 10), [1, 1])
        np.testing.assert_allclose(selection_weights([2, 1], 0), [0, 0])

    def test_threshold_maximizes_f1_and_prefers_fewer_alerts_on_ties(self):
        y = np.array([0, 0, 1, 1])
        self.assertEqual(choose_threshold(y, np.array([.1, .2, .8, .9])), .8)
        self.assertEqual(choose_threshold(np.array([0, 1]), np.array([.5, .5])), .5)

    def test_fusion_policies(self):
        self.assertEqual(fuse("tiered", 90, 80, 50, False), 45)
        self.assertEqual(fuse("tiered", 0, 80, 0, True), 90)
        self.assertEqual(fuse("weighted", 100, 100, 100, True), 100)
        self.assertEqual(fuse("weighted", 100, 0, 100, False), 50)
        with self.assertRaises(ValueError):
            fuse("other", 1, 1, 1, True)


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.df = fixture()
        self.bundle = build_bundle(self.root, self.df)

    def tearDown(self):
        self.temporary.cleanup()

    def fit(self, name, backend="sklearn"):
        with patch("train_models.load_dataset", return_value=self.df):
            return train(self.bundle, self.root / name, backend)

    def test_training_selects_on_validation_and_exports_verified_models(self):
        card = self.fit("models")
        self.assertTrue(card["test_evaluated_once"])
        self.assertIn(card["history"]["selected"], card["history"]["candidate_validation_average_precision"])
        self.assertIn("trained_model", card["history"]["validation_average_precision_vs_baselines"])
        self.assertIn(card["fusion"]["selected_policy"], ("weighted", "tiered"))
        self.assertEqual(set(card["history"]["test"]), {"trained_model", "legacy_60_25_15_index", "most_past_records",
                                                         "most_recent_3_months", "random_expectation"})
        held_out = {f["scenario"] for f in card["scan"]["families"] if f["held_out_family"]}
        self.assertEqual(held_out, {"delayed_sync", "slow_copy"})
        with self.assertRaises(FileExistsError):
            self.fit("models")
        models = TrainedModels(self.root / "models")
        self.assertEqual(models.version, card["model_version"])
        (self.root / "models" / "scan_model.pkl").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            TrainedModels(self.root / "models")

    def test_model_backed_queue_ranks_clone_above_benign_and_keeps_signals_separate(self):
        self.fit("models")
        models = TrainedModels(self.root / "models")
        _, episodes = make_scan_corpus(self.df, episodes_per_scenario=2, seed=99)
        normal = next(e for e in episodes if e["scenario"] == "benign_repeat")
        clone = next(e for e in episodes if e["scenario"] == "clone_copy" and
                     e["events"][0]["batch_no"] != normal["events"][0]["batch_no"])
        offset = timedelta(seconds=max(e.timestamp for e in map(ScanEvent.parse, clone["events"]))
                           - max(e.timestamp for e in map(ScanEvent.parse, normal["events"])))
        normal["events"] = [dict(e, event_time=(datetime.fromisoformat(e["event_time"])+offset).isoformat())
                            for e in normal["events"]]
        ranked = rank_candidates(self.df, normal["events"] + clone["events"], models=models)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["batch_no"], clone["events"][0]["batch_no"])
        self.assertTrue(ranked[0]["scan_alert"])
        self.assertFalse(ranked[1]["scan_alert"])
        for item in ranked:
            self.assertIsNotNone(item["scan_probability"])
            self.assertEqual(item["fusion_version"], models.version)
            self.assertTrue(item["scan_simulated"])
            self.assertIn("(simulated scans)", item["state"])
        self.assertEqual(len(build_decision_queue(self.df, normal["events"] + clone["events"], 1, models=models)), 1)

    @unittest.skipUnless(importlib.util.find_spec("snapml"), "Snap ML not installed")
    def test_snapml_backend_trains_and_loads(self):
        card = self.fit("snap", "snapml")
        self.assertEqual(card["backend"], "snapml")
        self.assertTrue(card["history"]["selected"].startswith("snap_"))
        TrainedModels(self.root / "snap")


class ParityTests(unittest.TestCase):
    def test_live_history_features_match_prepared_bundle(self):
        bundle = ROOT / "data" / "training" / "foundation-ready-v1"
        manifest = json.loads((bundle / "manifest.json").read_text())
        location = ROOT / "data" / "snapshots" / manifest["snapshot_id"]
        if not location.is_dir():
            self.skipTest("Bundle snapshot not present locally.")
        from batchguard_engine import load_dataset
        df = load_dataset((location, manifest["snapshot_id"]))
        x, _, metadata = load_model_inputs(bundle, HISTORY_TASK, "validation")
        live = history_features(df, metadata["feature_cutoff_month"].iloc[0])
        live = live.set_index("manufacturer_key").loc[metadata["manufacturer_key"], HISTORY_FEATURES].reset_index(drop=True)
        pd.testing.assert_frame_equal(live, x, check_dtype=False)


class ReplayTests(unittest.TestCase):
    def test_demo_refuses_to_reuse_an_event_database(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ["replay.py", "demo", "--output", directory]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                replay.main()
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertGreater(report["accepted_new_events"], 0)
            with patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                replay.main()


if __name__ == "__main__":
    unittest.main()
