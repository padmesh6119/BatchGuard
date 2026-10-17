"""Check that the synthetic load is reproducible and exercises the live decision path."""
import unittest
from unittest.mock import patch

from src.scale_benchmark import generate_events, process_stream
from src.scale_compare import MATCH_FIELDS, compare
from src.simulator import ScanEvent
from tests.test_batchguard import fixture


class ScaleBenchmarkTests(unittest.TestCase):
    def test_workload_contract_and_determinism(self):
        first = list(generate_events(300, "routine", ["FIRM A", "FIRM B"], seed=9))
        self.assertEqual(first, list(generate_events(300, "routine", ["FIRM A", "FIRM B"], seed=9)))
        self.assertNotEqual(first, list(generate_events(300, "routine", ["FIRM A", "FIRM B"], seed=10)))
        self.assertEqual(len(first), 300)
        self.assertEqual({pattern for pattern, _, _ in first}, {"single", "repeat", "burst", "conflict"})
        timestamps = [ScanEvent.parse(payload).timestamp for _, _, payload in first]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len({payload["event_id"] for _, _, payload in first}), 300)
        with self.assertRaises(ValueError):
            list(generate_events(0, "routine", ["FIRM A"]))
        with self.assertRaises(ValueError):
            list(generate_events(1, "unknown", ["FIRM A"]))

    def test_replay_uses_live_queue_and_stable_hash(self):
        df = fixture()
        first = process_stream(df, None, 130, "routine", ["CONTINUING"], queue_every=25)
        second = process_stream(df, None, 130, "routine", ["CONTINUING"], queue_every=25)
        self.assertEqual(first["workload_sha256"], second["workload_sha256"])
        self.assertEqual(first["decision_sha256"], second["decision_sha256"])
        self.assertEqual(first["events"], 130)
        self.assertEqual(sum(first["pattern_events"].values()), 130)
        self.assertGreater(first["alerts_on_arriving_events"], 0)
        self.assertEqual(first["snapshots"], 6)
        self.assertGreater(first["events_per_second_wall"], 0)
        with patch("src.scale_benchmark.OBSERVATION_SECONDS", 3):
            short_window = process_stream(df, None, 130, "routine", ["CONTINUING"], queue_every=25)
        self.assertLess(short_window["active_candidates_at_end"], short_window["candidate_groups"])
        with self.assertRaises(ValueError):
            process_stream(df, None, 1, "routine", ["CONTINUING"], queue_every=0)

    def test_cross_host_comparison_rejects_changed_workload(self):
        base = {name: "same" for name in MATCH_FIELDS}
        laptop = {**base, "host": "laptop", "events_per_second_median": 500.0}
        linuxone = {**base, "host": "linuxone", "events_per_second_median": 750.0}
        result = compare(laptop, linuxone)
        self.assertEqual(result["observed_linuxone_to_laptop_ratio"], 1.5)
        self.assertFalse(result["hardware_acceleration_verified"])
        with self.assertRaisesRegex(ValueError, "workload"):
            compare(laptop, {**linuxone, "workload_sha256": "different"})
        with self.assertRaisesRegex(ValueError, "decision"):
            compare(laptop, {**linuxone, "decision_sha256": "different"})
        with self.assertRaisesRegex(ValueError, "Expected"):
            compare(laptop, {**linuxone, "host": "laptop"})


if __name__ == "__main__":
    unittest.main()
