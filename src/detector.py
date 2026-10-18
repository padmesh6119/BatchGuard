"""M2 — Layer B detector: observable scan features, the declared rule, the corroboration gate, and the trained model.

Labels are simulated. The rule drives live alerts because the trained model did not beat it on held-out families.
"""
from collections import defaultdict
import math

import numpy as np
import pandas as pd

from src.common import SEED, fit_and_select, probability
from src.simulator import HELDOUT_SCENARIOS, ScanEvent, distance_km

OBSERVATION_SECONDS = 6 * 3600
SCAN_FEATURES = ["unique_events", "unique_packs", "max_events_per_pack", "max_sources_per_pack",
                 "max_pack_distance_km", "max_pack_speed_kmh", "max_events_per_pack_5min",
                 "observation_span_minutes", "retry_fraction"]


def extract_scan_features(payloads, as_of=None):
    """Use only events received up to as_of, within the declared six-hour window; training and inference share this.

    Event, pack and source IDs, product identity and scenario labels are not features.
    A source count describes asserted identifiers, not verified independent organizations.
    """
    events = [ScanEvent.parse(payload) for payload in payloads]
    if not events:
        return {name: 0.0 for name in SCAN_FEATURES}
    if as_of is None:
        as_of = max(event.timestamp for event in events)
    if not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        raise ValueError("as_of must be a finite Unix timestamp.")
    unique, deliveries = {}, 0
    for event in events:
        if not as_of-OBSERVATION_SECONDS <= event.timestamp <= as_of:
            continue
        deliveries += 1
        if event.event_id in unique and unique[event.event_id] != event:
            raise ValueError("Conflicting event_id in feature input.")
        unique[event.event_id] = event
    active = sorted(unique.values(), key=lambda event: (event.timestamp, event.event_id))
    packs, candidates = defaultdict(list), set()
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


def rule_scan_score(features):
    """Declared rule: 100 for one pack >=100 km apart faster than 900 km/h, 70 for >=10 scans of one pack in 5 min."""
    travel = features["max_pack_distance_km"] >= 100 and features["max_pack_speed_kmh"] > 900
    burst = features["max_events_per_pack_5min"] >= 10
    return (100.0 if travel else 70.0 if burst else 0.0), travel, burst


def corroboration(features):
    """Corroboration gate: 0/50/100 for one/two/three or more asserted sources on one pack; independence unverified."""
    return min(100.0, max(0, int(features["max_sources_per_pack"])-1)*50.0)


def featurize(episodes):
    rows = []
    for episode in episodes:
        values = extract_scan_features(episode["events"], episode["observation_end"])
        rows.append({"example_id": episode["example_id"], "episode_id": episode["episode_id"], "split": episode["split"],
                     "scenario": episode["scenario"], "label": episode["label"],
                     "baseline_rule_prediction": int(rule_scan_score(values)[0] > 0), **values})
    return pd.DataFrame(rows)


def split(features, name):
    part = features[features["split"].eq(name)].reset_index(drop=True)
    return part[SCAN_FEATURES], part["label"], part


def choose_threshold(y, scores):
    """Maximize validation F1; ties keep the higher threshold (fewer alerts)."""
    y, scores = np.asarray(y), np.asarray(scores)
    best = (-1.0, 1.0)
    for threshold in sorted(set(np.round(scores, 6)), reverse=True):
        predicted = scores >= threshold
        tp = float((predicted & (y == 1)).sum())
        precision = tp/predicted.sum() if predicted.sum() else 0
        recall = tp/(y == 1).sum()
        f1 = 2*precision*recall/(precision+recall) if precision+recall else 0
        if f1 > best[0]:
            best = (f1, float(threshold))
    return best[1]


def confusion(y, predicted):
    y, predicted = np.asarray(y).astype(bool), np.asarray(predicted).astype(bool)
    tp, fp = int((y & predicted).sum()), int((~y & predicted).sum())
    fn, tn = int((y & ~predicted).sum()), int((~y & ~predicted).sum())
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn, "true_negatives": tn,
            "precision": tp/(tp+fp) if tp+fp else None, "recall": tp/(tp+fn) if tp+fn else None}


def train(features, backend="sklearn", seed=SEED):
    x, y, _ = split(features, "train")
    xv, yv, _ = split(features, "validation")
    model, selection = fit_and_select(x, y, xv, yv, backend, seed)
    selection["threshold"] = choose_threshold(yv, probability(model, xv))
    selection["threshold_rule"] = "maximum validation F1"
    return model, selection


def evaluate(model, features, threshold):
    """Held-out episodes, read once: model vs rule overall and per scenario family."""
    from sklearn.metrics import average_precision_score
    x, y, metadata = split(features, "test")
    scores = probability(model, x)
    predicted, rule = scores >= threshold, metadata["baseline_rule_prediction"].to_numpy().astype(bool)
    families = [{"scenario": scenario, "held_out_family": scenario in HELDOUT_SCENARIOS,
                 "clone_label": int(y[part.index].iloc[0]), "episodes": len(part),
                 "model_alert_rate": float(predicted[part.index].mean()), "rule_alert_rate": float(rule[part.index].mean())}
                for scenario, part in metadata.groupby("scenario", sort=True)]
    return {"unit": "simulated batch observation episode", "test_episodes": len(y), "test_clones": int(y.sum()),
            "model": {**confusion(y, predicted), "average_precision": float(average_precision_score(y, scores))},
            "rule_baseline": confusion(y, rule), "families": families,
            "test_predictions": pd.DataFrame({"example_id": metadata["example_id"], "probability": scores})}
