"""Run the same labeled, persistent replay on a laptop or assigned LinuxONE."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import time

from batchguard_engine import historical_priorities, load_dataset
from inspection_stream import (InspectionStream, ReferenceIndex, POLICY_VERSION,
                               ScanEvent, digest, make_scenarios)
from snapshot_store import ROOT


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def environment():
    packages = {}
    for name in ("numpy", "pandas", "openpyxl", "scikit-learn", "streamlit", "snapml"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    return {"machine": platform.machine(), "system": platform.system(),
            "release": platform.release(), "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(), "packages": packages,
            "linuxone_run_verified": False,
            "platform_note": "Architecture is recorded automatically; operator must verify host allocation. No acceleration claim."}


def run_replay(events, truth, reference, database, capacity):
    samples, accepted, retries = [], 0, 0
    stream = InspectionStream(reference, database)
    try:
        start = time.perf_counter()
        for event in events:
            before = time.perf_counter()
            result = stream.ingest(event)
            samples.append((time.perf_counter()-before)*1000)
            retries += int(result["duplicate_delivery"])
            accepted += int(not result["duplicate_delivery"])
        duration = time.perf_counter()-start
        queue_start = time.perf_counter()
        queues = {mode: stream.queue(capacity, mode) for mode in
                  ("history_only", "raw_volume", "scan_only", "fused")}
        all_candidates = stream.queue(2**31-1)
        queue_seconds = time.perf_counter()-queue_start
    finally:
        stream.close()
    ordered = sorted(samples)
    def percentile(p):
        if not ordered:
            return 0
        pos = (len(ordered)-1)*p
        low = int(pos)
        high = min(low+1, len(ordered)-1)
        return ordered[low] + (ordered[high]-ordered[low])*(pos-low)
    metrics = {}
    labeled = [c for c in all_candidates if c["candidate_id"] in truth]
    positives = sum(truth[c["candidate_id"]]["clone"] for c in labeled)
    for mode, queue in queues.items():
        selected = [c for c in queue if c["candidate_id"] in truth]
        captured = sum(truth[c["candidate_id"]]["clone"] for c in selected)
        metrics[mode] = {"selected_candidates": len(queue), "labeled_selected": len(selected),
                         "simulated_clone_candidates_captured": captured,
                         "capture_fraction": captured/positives if positives else None}
    predicted = [c for c in labeled if c["evidence_tier"] >= 2]
    tp = sum(truth[c["candidate_id"]]["clone"] for c in predicted)
    fp = len(predicted)-tp
    scenario_results = [dict(truth[c["candidate_id"]], candidate_id=c["candidate_id"],
                             evidence_tier=c["evidence_tier"],
                             detected=c["evidence_tier"] >= 2) for c in labeled]
    report = {
        "policy_version": POLICY_VERSION, "snapshot_id": reference.snapshot_id,
        "workload_sha256": digest(events), "truth_sha256": digest(truth),
        "environment": environment(), "capacity": capacity,
        "input_deliveries": len(events), "accepted_new_events": accepted,
        "duplicate_deliveries": retries, "active_unique_candidates": len(all_candidates),
        "labeled_active_candidates": len(labeled), "simulated_clone_candidates": positives,
        "benchmark": {"duration_seconds": duration, "deliveries_per_second": len(events)/duration if duration else 0,
                      "accepted_new_events_per_second": accepted/duration if duration else 0,
                      "latency_ms": {"p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99),
                                     "mean": statistics.mean(samples) if samples else 0},
                      "queue_evaluation_seconds": queue_seconds,
                      "scope": "Sequential local validation, SQLite transaction, pack features and audit persistence per delivery. Excludes reference loading, network and UI; queue timing separate. No warmup excluded."},
        "detector": {"evaluation_unit": "active sampling candidate; threshold evidence_tier >= 2",
                     "true_positives": tp, "false_positives": fp,
                     "false_negatives": positives-tp,
                     "precision": tp/len(predicted) if predicted else None,
                     "recall": tp/positives if positives else None},
        "budget_comparison": metrics, "scenario_results": scenario_results,
        "limitations": ["Synthetic behavior only; no commercial competitor was benchmarked.",
                        "Source independence is assumed, not authenticated; Sybil attacks are not solved.",
                        "Thresholds and scenarios are hand-designed; no trained AI or unseen-family generalization claim.",
                        "Slow clones outside the 30-minute window remain a known miss.",
                        "Queue and metrics use the last 30 minutes of event time, not wall-clock freshness.",
                        "All candidates, including weak evidence, can fill the requested budget; N is a maximum, not an obligation to act.",
                        "No real defect probability or real-world counterfeit accuracy is measured."]}
    return report, queues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "replay", "platform"])
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "inspection_replay")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--capacity", type=int, default=2)
    parser.add_argument("--require-s390x", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="Continue an existing event database instead of requiring a fresh one.")
    args = parser.parse_args()
    if args.capacity < 0:
        parser.error("capacity must be nonnegative")
    if args.require_s390x and platform.machine().lower() != "s390x":
        parser.error("This host is not s390x. Do not label this run LinuxONE.")
    if args.command == "platform":
        print(json.dumps(environment(), indent=2))
        return
    df = load_dataset()
    reference = ReferenceIndex(df, historical_priorities(df))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command == "demo":
        events, truth = make_scenarios(df, args.copies, args.seed)
        with (args.output / "events.jsonl").open("w") as f:
            for event in events:
                f.write(json.dumps(event, sort_keys=True) + "\n")
        write_json(args.output / "truth.json", truth)
    else:
        if args.events is None:
            parser.error("replay requires --events")
        events = [json.loads(line) for line in args.events.read_text().splitlines() if line.strip()]
        truth = json.loads(args.truth.read_text()) if args.truth else {}
    # Validate the complete workload before opening or mutating the replay database.
    for event in events:
        ScanEvent.parse(event)
    database = args.database or args.output / "events.sqlite"
    if database.exists() and not args.resume:
        parser.error(f"{database} already holds events; rerunning would count every delivery as a duplicate. "
                     "Use a new --output/--database, delete it, or pass --resume.")
    database.parent.mkdir(parents=True, exist_ok=True)
    report, queues = run_replay(events, truth, reference, database, args.capacity)
    write_json(args.output / "report.json", report)
    write_json(args.output / "queues.json", queues)
    print(json.dumps({"report": str(args.output / "report.json"),
                      "accepted": report["accepted_new_events"], "retries": report["duplicate_deliveries"],
                      "machine": report["environment"]["machine"],
                      "budget_comparison": report["budget_comparison"]}, indent=2))


if __name__ == "__main__":
    main()
