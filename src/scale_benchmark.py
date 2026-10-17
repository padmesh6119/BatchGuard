"""Synthetic stream load for measuring the existing BatchGuard decision path.

This is a performance workload, not a clone-detection accuracy dataset. Pattern
frequencies are explicit assumptions and are not estimates of field traffic.
"""
import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import resource
import statistics
import time

import numpy as np

from src import layer_a
from src.common import DATA_PROCESSED, OUTPUTS, SEED, environment, file_hash, host_label, write_json
from src.detector import OBSERVATION_SECONDS
from src.fusion import decision_context, load_models, rank_candidates
from src.simulator import ScanEvent

PATTERNS = {
    "routine": ("single",) * 94 + ("repeat",) * 4 + ("burst", "conflict"),
    "repeat_heavy": ("single",) * 40 + ("repeat",) * 40 + ("burst",) * 10 + ("conflict",) * 10,
}
EVENTS_PER_PATTERN = {"single": 1, "repeat": 3, "burst": 12, "conflict": 2}
START = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)


def manufacturer_keys(df):
    keys = sorted({str(value).strip() for value in df["manufacturer_name_normalized"] if str(value).strip()})
    if not keys:
        raise ValueError("No manufacturer signatures available for load generation")
    return keys[:64]


def generate_events(count, profile, keys, seed=SEED):
    """Yield exactly count events, ordered by event time, with one-second-spaced candidate groups."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    if profile not in PATTERNS:
        raise ValueError(f"profile must be one of {', '.join(PATTERNS)}")
    if not keys:
        raise ValueError("keys must contain at least one manufacturer signature")
    emitted = case = 0
    while emitted < count:
        pattern = PATTERNS[profile][(case + seed) % len(PATTERNS[profile])]
        size = EVENTS_PER_PATTERN[pattern]
        origin = START + timedelta(seconds=case)
        manufacturer = f"UNSEEN-SYN-{case}" if case % 5 == 0 else keys[(case + seed) % len(keys)]
        pack = f"SYN-PACK-{case}"
        for index in range(min(size, count - emitted)):
            latitude, longitude = (28.61, 77.21) if pattern == "conflict" and index == 1 else (13.08, 80.27)
            second_source = (pattern == "burst" and index >= 6) or (pattern == "conflict" and index == 1)
            event = {
                "event_id": f"SYN-EVENT-{case}-{index}", "pack_id": pack,
                "product": "Synthetic load tablet", "batch_no": f"SYN-LOAD-{case}",
                "manufacturer_key": manufacturer,
                "event_time": (origin + timedelta(milliseconds=50 * index)).isoformat(),
                "source_id": f"SYN-SCANNER-{(case + int(second_source)) % 200}",
                "latitude": latitude, "longitude": longitude, "simulated": True,
            }
            yield pattern, case, event
            emitted += 1
        case += 1


def percentile_summary(values):
    values = np.asarray(values, dtype=float)
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)), "max": float(values.max())}


def process_stream(df, models, count, profile, keys, seed=SEED, queue_every=500, capacity=10):
    """Score each arriving scan through rank_candidates and maintain a six-hour active queue."""
    if isinstance(queue_every, bool) or not isinstance(queue_every, int) or queue_every < 1:
        raise ValueError("queue_every must be a positive integer")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise ValueError("capacity must be a positive integer")
    context_start = time.perf_counter()
    context = decision_context(df, START.strftime("%Y-%m"), models)
    context_seconds = time.perf_counter() - context_start
    buckets, latest, expiry = defaultdict(deque), {}, deque()
    patterns, pattern_events = Counter(), Counter()
    latencies, snapshot_ms = [], []
    events_hasher = hashlib.sha256()
    decisions_hasher = hashlib.sha256()
    alerts = 0
    run_start = time.perf_counter()
    for number, (pattern, case, payload) in enumerate(generate_events(count, profile, keys, seed), 1):
        events_hasher.update((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode())
        pattern_events[pattern] += 1
        if payload["event_id"].endswith("-0"):
            patterns[pattern] += 1
        event_start = time.perf_counter()
        event = ScanEvent.parse(payload)
        while expiry and expiry[0][0] < event.timestamp - OBSERVATION_SECONDS:
            _, old_candidate, old_id = expiry.popleft()
            old = buckets[old_candidate].popleft()
            if old["event_id"] != old_id:
                raise AssertionError("Active-window eviction order changed")
            if not buckets[old_candidate]:
                del buckets[old_candidate]
                latest.pop(old_candidate, None)
        buckets[event.candidate].append(payload)
        expiry.append((event.timestamp, event.candidate, event.event_id))
        if context["month"] != payload["event_time"][:7]:
            raise ValueError("Workload crossed a month; use a shorter sample for a comparable fixed context")
        row = rank_candidates(df, buckets[event.candidate], event.timestamp, models, context)[0]
        decision = (row["candidate_id"], row["priority_score"], row["historical_risk"],
                    row["scan_anomaly"], row["scan_alert"], row["model_scan_alert"])
        decisions_hasher.update((json.dumps(decision, separators=(",", ":")) + "\n").encode())
        latest[event.candidate] = row["priority_score"]
        alerts += int(row["scan_alert"])
        latencies.append((time.perf_counter() - event_start) * 1000)
        if number % queue_every == 0 or number == count:
            snapshot_start = time.perf_counter()
            sorted(latest.items(), key=lambda item: (-item[1], item[0]))[:capacity]
            snapshot_ms.append((time.perf_counter() - snapshot_start) * 1000)
    wall_seconds = time.perf_counter() - run_start
    cpu = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "events": count, "candidate_groups": sum(patterns.values()),
        "pattern_cases": dict(sorted(patterns.items())), "pattern_events": dict(sorted(pattern_events.items())),
        "workload_sha256": events_hasher.hexdigest(), "decision_sha256": decisions_hasher.hexdigest(),
        "context_build_seconds": context_seconds,
        "stream_wall_seconds": wall_seconds, "events_per_second_wall": count / wall_seconds,
        "per_event_decision_ms": percentile_summary(latencies),
        "queue_snapshot_ms": percentile_summary(snapshot_ms),
        "snapshots": len(snapshot_ms), "active_candidates_at_end": len(latest),
        "alerts_on_arriving_events": alerts, "peak_rss_kib_process": cpu.ru_maxrss,
    }


def benchmark(count=5000, profile="routine", backend="sklearn", repeats=3, queue_every=500,
              capacity=10, seed=SEED, output=None):
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    df = layer_a.load_dataset()
    keys = manufacturer_keys(df)
    models = load_models(backend)
    if models is None:
        raise FileNotFoundError(f"No trained {backend} model is available")
    runs = [process_stream(df, models, count, profile, keys, seed, queue_every, capacity) for _ in range(repeats)]
    hashes = {run["workload_sha256"] for run in runs}
    if len(hashes) != 1:
        raise AssertionError("Synthetic workload changed between repeats")
    decisions = {run["decision_sha256"] for run in runs}
    if len(decisions) != 1:
        raise AssertionError("Decisions changed between repeats")
    throughput = statistics.median(run["events_per_second_wall"] for run in runs)
    result = {
        "scope": "Synthetic in-memory event generation plus sequential decision processing; no network, disk ingest, concurrent clients, or sustained-run claim.",
        "host": host_label(), "environment": environment(), "backend": backend,
        "model_version": models.version, "model_type": type(models.scan).__name__,
        "scan_model_selection": models.card["scan"]["selected"],
        "scan_model_threshold": models.threshold,
        "scan_test_predictions_sha256": models.card["artifacts"]["scan_test_predictions.csv"],
        "hardware_acceleration_verified": False,
        "processed_manifest_sha256": file_hash(DATA_PROCESSED / "manifest.json"),
        "seed": seed, "profile": profile, "profile_case_cycle": dict(Counter(PATTERNS[profile])),
        "profile_rates_are_assumptions": True, "events_requested": count,
        "queue_every_events": queue_every, "capacity": capacity, "repeats": repeats,
        "workload_sha256": runs[0]["workload_sha256"],
        "decision_sha256": runs[0]["decision_sha256"], "runs": runs,
        "events_per_second_median": throughput,
        "arithmetic_capacity_only": [
            {"scans_per_day": volume, "average_required_per_second": volume / 86400,
             "ten_x_peak_required_per_second": volume / 8640,
             "headroom_vs_average": throughput / (volume / 86400),
             "headroom_vs_ten_x_peak": throughput / (volume / 8640)}
            for volume in (1_000_000, 10_000_000, 100_000_000)
        ],
    }
    path = Path(output) if output else OUTPUTS / f"scale_{host_label()}_{backend}_{profile}.json"
    write_json(path, result)
    return path, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=5000)
    parser.add_argument("--profile", choices=tuple(PATTERNS), default="routine")
    parser.add_argument("--backend", choices=("sklearn", "snapml"), default="sklearn")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--queue-every", type=int, default=500)
    parser.add_argument("--capacity", type=int, default=10)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path, result = benchmark(args.events, args.profile, args.backend, args.repeats,
                             args.queue_every, args.capacity, args.seed, args.output)
    print(f"{path}: {result['events_per_second_median']:.1f} events/s; workload {result['workload_sha256']}")


if __name__ == "__main__":
    main()
