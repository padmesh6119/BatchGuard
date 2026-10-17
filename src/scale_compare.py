"""Compare like-for-like laptop and LinuxONE synthetic stream measurements."""
import argparse
import json
from pathlib import Path

from src.common import write_json

MATCH_FIELDS = ("backend", "profile", "events_requested", "seed", "queue_every_events",
                "capacity", "workload_sha256", "processed_manifest_sha256", "model_version",
                "scan_model_selection", "scan_model_threshold", "decision_sha256")


def compare(laptop, linuxone):
    if laptop.get("host") != "laptop" or linuxone.get("host") != "linuxone":
        raise ValueError("Expected a laptop report followed by a LinuxONE report")
    differences = [name for name in MATCH_FIELDS if laptop.get(name) != linuxone.get(name)]
    if differences:
        raise ValueError("Cannot compare mismatched workloads/models: " + ", ".join(differences))
    x86 = float(laptop["events_per_second_median"])
    z = float(linuxone["events_per_second_median"])
    if x86 <= 0 or z <= 0:
        raise ValueError("Measured throughputs must be positive")
    return {
        "backend": laptop["backend"], "profile": laptop["profile"],
        "events": laptop["events_requested"], "workload_sha256": laptop["workload_sha256"],
        "decision_sha256": laptop["decision_sha256"],
        "laptop_events_per_second": x86, "linuxone_events_per_second": z,
        "observed_linuxone_to_laptop_ratio": z / x86,
        "same_scan_test_predictions_sha256": laptop.get("scan_test_predictions_sha256") == linuxone.get("scan_test_predictions_sha256"),
        "hardware_acceleration_verified": False,
        "scope": "Observed single-process synthetic workload ratio only; no cost, energy, service-level, or accelerator conclusion.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("laptop", type=Path)
    parser.add_argument("linuxone", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.laptop.read_text()), json.loads(args.linuxone.read_text()))
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
