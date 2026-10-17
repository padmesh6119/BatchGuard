"""The field path must keep provenance out of features and refuse weak evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from src.field_model import (checked_case, choose_budget_threshold, load_cases,
                             observation_features, review_quality, score, train, validate_splits)


def field_case(split, site, index, copied):
    day = {"train": 0, "validation": 10, "test": 20}[split]
    start = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day)
    events = []
    for n in range(2):
        observed = start + timedelta(minutes=4*n)
        event = {"event_id": f"EVENT-{split}-{site}-{index}-{n}",
                 "pack_id": f"PACK-{split}-{site}-{index}", "product": "Tablet",
                 "batch_no": f"BATCH-{split}-{site}-{index}", "manufacturer_key": "FIRM",
                 "event_time": observed.isoformat(), "source_id": f"SCANNER-{site}-{n}",
                 "latitude": 13.08 if n == 0 else 28.61,
                 "longitude": 80.27 if n == 0 else 77.21, "simulated": False}
        events.append({"event": event, "received_at": (observed + timedelta(seconds=2)).isoformat(),
                       "location_accuracy_m": 10, "clock_offset_seconds": 1,
                       "scanner_authenticated": True})
    return {"case_id": f"CASE-{split}-{site}-{index}", "site_id": site,
            "split": split, "observations": events,
            "physical_pack_ids": {events[0]["event"]["event_id"]: "PHYSICAL-A",
                                  events[1]["event"]["event_id"]: "PHYSICAL-B" if copied else "PHYSICAL-A"},
            "adjudication": {"method": "physical_inspection", "evidence_ref": f"EVIDENCE-{split}-{site}-{index}",
                             "reviewer_id": "REVIEWER-1",
                             "adjudicated_at": (start + timedelta(hours=1)).isoformat()}}


def dataset():
    return [field_case(split, f"{split}-SITE-{site}", outcome, bool(outcome))
            for split in ("train", "validation", "test") for site in (0, 1) for outcome in (0, 1)]


class FieldModelTests(unittest.TestCase):
    def test_provenance_changes_label_but_never_features(self):
        benign = field_case("train", "SITE-A", 0, False)
        copied = json.loads(json.dumps(benign))
        copied["physical_pack_ids"][copied["observations"][1]["event"]["event_id"]] = "PHYSICAL-B"
        left, right = checked_case(benign, True), checked_case(copied, True)
        self.assertEqual(left["features"], right["features"])
        self.assertEqual((left["label"], right["label"]), (0, 1))
        self.assertEqual(left["rule_alert"], right["rule_alert"])

    def test_bad_observation_and_unverified_outcome_are_rejected(self):
        case = field_case("train", "SITE-A", 0, True)
        event = case["observations"][0]
        event["event"]["simulated"] = True
        with self.assertRaisesRegex(ValueError, "simulated"):
            checked_case(case, True)
        event["event"]["simulated"] = False
        event["location_accuracy_m"] = -1
        with self.assertRaisesRegex(ValueError, "accuracy"):
            observation_features(case["observations"])
        event["location_accuracy_m"] = 10
        case["physical_pack_ids"].pop(event["event"]["event_id"])
        with self.assertRaisesRegex(ValueError, "cover"):
            checked_case(case, True)

    def test_split_checks_and_false_alert_budget(self):
        rows = [checked_case(case, True) for case in dataset()]
        self.assertEqual([len(part) for part in validate_splits(rows).values()], [4, 4, 4])
        leaked = dataset()
        leaked[-1]["site_id"] = leaked[0]["site_id"]
        with self.assertRaisesRegex(ValueError, "share a site"):
            validate_splits([checked_case(case, True) for case in leaked])
        repeated = dataset()
        repeated[1]["observations"][0]["event"]["event_id"] = repeated[0]["observations"][0]["event"]["event_id"]
        repeated[1]["physical_pack_ids"] = {record["event"]["event_id"]: "PHYSICAL-A"
                                            for record in repeated[1]["observations"]}
        with self.assertRaisesRegex(ValueError, "share an event"):
            validate_splits([checked_case(case, True) for case in repeated])
        reordered = dataset()
        for record in reordered[-1]["observations"]:
            record["event"]["event_time"] = "2026-08-01T00:00:00+00:00"
            record["received_at"] = "2026-08-01T00:00:02+00:00"
        with self.assertRaisesRegex(ValueError, "chronological"):
            validate_splits([checked_case(case, True) for case in reordered])
        threshold = choose_budget_threshold([0, 0, 1, 1], [0.1, 0.8, 0.7, 0.9], maximum_fpr=0)
        self.assertEqual(threshold, 0.9)
        self.assertEqual(choose_budget_threshold([0, 0, 1, 1], [0.1, 0.8, 0.7, 0.9],
                                                maximum_fpr=0, eligible=[True, False, True, True]), 0.7)

    def test_quality_gate_abstains_on_untrusted_telemetry(self):
        case = field_case("train", "SITE-A", 0, True)
        features, _, _ = observation_features(case["observations"])
        self.assertTrue(review_quality(features))
        case["observations"][1]["scanner_authenticated"] = False
        bad, _, _ = observation_features(case["observations"])
        self.assertFalse(review_quality(bad))

    def test_trusted_clock_offset_corrects_the_travel_pattern(self):
        case = field_case("train", "SITE-A", 0, False)
        raw, _, _ = observation_features(case["observations"])
        self.assertGreater(raw["max_pack_speed_kmh"], 900)
        later = case["observations"][1]
        later["clock_offset_seconds"] = -17_760  # scanner reads 4m; trusted elapsed time is 5h
        start = datetime.fromisoformat(case["observations"][0]["event"]["event_time"])
        later["received_at"] = (start + timedelta(hours=5, seconds=2)).isoformat()
        corrected, _, _ = observation_features(case["observations"])
        self.assertLess(corrected["max_pack_speed_kmh"], 900)
        self.assertFalse(review_quality(corrected))
        case["observations"][1]["scanner_authenticated"] = True
        case["observations"][1]["clock_offset_seconds"] = 120
        bad, _, _ = observation_features(case["observations"])
        self.assertFalse(review_quality(bad))
        case["observations"][1]["clock_offset_seconds"] = 1
        observed = datetime.fromisoformat(case["observations"][1]["event"]["event_time"])
        case["observations"][1]["received_at"] = (observed - timedelta(minutes=2)).isoformat()
        bad, _, _ = observation_features(case["observations"])
        self.assertFalse(review_quality(bad))

    def test_end_to_end_scoring_stays_research_only_without_enough_field_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cases_path = root / "adjudicated.jsonl"
            cases_path.write_text("".join(json.dumps(case) + "\n" for case in dataset()))
            self.assertEqual(len(load_cases(cases_path)), 12)
            model_dir = root / "model"
            card = train(cases_path, model_dir)
            self.assertFalse(card["field_review_ready"])
            self.assertTrue(card["readiness_reasons"])
            unlabeled = root / "unlabeled.jsonl"
            unlabeled.write_text(json.dumps({key: dataset()[0][key] for key in ("case_id", "site_id", "observations")}) + "\n")
            output = root / "scores.json"
            results = score(unlabeled, model_dir, output)
            self.assertEqual(results[0]["status"], "research_only")
            self.assertFalse(results[0]["review_flag"])
            self.assertEqual(len(json.loads(output.read_text())["cases"]), 1)
            (model_dir / "field_model.pkl").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                score(unlabeled, model_dir, output)

    def test_review_flag_path_requires_a_passing_holdout(self):
        # A deliberately easy synthetic fixture checks the deployment gate's plumbing,
        # not the field performance of a model trained on actual observations.
        cases = []
        for split in ("train", "validation", "test"):
            for site in (0, 1):
                for index in range(125):
                    copied = index < 25
                    case = field_case(split, f"{split}-SITE-{site}", index, copied)
                    if not copied:
                        second = case["observations"][1]["event"]
                        second["latitude"], second["longitude"] = 13.08, 80.27
                    cases.append(case)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path = root / "adjudicated.jsonl"
            input_path.write_text("".join(json.dumps(case) + "\n" for case in cases))
            model_dir = root / "model"
            card = train(input_path, model_dir)
            self.assertTrue(card["field_review_ready"], card["readiness_reasons"])
            self.assertEqual(card["split_counts"]["test"]["positives"], 50)
            scoring = root / "new.jsonl"
            unseen = field_case("test", "NEW-SITE", 200, True)
            scoring.write_text(json.dumps({key: unseen[key] for key in ("case_id", "site_id", "observations")}) + "\n")
            result = score(scoring, model_dir, root / "scores.json")[0]
            self.assertEqual(result["status"], "field_model_review")
            self.assertTrue(result["review_flag"])


if __name__ == "__main__":
    unittest.main()
