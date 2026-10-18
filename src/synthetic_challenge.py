"""Reproducible, intentionally difficult scan challenge; never used to fit or tune models.

The label is whether two physical packs were assigned one observed pack ID. It is
synthetic provenance, not a laboratory result or a counterfeit-drug diagnosis.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random

from src.common import ROOT, SEED, probability
from src.detector import SCAN_FEATURES, confusion, extract_scan_features, rule_scan_score
from src.simulator import ScanEvent

SCENARIOS = (
    "benign_repeat", "legitimate_distribution", "legitimate_travel",
    "location_glitch", "clock_skew", "benign_handoff", "benign_rescan_burst",
    "clone_fast", "clone_burst", "clone_slow", "clone_same_location",
)
COPIED_ID = {"clone_fast", "clone_burst", "clone_slow", "clone_same_location"}
PAIRS = (("clone_fast", "location_glitch"), ("clone_slow", "legitimate_travel"),
         ("clone_same_location", "benign_handoff"), ("clone_burst", "benign_rescan_burst"))
CHENNAI = (13.08, 80.27)
DELHI = (28.61, 77.21)
COIMBATORE = (11.02, 76.96)


def generate(per_scenario=100, seed=SEED):
    """Generate diagnostic cases. Truth is kept outside the ScanEvent payload."""
    if isinstance(per_scenario, bool) or not isinstance(per_scenario, int) or per_scenario < 1:
        raise ValueError("per_scenario must be a positive integer")
    cases = []
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for index in range(per_scenario):
        rng = random.Random(f"{seed}:{index}")
        fast_minutes = rng.randint(2, 4)
        slow_minutes = rng.randint(240, 300)
        for scenario in SCENARIOS:
            expected_copied = scenario in COPIED_ID
            batch = f"SYN-{scenario.upper()}-{index:04d}"
            pack = f"PACK-{scenario}-{index}"
            origin = start + timedelta(days=index)
            observations, truth_events = [], []

            def add(minutes, location, pack_id=pack, source="SCANNER-A", retry=False,
                    physical_pack="PHYS-1", true_minutes=None, true_location=None):
                event = dict(event_id=f"EVENT-{scenario}-{index}-{len(observations)}",
                             pack_id=pack_id, product="Synthetic tablet", batch_no=batch,
                             manufacturer_key="SYNTHETIC MANUFACTURER",
                             event_time=(origin + timedelta(minutes=minutes)).isoformat(),
                             source_id=source, latitude=location[0], longitude=location[1], simulated=True)
                observations.append(event)
                actual_location = location if true_location is None else true_location
                truth = {"event_id": event["event_id"], "physical_pack_id": physical_pack,
                         "true_event_time": (origin + timedelta(minutes=minutes if true_minutes is None else true_minutes)).isoformat(),
                         "true_latitude": actual_location[0], "true_longitude": actual_location[1]}
                truth_events.append(truth)
                if retry:
                    observations.append(dict(event))
                    truth_events.append(dict(truth))

            if scenario == "benign_repeat":
                add(0, CHENNAI, retry=True)
                add(10, CHENNAI)
                add(20, CHENNAI)
            elif scenario == "legitimate_distribution":
                for n in range(12):
                    add(n * 2, CHENNAI if n % 2 else DELHI, f"{pack}-{n}", physical_pack=f"PHYS-{n}")
            elif scenario in {"clone_fast", "location_glitch"}:
                # Exactly the same observable pattern; hidden physical provenance differs.
                add(0, CHENNAI)
                add(fast_minutes, DELHI, source="SCANNER-B",
                    physical_pack="PHYS-2" if expected_copied else "PHYS-1",
                    true_location=None if expected_copied else CHENNAI)
            elif scenario in {"clone_slow", "legitimate_travel"}:
                # Both fit ordinary travel within the six-hour observation window.
                add(0, CHENNAI)
                add(slow_minutes, COIMBATORE, source="SCANNER-B",
                    physical_pack="PHYS-2" if expected_copied else "PHYS-1")
            elif scenario == "clock_skew":
                # One pack actually travels over hours; the second scanner's clock is wrong.
                add(0, CHENNAI)
                add(2, COIMBATORE, source="SCANNER-B", true_minutes=300)
            elif scenario in {"clone_burst", "benign_rescan_burst"}:
                for n in range(12):
                    add(n / 4, CHENNAI, source="SCANNER-A" if n < 6 else "SCANNER-B",
                        physical_pack="PHYS-2" if expected_copied and n >= 6 else "PHYS-1")
            elif scenario in {"clone_same_location", "benign_handoff"}:
                add(0, CHENNAI)
                add(3, CHENNAI, source="SCANNER-B",
                    physical_pack="PHYS-2" if expected_copied else "PHYS-1")
            else:
                raise AssertionError(scenario)
            for event in observations:
                ScanEvent.parse(event)
            pack_provenance = {}
            for event, truth in zip(observations, truth_events):
                pack_provenance.setdefault(event["pack_id"], set()).add(truth["physical_pack_id"])
            copied = any(len(physical_ids) > 1 for physical_ids in pack_provenance.values())
            physical_packs = len({event["physical_pack_id"] for event in truth_events})
            if copied != expected_copied:
                raise AssertionError("Generated physical provenance disagrees with copied-ID label")
            cases.append({"case_id": f"{scenario}-{index:04d}", "scenario": scenario,
                          "copied_id": copied, "physical_packs": physical_packs,
                          "events": observations, "truth_events": truth_events})
    return cases


def evaluate(cases, model=None, threshold=None):
    """Report diagnostic performance by mechanism, never a population precision estimate."""
    if (model is None) != (threshold is None):
        raise ValueError("model and threshold must be provided together")
    features = [extract_scan_features(case["events"]) for case in cases]
    scores = [rule_scan_score(row)[0] for row in features]
    y = [case["copied_id"] for case in cases]
    probabilities = probability(model, features, SCAN_FEATURES) if model is not None else None
    result = {"dataset": "synthetic challenge; equal cases per mechanism, not a population sample",
              "label": "two physical packs assigned one observed pack ID (synthetic hidden provenance)",
              "cases": len(cases), "positives": sum(y),
              "rule": confusion(y, [score > 0 for score in scores]),
              "scenarios": {}, "indistinguishable_pairs": []}
    if probabilities is not None:
        result["model"] = confusion(y, probabilities >= threshold)
        result["model_threshold"] = threshold
    for scenario in SCENARIOS:
        selected = [i for i, case in enumerate(cases) if case["scenario"] == scenario]
        row = {"cases": len(selected), "copied_id": scenario in COPIED_ID,
               "rule_alerts": sum(scores[i] > 0 for i in selected)}
        if probabilities is not None:
            row["model_alerts"] = int(sum(probabilities[i] >= threshold for i in selected))
        result["scenarios"][scenario] = row
    lookup = {case["case_id"]: i for i, case in enumerate(cases)}
    for positive, negative in PAIRS:
        count = 0
        for index in range(result["scenarios"][positive]["cases"]):
            a = lookup[f"{positive}-{index:04d}"]
            b = lookup[f"{negative}-{index:04d}"]
            if features[a] != features[b]:
                raise ValueError(f"Paired observable features diverged: {positive}/{negative}/{index}")
            count += 1
        result["indistinguishable_pairs"].append({"positive": positive, "negative": negative,
                                                    "identical_feature_pairs": count})
    return result


def write_dataset(cases, directory, result):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(case, sort_keys=True, separators=(",", ":")) + "\n" for case in cases)
    dataset = directory / "challenge_v1.jsonl"
    dataset.write_text(records)
    result["dataset_sha256"] = hashlib.sha256(records.encode()).hexdigest()
    (directory / "challenge_v1_report.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-scenario", type=int, default=100)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "synthetic")
    parser.add_argument("--rule-only", action="store_true")
    args = parser.parse_args()
    cases = generate(args.per_scenario, args.seed)
    model = threshold = version = None
    if not args.rule_only:
        from src.fusion import load_models
        models = load_models("sklearn")
        if models is not None:
            model, threshold, version = models.scan, models.threshold, models.version
    result = evaluate(cases, model, threshold)
    result.update({"seed": args.seed, "per_scenario": args.per_scenario,
                   "model_version": version, "purpose": "diagnostic stress test only; no field accuracy claim"})
    path = write_dataset(cases, args.output, result)
    print(f"{path}: {result['cases']} cases; rule={result['rule']}; model={result.get('model')}")


if __name__ == "__main__":
    main()
