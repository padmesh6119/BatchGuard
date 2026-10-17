"""Test whether more copies of the current synthetic scripts improve Layer B generalization.

This is a diagnostic experiment. The challenge set was designed after seeing the
original model and is not a blinded final test or a source of field accuracy.
"""
import argparse
import json
from pathlib import Path

from src import detector, layer_a, simulator
from src.common import DATA_PROCESSED, OUTPUTS, ROOT, SEED, file_hash, write_json
from src.synthetic_challenge import evaluate as evaluate_challenge

DEFAULT_SIZES = (30, 100, 300, 900)


def run(sizes=DEFAULT_SIZES, backend="sklearn", output=OUTPUTS / "scan_learning_curve.json"):
    df = layer_a.load_dataset()
    challenge_path = ROOT / "data" / "synthetic" / "challenge_v1.jsonl"
    cases = [json.loads(line) for line in challenge_path.read_text().splitlines()]
    fixed_episodes = simulator.scan_corpus(df, episodes_per_scenario=300, seed=SEED + 101)
    # The generator's pack IDs otherwise reuse episode names across different seeds.
    for episode in fixed_episodes:
        for event in episode["events"]:
            event["event_id"] = "FIXED-" + event["event_id"]
            event["pack_id"] = "FIXED-" + event["pack_id"]
    fixed = detector.featurize(fixed_episodes)
    results = []
    for size in sizes:
        if isinstance(size, bool) or not isinstance(size, int) or size < 2:
            raise ValueError("All training sizes must be integers of at least two")
        training = detector.featurize(simulator.scan_corpus(df, episodes_per_scenario=size, seed=SEED))
        model, selection = detector.train(training, backend=backend, seed=SEED)
        fixed_result = detector.evaluate(model, fixed, selection["threshold"])
        fixed_result.pop("test_predictions")
        challenge_result = evaluate_challenge(cases, model, selection["threshold"])
        results.append({"episodes_per_seen_scenario": size,
                        "training_episodes": int(training["split"].eq("train").sum()),
                        "validation_episodes": int(training["split"].eq("validation").sum()),
                        "selected_model": selection["selected"], "threshold": selection["threshold"],
                        "fixed_test": fixed_result,
                        "challenge": {"model": challenge_result["model"], "rule": challenge_result["rule"],
                                      "scenarios": challenge_result["scenarios"]}})
    report = {"purpose": "learning curve for the existing synthetic generator; not field accuracy",
              "backend": backend, "training_seed": SEED, "fixed_test_seed": SEED + 101,
              "processed_manifest_sha256": file_hash(DATA_PROCESSED / "manifest.json"),
              "challenge_dataset_sha256": file_hash(challenge_path),
              "fixed_test_episodes": int(fixed["split"].eq("test").sum()),
              "challenge_cases": len(cases), "results": results}
    write_json(Path(output), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=DEFAULT_SIZES)
    parser.add_argument("--backend", choices=("sklearn", "snapml"), default="sklearn")
    parser.add_argument("--output", type=Path, default=OUTPUTS / "scan_learning_curve.json")
    args = parser.parse_args()
    report = run(tuple(args.sizes), args.backend, args.output)
    for row in report["results"]:
        test = row["fixed_test"]["model"]
        challenge = row["challenge"]["model"]
        print(f"{row['episodes_per_seen_scenario']:4d}/family: test AP={test['average_precision']:.3f}, "
              f"recall={test['recall']:.3f}; challenge FP={challenge['false_positives']}, "
              f"FN={challenge['false_negatives']}")


if __name__ == "__main__":
    main()
