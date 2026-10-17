"""One batch queue combining real historical context and simulated scan evidence."""
from collections import defaultdict
import math

from batchguard_engine import historical_priorities
from inspection_stream import ReferenceIndex, ScanEvent
from scan_features import OBSERVATION_SECONDS, extract_scan_features

FUSION_VERSION = "three-signal-baseline-v1"


def build_decision_queue(df, payloads, capacity=10, as_of=None):
    """Return candidate-level signals and a declared heuristic priority, without a model.

    Training and inference share extract_scan_features. Model fitting is a later stage.
    No manufacturer or state identity is inferred from unverified free text.
    """
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    events = [ScanEvent.parse(payload) for payload in payloads]
    if not events:
        return []
    if as_of is None:
        as_of = max(event.timestamp for event in events)
    if not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        raise ValueError("as_of must be a finite timestamp.")
    # Do not attach historical context from collection months after the scan decision.
    from datetime import datetime, timezone
    cutoff = datetime.fromtimestamp(as_of, timezone.utc).strftime("%Y-%m")
    historical_df = df[df["collection_month"].lt(cutoff)]
    reference = ReferenceIndex(historical_df, historical_priorities(historical_df))
    groups, seen_ids = defaultdict(list), {}
    for payload, event in zip(payloads, events):
        if event.event_id in seen_ids and seen_ids[event.event_id] != event:
            raise ValueError("Conflicting event_id in decision input.")
        seen_ids[event.event_id] = event
        if as_of-OBSERVATION_SECONDS <= event.timestamp <= as_of:
            groups[event.candidate].append(payload)
    output = []
    for cid, observations in groups.items():
        event = ScanEvent.parse(observations[0])
        features = extract_scan_features(observations, as_of)
        historical = reference.evidence(event)
        travel = features["max_pack_distance_km"] >= 100 and features["max_pack_speed_kmh"] > 900
        burst = features["max_events_per_pack_5min"] >= 10
        scan_score = 100.0 if travel else 70.0 if burst else 0.0
        sources = int(features["max_sources_per_pack"])
        quality = min(100.0, max(0, sources-1)*50.0)
        history_score = historical["historical_priority"]
        # Frozen baseline weights; they do not claim optimality or calibrated probabilities.
        priority = .50*history_score + .35*scan_score + .15*quality*int(scan_score > 0)
        reasons = []
        if travel:
            reasons.append("CLONE_PATTERN_TRAVEL_REVIEW")
        if burst:
            reasons.append("REPEATED_PACK_BURST_REVIEW")
        if historical["record_ids"]:
            reasons.append("BATCH_REPORT_REFERENCE")
        if event.manufacturer_key.strip().casefold() in reference.scores:
            reasons.append("MANUFACTURER_HISTORY")
        if not historical["reference_match"]:
            reasons.append("REFERENCE_COVERAGE_UNKNOWN")
        reasons.append("FOLLOWUP_SAMPLE_STATUS_UNKNOWN")
        output.append({
            "candidate_id": cid, "batch_no": event.batch_no, "product": event.product,
            "manufacturer": event.manufacturer_key or "Unavailable",
            "state": "Not established from source data",
            "historical_risk": round(history_score, 2), "scan_anomaly": scan_score,
            "evidence_quality": quality, "asserted_sources": sources,
            "priority_score": round(priority, 2), "reason_codes": reasons,
            "historical_record_ids": historical["record_ids"],
            "scan_features": features, "scan_timeline": sorted(observations, key=lambda p: p["event_time"]),
            "history_label": "Earlier reported recurrence index, not medicine defect probability",
            "evidence_label": "Asserted-source corroboration index; independence unverified",
            "scan_simulated": all(p["simulated"] for p in observations),
            "fusion_version": FUSION_VERSION,
        })
    output.sort(key=lambda item: (-item["priority_score"], item["candidate_id"]))
    for rank, item in enumerate(output[:capacity], 1):
        item["rank"] = rank
    return output[:capacity]
