"""Measure the same decision workload on a laptop or assigned LinuxONE; compare model outputs across hosts."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import resource
import time

import numpy as np
import pandas as pd

from batchguard_engine import load_dataset
from decision_core import (TrainedModels, corroboration, decision_context, fuse, probability, rank_candidates,
                           rule_scan_score)
from inspection_stream import ScanEvent, digest
from scan_features import SCAN_FEATURES, extract_scan_features
from replay import environment
from snapshot_store import ROOT

WINDOW_CANDIDATES = 50


def percentiles(samples_ms):
    values = np.asarray(samples_ms, dtype=float)
    return {"count": int(values.size), "p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)), "mean": float(values.mean()), "max": float(values.max())}


def cpu_facts():
    facts = {"logical_cpus": os.cpu_count(), "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None}
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return facts
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key in {"model name", "vendor_id", "machine", "features"} and key not in facts:
            facts[key] = value.strip()
    # Hardware availability only; it does not show that any workload used the accelerator.
    facts["nnpa_facility_listed"] = "nnpa" in facts.get("features", "").split()
    return facts


def load_workload(bundle):
    return [json.loads(line) for line in (Path(bundle) / "scan_episodes.jsonl").read_text().splitlines() if line.strip()]


def live_window(episodes, end=datetime(2026, 9, 15, 12, tzinfo=timezone.utc)):
    """Test-split episodes taken round-robin across scenario families, re-timed to end together."""
    families = defaultdict(list)
    for episode in episodes:
        if episode["split"] == "test":
            families[episode["scenario"]].append(episode)
    chosen = [family[i] for i in range(WINDOW_CANDIDATES) for family in families.values() if i < len(family)][:WINDOW_CANDIDATES]
    events = []
    for index, episode in enumerate(chosen):
        shift = timedelta(seconds=end.timestamp() - max(ScanEvent.parse(p).timestamp for p in episode["events"]))
        events.extend(dict(p, event_id=f"W{index}-{p['event_id']}", event_time=(datetime.fromisoformat(p["event_time"])+shift).isoformat())
                      for p in episode["events"])
    return events, sorted({e["scenario"] for e in chosen})


def timed(function, *args):
    start = time.perf_counter()
    value = function(*args)
    return value, (time.perf_counter()-start)*1000


def run_once(df, models, episodes, window):
    stages = defaultdict(list)
    flat = [payload for payloads in episodes for payload in payloads]
    _, ms = timed(lambda: [ScanEvent.parse(p) for p in flat])
    stages["event_validation_total_ms"].append(ms)
    features = []
    for payloads in episodes:
        values, ms = timed(extract_scan_features, payloads)
        features.append(values)
        stages["feature_extraction_ms"].append(ms)
    for values in features:
        _, ms = timed(probability, models.scan, [values], SCAN_FEATURES)
        stages["scan_inference_single_ms"].append(ms)
    _, ms = timed(probability, models.scan, features, SCAN_FEATURES)
    stages["scan_inference_batch_total_ms"].append(ms)
    month = max(p["event_time"] for p in window)[:7]
    context, ms = timed(decision_context, df, month, models)
    stages["decision_context_build_ms"].append(ms)
    history = context["history"]
    # Per delivery: re-derive that candidate's pack features, score it and fuse with cached history.
    by_candidate = defaultdict(list)
    ordered = sorted(window, key=lambda p: (p["event_time"], p["event_id"]))
    for payload in ordered:
        start = time.perf_counter()
        event = ScanEvent.parse(payload)
        by_candidate[event.candidate].append(payload)
        values = extract_scan_features(by_candidate[event.candidate], event.timestamp)
        scan = float(probability(models.scan, [values], SCAN_FEATURES)[0])
        key = event.manufacturer_key.strip().casefold()
        history_score = float(history["percentile"].get(key, 0.0)) if key else 0.0
        rule = rule_scan_score(values)[0]
        fuse(models.policy, history_score, rule, corroboration(values), rule > 0)
        stages["per_scan_decision_ms"].append((time.perf_counter()-start)*1000)
    _, ms = timed(rank_candidates, df, window, None, models, context)
    stages["queue_rebuild_with_cached_context_ms"].append(ms)
    return stages, len(flat)


def run(args):
    if args.require_s390x and platform.machine().lower() != "s390x":
        raise SystemExit("This host is not s390x. Do not label this run LinuxONE.")
    models = TrainedModels(args.models)
    bundle = ROOT / models.card["bundle"]["path"] if not Path(models.card["bundle"]["path"]).is_absolute() else Path(models.card["bundle"]["path"])
    snapshot = models.card["bundle"]["snapshot_id"]
    df = load_dataset((ROOT / "data" / "snapshots" / snapshot, snapshot))
    episodes = load_workload(bundle)
    window, window_scenarios = live_window(episodes)
    episodes = [episode["events"] for episode in episodes]
    run_once(df, models, episodes[:20], window[:50])
    pooled, repeats = defaultdict(list), []
    wall = time.perf_counter()
    for _ in range(args.repeats):
        start = time.perf_counter()
        stages, events = run_once(df, models, episodes, window)
        seconds = time.perf_counter()-start
        repeats.append({"seconds": seconds, "events": events, "episodes": len(episodes),
                        "events_per_second_end_to_end": events/seconds})
        for name, samples in stages.items():
            pooled[name].extend(samples)
    result = {
        "benchmark_version": "decision-workload-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": "LinuxONE (s390x)" if platform.machine().lower() == "s390x" else f"{platform.machine()} host",
        "model_version": models.version, "backend": models.card["backend"], "fusion_policy": models.policy,
        "snapshot_id": snapshot, "workload_sha256": digest(episodes), "window_sha256": digest(window),
        "workload": {"episodes": len(episodes), "events": sum(map(len, episodes)), "window_events": len(window),
                     "window_episodes": WINDOW_CANDIDATES, "window_scenarios": window_scenarios, "repeats": args.repeats, "warmup": "one reduced pass excluded"},
        "stages_ms": {name: percentiles(samples) for name, samples in pooled.items()},
        "repeats": repeats, "total_seconds": time.perf_counter()-wall,
        "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        "environment": environment(), "cpu": cpu_facts(), "python_platform": platform.platform(),
        "scope": ("Single process, sequential, in memory; data already loaded. Excludes network, UI and disk persistence. "
                  "Accelerator use is not claimed unless separately configured and evidenced."),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / f"{platform.machine()}-{models.card['backend']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    summary = {name: {k: round(v, 4) for k, v in values.items() if k in {"p50", "p99"}}
               for name, values in result["stages_ms"].items()}
    print(json.dumps({"output": str(path), "label": result["label"], "backend": result["backend"],
                      "events_per_second_end_to_end": round(np.median([r["events_per_second_end_to_end"] for r in repeats]), 1),
                      "stages_ms": summary}, indent=2))
    return result


def compare(args):
    """Same bundle, seed and code on two hosts: report prediction and metric differences, not a verdict."""
    report = {"reference": str(args.reference), "candidate": str(args.candidate)}
    cards = [json.loads((Path(d) / "model_card.json").read_text()) for d in (args.reference, args.candidate)]
    report["machines"] = [c["environment"]["machine"] for c in cards]
    report["backends"] = [c["backend"] for c in cards]
    report["selected"] = {"history": [c["history"]["selected"] for c in cards], "scan": [c["scan"]["selected"] for c in cards]}
    for task in ("history", "scan"):
        a, b = (pd.read_csv(Path(d) / f"{task}_test_predictions.csv") for d in (args.reference, args.candidate))
        joined = a.merge(b, on="example_id", suffixes=("_reference", "_candidate"), validate="one_to_one")
        diff = (joined["probability_reference"]-joined["probability_candidate"]).abs()
        report[f"{task}_predictions"] = {
            "rows": len(joined), "max_abs_difference": float(diff.max()), "mean_abs_difference": float(diff.mean()),
            "spearman": float(joined["probability_reference"].rank().corr(joined["probability_candidate"].rank()))}
    report["history_test_average_precision"] = [c["history"]["test"]["trained_model"]["average_precision"] for c in cards]
    report["scan_test_recall"] = [c["scan"]["model"]["recall"] for c in cards]
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run")
    one.add_argument("--models", type=Path, default=ROOT / "models" / "baseline-v1")
    one.add_argument("--repeats", type=int, default=5)
    one.add_argument("--output", type=Path, default=ROOT / "reports" / "benchmarks")
    one.add_argument("--require-s390x", action="store_true")
    two = sub.add_parser("compare")
    two.add_argument("--reference", type=Path, default=ROOT / "models" / "baseline-v1")
    two.add_argument("--candidate", type=Path, required=True)
    two.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "run" and args.repeats < 1:
        parser.error("repeats must be at least one")
    run(args) if args.command == "run" else compare(args)


if __name__ == "__main__":
    main()
