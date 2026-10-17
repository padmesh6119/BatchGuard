"""Guard the frozen diagnostic set and its non-identifiability examples."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src import synthetic_challenge as challenge
from src.common import ROOT
from src.detector import extract_scan_features


class SyntheticChallengeTests(unittest.TestCase):
    def test_cases_are_reproducible_and_truth_is_hidden_from_events(self):
        cases = challenge.generate(3, 7)
        self.assertEqual(cases, challenge.generate(3, 7))
        self.assertNotEqual(cases, challenge.generate(3, 8))
        self.assertEqual(len(cases), 3 * len(challenge.SCENARIOS))
        for case in cases:
            provenance = {}
            for event, truth in zip(case["events"], case["truth_events"]):
                self.assertEqual(event["event_id"], truth["event_id"])
                provenance.setdefault(event["pack_id"], set()).add(truth["physical_pack_id"])
            self.assertEqual(case["physical_packs"], len({t["physical_pack_id"] for t in case["truth_events"]}))
            self.assertEqual(case["copied_id"], any(len(physical_ids) > 1 for physical_ids in provenance.values()))
        self.assertTrue(all(set(event) == {"event_id", "pack_id", "product", "batch_no", "manufacturer_key",
                                            "event_time", "source_id", "latitude", "longitude", "simulated"}
                            for case in cases for event in case["events"]))
        self.assertTrue(all("physical_packs" not in event and "copied_id" not in event
                            for case in cases for event in case["events"]))

    def test_opposite_truth_can_have_identical_observables(self):
        cases = challenge.generate(4)
        by_id = {case["case_id"]: case for case in cases}
        report = challenge.evaluate(cases)
        self.assertEqual(len(report["indistinguishable_pairs"]), 4)
        for positive, negative in challenge.PAIRS:
            for index in range(4):
                a = by_id[f"{positive}-{index:04d}"]
                b = by_id[f"{negative}-{index:04d}"]
                self.assertTrue(a["copied_id"])
                self.assertFalse(b["copied_id"])
                self.assertEqual(extract_scan_features(a["events"]), extract_scan_features(b["events"]))
        self.assertEqual(report["rule"]["false_positives"], 12)
        self.assertEqual(report["rule"]["false_negatives"], 8)

    def test_written_dataset_hash_and_report_match(self):
        cases = challenge.generate(2)
        with tempfile.TemporaryDirectory() as directory:
            report = challenge.evaluate(cases)
            dataset = challenge.write_dataset(cases, directory, report)
            saved = [json.loads(line) for line in dataset.read_text().splitlines()]
            saved_report = json.loads((Path(directory) / "challenge_v1_report.json").read_text())
            self.assertEqual(saved, cases)
            self.assertEqual(saved_report["dataset_sha256"], hashlib.sha256(dataset.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            challenge.generate(0)

    def test_committed_challenge_is_the_declared_generator_output(self):
        directory = ROOT / "data" / "synthetic"
        dataset = directory / "challenge_v1.jsonl"
        report = json.loads((directory / "challenge_v1_report.json").read_text())
        self.assertEqual(report["dataset_sha256"], hashlib.sha256(dataset.read_bytes()).hexdigest())
        self.assertEqual([json.loads(line) for line in dataset.read_text().splitlines()],
                         challenge.generate(report["per_scenario"], report["seed"]))


if __name__ == "__main__":
    unittest.main()
