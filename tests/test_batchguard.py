import copy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src import detector, ingest, layer_a, simulator
from src.common import DATA_RAW, OUTPUTS, selection_weights
from src.fusion import TrainedModels, build_decision_queue, fuse, live_window, load_models, queue_pool, rank_candidates, train_backend


def fixture():
    rows = []
    for month in pd.period_range("2025-07", "2026-08", freq="M").astype(str):
        for manufacturer in ["CONTINUING", f"NEW-{month}"]:
            rows.append(dict(build_record_id=f"{month}-{manufacturer}", collection_month=month,
                             manufacturer_name_normalized=manufacturer, source_category="central_nsq",
                             product="Product", batch_no=f"BATCH-{month}", failure_mapping_status="keyword_mapped",
                             failure_categories="assay", source_file=f"{month}_all.xlsx"))
    return pd.DataFrame(rows)


def record(identity, month, manufacturer="FIRM A", product="Product", batch="Batch"):
    return {"build_record_id": identity, "collection_month": month, "manufacturer_name_normalized": manufacturer,
            "product": product, "batch_no": batch, "source_category": "central_nsq", "failure_categories": "assay",
            "failure_mapping_status": "keyword_mapped", "source_file": f"{month}_all.xlsx"}


def episode(episodes, scenario):
    return next(e for e in episodes if e["scenario"] == scenario)


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "raw").mkdir()
        for name in ("2025-08_all.xlsx", "2026-08_all.xlsx"):
            shutil.copy2(DATA_RAW / name, self.root / "raw" / name)

    def tearDown(self):
        self.temporary.cleanup()

    def build(self):
        return ingest.build(self.root / "raw", self.root / "processed")

    def test_removed_month_does_not_survive_and_tampering_is_rejected(self):
        self.assertEqual(self.build()["summary"]["analytical_records"], 318)
        (self.root / "raw" / "2025-08_all.xlsx").unlink()
        self.assertEqual(self.build()["summary"]["months"], ["2026-08"])
        self.assertEqual(len(layer_a.load_dataset(self.root / "processed")), 221)
        with (self.root / "processed" / "all_months_analytical.csv").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            layer_a.load_dataset(self.root / "processed")

    def test_failed_build_keeps_previous_output(self):
        first = self.build()
        with patch("src.ingest.normalize_failure_types", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.build()
        self.assertEqual(len(layer_a.load_dataset(self.root / "processed")), first["summary"]["analytical_records"])
        self.assertFalse(list(self.root.glob(".build-*")))

    def test_parser_contracts(self):
        with self.assertRaisesRegex(ValueError, "required headers"):
            ingest.normalize_sheet(pd.DataFrame({"Wrong column": [1]}), "central", "2026-08", "test.xlsx")
        self.assertNotIn("bacterial_endotoxins", ingest.classify_failure({"source_category": "central_nsq", "failure_type": "Assay of Betamethasone"})[0])
        self.assertIn("bacterial_endotoxins", ingest.classify_failure({"source_category": "central_nsq", "failure_type": "BET"})[0])


class LayerATests(unittest.TestCase):
    def test_future_records_do_not_change_earlier_features(self):
        df = fixture()
        future = df.iloc[[-1]].copy()
        before = layer_a.history_examples(df)
        after = layer_a.history_examples(pd.concat([df, future, future], ignore_index=True))
        pd.testing.assert_frame_equal(before[before.target_month.lt("2026-08")].reset_index(drop=True),
                                      after[after.target_month.lt("2026-08")].reset_index(drop=True))

    def test_chronological_splits_and_feature_contract(self):
        examples = layer_a.history_examples(fixture())
        self.assertTrue(examples.feature_cutoff_month.lt(examples.target_month).all())
        self.assertEqual(sorted(examples.loc[examples.split.eq("test"), "target_month"].unique()), ["2026-07", "2026-08"])
        self.assertFalse(set(layer_a.HISTORY_FEATURES) & {"label", "target_report_count", "manufacturer_key", "split"})

    def test_followup_queue_uses_only_earlier_months(self):
        initial = pd.DataFrame([record("a", "2026-01"), record("b", "2026-02"), record("c", "2026-02", "FIRM B", "Other", "Other batch")])
        result = layer_a.followup_queue(initial, "2026-02", 10)
        future = pd.concat([initial, pd.DataFrame([record(str(i), "2026-03", "FIRM B") for i in range(20)])])
        pd.testing.assert_frame_equal(result, layer_a.followup_queue(future, "2026-02", 10))
        self.assertEqual(int(result.loc[result.manufacturer_key.eq("FIRM A"), "prior_nsq_records"].iloc[0]), 1)
        self.assertEqual(int(result.loc[result.manufacturer_key.eq("FIRM B"), "prior_nsq_records"].iloc[0]), 0)

    def test_chronological_coverage_counts_new_manufacturers(self):
        row = layer_a.chronological_coverage(pd.DataFrame([record("a", "2026-01"), record("b", "2026-02"),
                                                           record("c", "2026-02", "FIRM B")]), 1).iloc[0]
        self.assertEqual((row.seen_manufacturer_records, row.new_or_unavailable_manufacturer_records), (1, 1))
        self.assertEqual(row.random_expected_captured_records, 1)


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.episodes = simulator.scan_corpus(fixture(), episodes_per_scenario=3)

    def test_held_out_families_only_in_test_and_corpus_reproduces(self):
        self.assertEqual({e["split"] for e in self.episodes if e["scenario"] in simulator.HELDOUT_SCENARIOS}, {"test"})
        self.assertEqual(self.episodes, simulator.scan_corpus(fixture(), episodes_per_scenario=3))
        self.assertFalse(any("flood" in e["scenario"] for e in self.episodes))

    def test_features_ignore_identifiers_and_future_events(self):
        events = copy.deepcopy(episode(self.episodes, "clone_copy")["events"])
        expected = detector.extract_scan_features(events)
        for event in events:
            event.update(event_id="RENAMED-"+event["event_id"], pack_id="RENAMED-"+event["pack_id"],
                         source_id="RENAMED-"+event["source_id"], product="Different product")
        self.assertEqual(expected, detector.extract_scan_features(events))
        ordered = sorted(events, key=lambda e: e["event_time"])
        cutoff = datetime.fromisoformat(ordered[0]["event_time"]).timestamp()
        self.assertEqual(detector.extract_scan_features(ordered, cutoff), detector.extract_scan_features(ordered[:1], cutoff))

    def test_retries_and_legitimate_distribution(self):
        events = episode(self.episodes, "legitimate_distribution")["events"]
        features = detector.extract_scan_features(events)
        self.assertEqual((features["max_events_per_pack"], features["max_pack_distance_km"]), (1, 0))
        retried = detector.extract_scan_features(events + [events[0]])
        self.assertEqual(retried["unique_events"], features["unique_events"])
        self.assertGreater(retried["retry_fraction"], 0)
        self.assertEqual(detector.rule_scan_score(features)[0], 0)

    def test_event_contract_rejects_bad_values(self):
        good = episode(self.episodes, "clone_copy")["events"][0]
        for change in ({"latitude": 91}, {"event_time": "2026-09-01T00:00:00"}, {"simulated": "yes"}, {"event_id": " "}):
            with self.assertRaises(ValueError):
                simulator.ScanEvent.parse(dict(good, **change))
        with self.assertRaises(ValueError):
            simulator.ScanEvent.parse({**good, "extra": 1})

    def test_benchmark_window_includes_benign_and_clone_families(self):
        _, scenarios = live_window(self.episodes, count=10)
        self.assertIn("benign_repeat", scenarios)
        self.assertIn("clone_copy", scenarios)
        self.assertIn("slow_copy", scenarios)


class SelectionTests(unittest.TestCase):
    def test_ties_share_slots_threshold_and_fusion(self):
        np.testing.assert_allclose(selection_weights([3, 1, 1, 1, 0], 2), [1, 1/3, 1/3, 1/3, 0])
        np.testing.assert_allclose(selection_weights([0, 0, 0, 0], 1), [.25]*4)
        np.testing.assert_allclose(selection_weights([2, 1], 0), [0, 0])
        self.assertEqual(detector.choose_threshold(np.array([0, 0, 1, 1]), np.array([.1, .2, .8, .9])), .8)
        self.assertEqual(fuse("tiered", 90, 80, 50, False), 45)
        self.assertEqual(fuse("tiered", 0, 80, 0, True), 90)
        self.assertEqual(fuse("weighted", 100, 100, 100, True), 100)
        with self.assertRaises(ValueError):
            fuse("other", 1, 1, 1, True)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.df = fixture()
        cls.examples = layer_a.history_examples(cls.df)
        cls.episodes = simulator.scan_corpus(cls.df, episodes_per_scenario=6)
        cls.card = train_backend(cls.df, cls.examples, cls.episodes, detector.featurize(cls.episodes), "sklearn", output=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_card_records_validation_choices_and_held_out_results(self):
        self.assertIn(self.card["history"]["selected"], self.card["history"]["candidate_validation_average_precision"])
        self.assertEqual({f["scenario"] for f in self.card["scan"]["families"] if f["held_out_family"]}, {"delayed_sync", "slow_copy"})
        self.assertIn(self.card["fusion"]["selected_policy"], ("weighted", "tiered"))
        self.assertTrue(self.card["fusion"]["test"])

    def test_backend_without_its_package_is_skipped(self):
        self.assertIsNotNone(load_models("sklearn", self.root))
        with patch("src.fusion.importlib.util.find_spec", return_value=None):
            self.assertIsNone(load_models("sklearn", self.root))

    def test_tampered_model_is_rejected(self):
        copy_dir = self.root / "tampered"
        shutil.copytree(self.root / "sklearn", copy_dir)
        (copy_dir / "scan_model.pkl").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            TrainedModels(copy_dir)

    def test_fusion_pool_merges_episodes_and_excludes_future_references(self):
        models = TrainedModels(self.root / "sklearn")
        base = copy.deepcopy(episode(self.episodes, "benign_repeat"))
        chosen = []
        for index, (batch, label) in enumerate((("BATCH-2026-01", 0), ("BATCH-2026-01", 1), ("BATCH-2026-07", 1))):
            item = copy.deepcopy(base)
            item.update(episode_id=f"pool-case-{index}", split="test", label=label)
            for event in item["events"]:
                event.update(product="Product", batch_no=batch, manufacturer_key="CONTINUING",
                             pack_id=f"PACK-pool-case-{index}")
            chosen.append(item)
        pool = queue_pool(self.df, chosen, "test", "2026-07", models.history, models.scan, models.threshold)
        self.assertEqual(len(pool), 1)
        self.assertEqual((int(pool.iloc[0]["clone"]), int(pool.iloc[0]["recurrence"])), (1, 1))

    def test_demo_feed_alerts_only_clone_and_burst(self):
        models = TrainedModels(self.root / "sklearn")
        feed = simulator.demo_feed(self.df)
        ranked = rank_candidates(self.df, feed, models=models)
        self.assertEqual(len(ranked), len({simulator.ScanEvent.parse(e).candidate for e in feed}))
        alerts = {c["reason_codes"][0] for c in ranked if c["scan_alert"]}
        self.assertEqual(alerts, {"CLONE_PATTERN_TRAVEL_REVIEW", "REPEATED_PACK_BURST_REVIEW"})
        self.assertEqual([c["rank"] for c in ranked], list(range(1, len(ranked)+1)))
        self.assertTrue(all(c["scan_simulated"] and "(simulated scans)" in c["state"] for c in ranked))
        for item in ranked:
            for name in ("historical_risk", "scan_anomaly", "evidence_quality", "priority_score"):
                self.assertIn(name, item)
        self.assertEqual(len(build_decision_queue(self.df, feed, 3, models=models)), 3)
        with self.assertRaises(ValueError):
            build_decision_queue(self.df, feed, -1, models=models)

    @unittest.skipUnless(importlib.util.find_spec("snapml"), "Snap ML not installed")
    def test_snapml_backend(self):
        card = train_backend(self.df, self.examples, self.episodes, detector.featurize(self.episodes), "snapml", output=self.root)
        self.assertTrue(card["history"]["selected"].startswith("snap_"))
        TrainedModels(self.root / "snapml")


@unittest.skipUnless((OUTPUTS / "models" / "sklearn" / "model_card.json").is_file(), "run python -m src.fusion run first")
class DashboardTests(unittest.TestCase):
    def test_dashboard_replays_the_live_queue(self):
        from app.dashboard import build
        with tempfile.TemporaryDirectory() as directory:
            html = build(Path(directory) / "dashboard.html").read_text()
        self.assertIn("SIMULATED scans", html)
        payload = html.split('<script id="bg-data" type="application/json">')[1].split("</script>")[0]
        self.assertNotIn("</", payload)
        data = json.loads(payload)
        steps = data["steps"]["sklearn"]
        self.assertEqual(len(steps), len(data["feed"]))
        self.assertEqual((len(steps[0]), sum(r[3] > 0 for r in steps[0])), (1, 0))
        self.assertEqual(sum(r[3] > 0 for r in steps[-1]), 2)
        self.assertEqual({data["codes"][i] for r in steps[-1][:2] for i in r[7][:1]},
                         {"CLONE_PATTERN_TRAVEL_REVIEW", "REPEATED_PACK_BURST_REVIEW"})
        self.assertTrue(all(c["history"] is not None for c in data["candidates"].values()))
        no_history = [r for r in steps[-1] if r[6] is None]
        self.assertGreaterEqual(len(no_history), 1)
        self.assertTrue(all("NO_EARLIER_MANUFACTURER_HISTORY" in {data["codes"][i] for i in r[7]}
                            for r in no_history))
        self.assertTrue(any(data["candidates"][r[0]]["reports"] for r in no_history))


if __name__ == "__main__":
    unittest.main()
