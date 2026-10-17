"""One batch queue combining real historical context and simulated scan evidence."""
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from batchguard_engine import historical_priorities
from inspection_stream import ReferenceIndex, ScanEvent
from model_foundation import CITIES, HISTORY_FEATURES, history_features
from scan_features import OBSERVATION_SECONDS, SCAN_FEATURES, extract_scan_features
from snapshot_store import ROOT, file_hash

FUSION_VERSION = "three-signal-baseline-v1"
DEFAULT_MODELS = ROOT / "models" / "baseline-v1"
FUSION_POLICIES = ("weighted", "tiered")
SIMULATED_STATES = {(lat, lon): state for _, state, lat, lon in CITIES}


def rule_scan_score(features):
    """Declared heuristic: 100 for an implausible-travel pack, 70 for a repeated-pack burst."""
    travel = features["max_pack_distance_km"] >= 100 and features["max_pack_speed_kmh"] > 900
    burst = features["max_events_per_pack_5min"] >= 10
    return (100.0 if travel else 70.0 if burst else 0.0), travel, burst


def corroboration(features):
    """0/50/100 for one/two/three or more asserted sources on one pack; independence unverified."""
    return min(100.0, max(0, int(features["max_sources_per_pack"])-1)*50.0)


def fuse(policy, history, scan, quality, alert):
    """Untrained fusion candidates; train_models.py selects one on validation data only."""
    if policy == "tiered":
        return 50+scan/2 if alert else history/2
    if policy == "weighted":
        return .50*history + .35*scan + .15*quality*int(alert)
    raise ValueError("Unknown fusion policy.")


def probability(model, rows, columns):
    return model.predict_proba(np.asarray(pd.DataFrame(rows)[columns], dtype=np.float32))[:, 1] if len(rows) else np.array([])


class TrainedModels:
    """Layer A/B models exported by train_models.py, verified against their model card before loading."""

    def __init__(self, directory=DEFAULT_MODELS):
        directory = Path(directory)
        card = json.loads((directory / "model_card.json").read_text())
        # Unpickling runs code, so only artifacts matching the card's recorded hashes are loaded.
        for name, expected in card["artifacts"].items():
            if file_hash(directory / name) != expected:
                raise ValueError(f"Model artifact changed: {name}")
        if card["scan"]["features_sha256"] != file_hash(ROOT / "scan_features.py"):
            raise ValueError("scan_features.py differs from the code the scan model was trained with.")
        self.card = card
        self.history = pickle.loads((directory / "history_model.pkl").read_bytes())
        self.scan = pickle.loads((directory / "scan_model.pkl").read_bytes())
        self.threshold = float(card["scan"]["threshold"])
        self.policy = card["fusion"]["selected_policy"]
        self.version = card["model_version"]



def load_models(directory=DEFAULT_MODELS):
    return TrainedModels(directory) if (Path(directory) / "model_card.json").is_file() else None


def history_scores(model, df, cutoff):
    """Layer A probability and percentile among every previously observed manufacturer signature."""
    features = history_features(df, cutoff)
    features["probability"] = probability(model, features, HISTORY_FEATURES)
    features["percentile"] = features["probability"].rank(pct=True)*100 if len(features) else []
    return features.set_index(features["manufacturer_key"].str.strip().str.casefold())


