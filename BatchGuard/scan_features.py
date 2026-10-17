"""Observable scan features shared by training preparation and later inference."""
from collections import defaultdict
import math

from inspection_stream import ScanEvent, distance_km

OBSERVATION_SECONDS = 6 * 3600
SCAN_FEATURES = ["unique_events", "unique_packs", "max_events_per_pack",
                 "max_sources_per_pack", "max_pack_distance_km", "max_pack_speed_kmh",
                 "max_events_per_pack_5min", "observation_span_minutes", "retry_fraction"]


def extract_scan_features(payloads, as_of=None):
    """Use only received events up to as_of, within the declared observation window.

    Event IDs, pack IDs, source IDs, product identity and scenario labels are not features.
    A source count describes asserted identifiers, not verified independent organizations.
    """
    events = [ScanEvent.parse(payload) for payload in payloads]
    if not events:
        return {name: 0.0 for name in SCAN_FEATURES}
    if as_of is None:
        as_of = max(event.timestamp for event in events)
    if not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        raise ValueError("as_of must be a finite Unix timestamp.")
    unique = {}
    deliveries = 0
    for event in events:
        if not as_of-OBSERVATION_SECONDS <= event.timestamp <= as_of:
            continue
        deliveries += 1
        if event.event_id in unique and unique[event.event_id] != event:
            raise ValueError("Conflicting event_id in feature input.")
        unique[event.event_id] = event
    active = sorted(unique.values(), key=lambda event: (event.timestamp, event.event_id))
    packs = defaultdict(list)
    candidates = set()
    for event in active:
        packs[(event.candidate, event.pack_id)].append(event)
        candidates.add(event.candidate)
    if len(candidates) > 1:
        raise ValueError("Scan features require one product/batch/manufacturer candidate.")
    result = {name: 0.0 for name in SCAN_FEATURES}
    result["unique_events"] = len(active)
    result["unique_packs"] = len(packs)
    result["retry_fraction"] = (deliveries-len(active))/deliveries if deliveries else 0.0
    result["observation_span_minutes"] = (active[-1].timestamp-active[0].timestamp)/60 if active else 0.0
    for scans in packs.values():
        result["max_events_per_pack"] = max(result["max_events_per_pack"], len(scans))
        result["max_sources_per_pack"] = max(result["max_sources_per_pack"], len({e.source_id for e in scans}))
        for i, event in enumerate(scans):
            recent = sum(0 <= event.timestamp-e.timestamp <= 300 for e in scans[:i+1])
            result["max_events_per_pack_5min"] = max(result["max_events_per_pack_5min"], recent)
            for previous in scans[:i]:
                distance = distance_km(event.latitude, event.longitude, previous.latitude, previous.longitude)
                seconds = event.timestamp-previous.timestamp
                speed = min(100000.0, distance*3600/seconds) if seconds > 0 else (100000.0 if distance else 0.0)
                result["max_pack_distance_km"] = max(result["max_pack_distance_km"], distance)
                result["max_pack_speed_kmh"] = max(result["max_pack_speed_kmh"], speed)
    return {name: float(result[name]) for name in SCAN_FEATURES}


def scan_rule_baseline(features):
    """An explicit baseline using the same observation window/features as a future model."""
    travel = features["max_pack_distance_km"] >= 100 and features["max_pack_speed_kmh"] > 900
    burst = features["max_events_per_pack_5min"] >= 10
    return int(travel or burst)