def rank_candidates(df, payloads, as_of=None, models=None):
    """Rank every candidate observed in the scan window; humans decide which to sample.

    Training and inference share extract_scan_features and history_features.
    No manufacturer identity is inferred from unverified free text; states come only from scan coordinates.
    """
    events = [ScanEvent.parse(payload) for payload in payloads]
    if not events:
        return []
    if as_of is None:
        as_of = max(event.timestamp for event in events)
    if isinstance(as_of, bool) or not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        raise ValueError("as_of must be a finite timestamp.")
    # Do not attach historical context from collection months after the scan decision.
    month = datetime.fromtimestamp(as_of, timezone.utc).strftime("%Y-%m")
    historical_df = df[df["collection_month"].lt(month)]
    reference = ReferenceIndex(historical_df, historical_priorities(historical_df))
    groups, seen_ids = defaultdict(list), {}
    for payload, event in zip(payloads, events):
        if event.event_id in seen_ids and seen_ids[event.event_id] != event:
            raise ValueError("Conflicting event_id in decision input.")
        seen_ids[event.event_id] = event
        if as_of-OBSERVATION_SECONDS <= event.timestamp <= as_of:
            groups[event.candidate].append((payload, event))
    if not groups:
        return []
    cids = sorted(groups)
    features = [extract_scan_features([p for p, _ in groups[cid]], as_of) for cid in cids]
    if models is not None:
        scan_probabilities = probability(models.scan, features, SCAN_FEATURES)
        history = history_scores(models.history, df, str(pd.Period(month, freq="M")-1))
        policy, version = models.policy, models.version
    else:
        policy, version = "weighted", FUSION_VERSION
    output = []
    for index, cid in enumerate(cids):
        observations = [p for p, _ in groups[cid]]
        event = groups[cid][0][1]
        values = features[index]
        rule, travel, burst = rule_scan_score(values)
        quality = corroboration(values)
        historical = reference.evidence(event)
        key = event.manufacturer_key.strip().casefold()
        reasons = []
        if travel:
            reasons.append("CLONE_PATTERN_TRAVEL_REVIEW")
        if burst:
            reasons.append("REPEATED_PACK_BURST_REVIEW")
        if models is not None:
            scan_probability = float(scan_probabilities[index])
            scan_score, alert = round(100*scan_probability, 1), scan_probability >= models.threshold
            row = history.loc[key] if key and key in history.index else None
            history_probability = None if row is None else float(row["probability"])
            history_score = 0.0 if row is None else round(float(row["percentile"]), 1)
            if alert:
                reasons.append("SCAN_MODEL_ALERT")
            if row is not None:
                reasons.append(f"PRIOR_NSQ_RECORDS={int(row['prior_records'])}")
                if row["records_last_3_months"]:
                    reasons.append(f"REPORTED_IN_LAST_3_MONTHS={int(row['records_last_3_months'])}")
        else:
            scan_probability, history_probability = None, None
            scan_score, alert = rule, rule > 0
            history_score = round(historical["historical_priority"], 2)
        if key in reference.scores:
            reasons.append("MANUFACTURER_HISTORY")
        else:
            reasons.append("NO_EARLIER_MANUFACTURER_HISTORY")
        if historical["record_ids"]:
            reasons.append("BATCH_REPORT_REFERENCE")
        if historical["spurious_report_match"]:
            reasons.append("SPURIOUS_REPORT_REFERENCE")
        if not historical["reference_match"]:
            reasons.append("REFERENCE_COVERAGE_UNKNOWN")
        reasons.append("FOLLOWUP_SAMPLE_STATUS_UNKNOWN")
        states = sorted({SIMULATED_STATES.get((e.latitude, e.longitude), "Unmapped location") for _, e in groups[cid]})
        output.append({
            "candidate_id": cid, "batch_no": event.batch_no, "product": event.product,
            "manufacturer": event.manufacturer_key or "Unavailable",
            "state": " / ".join(states) + " (simulated scans)",
            "historical_risk": history_score, "scan_anomaly": scan_score,
            "evidence_quality": quality, "asserted_sources": int(values["max_sources_per_pack"]),
            "history_probability": history_probability, "scan_probability": scan_probability,
            "scan_alert": bool(alert), "rule_scan_score": rule,
            "priority_score": round(fuse(policy, history_score, scan_score, quality, alert), 2),
            "reason_codes": reasons, "historical_record_ids": historical["record_ids"],
            "scan_features": values,
            "scan_timeline": sorted(observations, key=lambda p: (p["event_time"], p["event_id"])),
            "history_label": "Next-month report recurrence rank among earlier manufacturer signatures, not medicine defect probability",
            "evidence_label": "Asserted-source corroboration index; independence unverified",
            "scan_simulated": all(p["simulated"] for p in observations),
            "fusion_policy": policy, "fusion_version": version,
        })
    output.sort(key=lambda item: (-item["priority_score"], item["candidate_id"]))
    for rank, item in enumerate(output, 1):
        item["rank"] = rank
    return output


def build_decision_queue(df, payloads, capacity=10, as_of=None, models=None):
    """Return at most capacity unique candidates; capacity is a maximum, not an obligation to sample."""
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    return rank_candidates(df, payloads, as_of, models)[:capacity]
