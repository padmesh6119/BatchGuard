"""Train and score an independently adjudicated scan model, when field cases exist.

Physical-pack provenance is used to derive training labels only. It is never a
model feature or accepted in the scoring input. This module does not turn the
repository's scripted scans into evidence of field performance.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import inspect
import json
import math
from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from src.common import digest, file_hash, fit_and_select, probability, write_json
from src.detector import SCAN_FEATURES, confusion, extract_scan_features, rule_scan_score
from src.simulator import ScanEvent

QUALITY_FIELDS = ("location_accuracy_m", "clock_offset_seconds", "scanner_authenticated", "received_at")
FIELD_FEATURES = SCAN_FEATURES + ["worst_location_accuracy_m", "worst_abs_clock_offset_seconds",
                               "unauthenticated_fraction", "longest_receipt_delay_seconds",
                               "max_future_event_seconds"]
SPLITS = ("train", "validation", "test")
MAX_VALIDATION_FALSE_ALERT_RATE = 0.05
MAX_REVIEW_LOCATION_ACCURACY_M = 100.0
MAX_REVIEW_CLOCK_OFFSET_SECONDS = 60.0
MAX_REVIEW_RECEIPT_DELAY_SECONDS = 6 * 3600.0


def timestamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")
    return parsed.astimezone(timezone.utc).timestamp()


def text_field(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"Invalid {name}")
    return value


def observation_features(observations):
    """Return only measured scan and quality fields, never hidden outcome evidence."""
    if not isinstance(observations, list) or len(observations) < 2:
        raise ValueError("Each case needs at least two observations")
    events, corrected_payloads, corrected_times = [], [], []
    receipts, accuracies, offsets, authenticated = [], [], [], []
    for record in observations:
        if not isinstance(record, dict) or set(record) != {"event", *QUALITY_FIELDS}:
            raise ValueError("Observation needs event, receipt time, accuracy, clock offset, authentication")
        event = ScanEvent.parse(record["event"])
        if event.simulated:
            raise ValueError("Field observations cannot be marked simulated")
        accuracy, offset = record["location_accuracy_m"], record["clock_offset_seconds"]
        if (isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or
                not math.isfinite(accuracy) or not 0 <= accuracy <= 1_000_000):
            raise ValueError("Invalid location_accuracy_m")
        if (isinstance(offset, bool) or not isinstance(offset, (int, float)) or
                not math.isfinite(offset) or abs(offset) > 604_800):
            raise ValueError("Invalid clock_offset_seconds")
        if not isinstance(record["scanner_authenticated"], bool):
            raise ValueError("scanner_authenticated must be boolean")
        receipt = timestamp(record["received_at"], "received_at")
        if abs(receipt - event.timestamp) > 604_800:
            raise ValueError("Receipt time differs from event time by over seven days")
        corrected_time = event.timestamp - float(offset)
        try:
            corrected_iso = datetime.fromtimestamp(corrected_time, timezone.utc).isoformat()
        except (OverflowError, ValueError, OSError) as exc:
            raise ValueError("Clock correction is outside the supported timestamp range") from exc
        events.append(event)
        corrected_payloads.append({**record["event"], "event_time": corrected_iso})
        corrected_times.append(corrected_time)
        receipts.append(receipt)
        accuracies.append(float(accuracy))
        offsets.append(abs(float(offset)))
        authenticated.append(record["scanner_authenticated"])
    if len({event.candidate for event in events}) != 1:
        raise ValueError("A case must contain one product/batch/manufacturer candidate")
    unique = {}
    for event in events:
        if event.event_id in unique and event != unique[event.event_id]:
            raise ValueError("Conflicting event_id")
        unique[event.event_id] = event
    if len(unique) < 2:
        raise ValueError("A case needs at least two unique events")
    end = max(corrected_times)
    if end - min(corrected_times) > 6 * 3600:
        raise ValueError("A case must fit the six-hour scan window")
    features = extract_scan_features(corrected_payloads, end)
    features.update(worst_location_accuracy_m=max(accuracies),
                    worst_abs_clock_offset_seconds=max(offsets),
                    unauthenticated_fraction=1 - sum(authenticated) / len(authenticated),
                    longest_receipt_delay_seconds=max(abs(receipt - corrected_time)
                                                      for receipt, corrected_time in zip(receipts, corrected_times)),
                    max_future_event_seconds=max(max(0.0, corrected_time - receipt)
                                                 for receipt, corrected_time in zip(receipts, corrected_times)))
    # Split and adjudication times use trusted server receipt, not scanner clocks.
    return {name: float(features[name]) for name in FIELD_FEATURES}, unique, max(receipts)


def checked_case(case, labeled):
    if not isinstance(case, dict):
        raise ValueError("Each JSONL line must be an object")
    required = {"case_id", "site_id", "observations"}
    if labeled:
        required |= {"split", "physical_pack_ids", "adjudication"}
    if set(case) != required:
        raise ValueError(f"Case fields must be {sorted(required)}")
    case_id = text_field(case["case_id"], "case_id")
    site = text_field(case["site_id"], "site_id")
    features, events, receipt_end = observation_features(case["observations"])
    result = {"case_id": case_id, "site_id": site, "features": features, "events": events, "end": receipt_end,
              "rule_alert": rule_scan_score(features)[0] > 0}
    if not labeled:
        return result
    split = case["split"]
    if split not in SPLITS:
        raise ValueError("split must be train, validation, or test")
    provenance = case["physical_pack_ids"]
    if not isinstance(provenance, dict) or set(provenance) != set(events):
        raise ValueError("physical_pack_ids must cover every unique event_id exactly")
    physical = defaultdict(set)
    for event_id, event in events.items():
        physical[event.pack_id].add(text_field(provenance[event_id], "physical_pack_id"))
    adjudication = case["adjudication"]
    if not isinstance(adjudication, dict) or set(adjudication) != {"method", "evidence_ref", "reviewer_id", "adjudicated_at"}:
        raise ValueError("Adjudication requires method, evidence_ref, reviewer_id, adjudicated_at")
    if adjudication["method"] not in {"physical_inspection", "independent_pack_authentication"}:
        raise ValueError("Adjudication method must establish physical-pack identity")
    for name in ("evidence_ref", "reviewer_id"):
        text_field(adjudication[name], name)
    if timestamp(adjudication["adjudicated_at"], "adjudicated_at") < receipt_end:
        raise ValueError("Adjudication cannot precede the observations")
    result.update(split=split, label=int(any(len(ids) > 1 for ids in physical.values())))
    return result


def load_cases(path, labeled=True):
    cases = []
    for line_no, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            try:
                cases.append(checked_case(json.loads(line), labeled))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    if not cases:
        raise ValueError("No cases supplied")
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id must be unique")
    return cases


def validate_splits(cases):
    by_split = {name: [case for case in cases if case["split"] == name] for name in SPLITS}
    sites = defaultdict(set)
    owner_by_event, owner_by_pack = {}, {}
    for split, rows in by_split.items():
        if not rows or {row["label"] for row in rows} != {0, 1}:
            raise ValueError(f"{split} needs both independently adjudicated outcomes")
        for row in rows:
            sites[split].add(row["site_id"])
            for event_id, event in row["events"].items():
                pack_key = (event.candidate, event.pack_id)
                if event_id in owner_by_event or (pack_key in owner_by_pack and owner_by_pack[pack_key] != row["case_id"]):
                    raise ValueError("Cases share an event or candidate/pack identity")
                owner_by_event[event_id] = row["case_id"]
                owner_by_pack[pack_key] = row["case_id"]
    for i, left in enumerate(SPLITS):
        for right in SPLITS[i+1:]:
            if sites[left] & sites[right]:
                raise ValueError(f"{left} and {right} share a site")
    for left, right in zip(SPLITS, SPLITS[1:]):
        if max(row["end"] for row in by_split[left]) >= min(row["end"] for row in by_split[right]):
            raise ValueError("Splits must be chronological: train, validation, then test")
    return by_split


def frame(cases):
    return pd.DataFrame([case["features"] for case in cases], columns=FIELD_FEATURES).astype(np.float32)


def review_quality(features):
    """Abstain from scan-pattern review when the observation source is unreliable."""
    return (features["unauthenticated_fraction"] == 0 and
            features["worst_location_accuracy_m"] <= MAX_REVIEW_LOCATION_ACCURACY_M and
            features["worst_abs_clock_offset_seconds"] <= MAX_REVIEW_CLOCK_OFFSET_SECONDS and
            features["longest_receipt_delay_seconds"] <= MAX_REVIEW_RECEIPT_DELAY_SECONDS and
            features["max_future_event_seconds"] <= MAX_REVIEW_CLOCK_OFFSET_SECONDS)


def feature_fingerprint():
    return digest([QUALITY_FIELDS, FIELD_FEATURES, inspect.getsource(ScanEvent.parse),
                   inspect.getsource(extract_scan_features), inspect.getsource(observation_features),
                   inspect.getsource(review_quality)])


def choose_budget_threshold(labels, scores, maximum_fpr=MAX_VALIDATION_FALSE_ALERT_RATE, eligible=None):
    """Maximize validation recall subject to an empirical false-alert budget."""
    y = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    eligible = np.ones(len(y), dtype=bool) if eligible is None else np.asarray(eligible, dtype=bool)
    if len(eligible) != len(y):
        raise ValueError("Eligibility must match the number of scores")
    if not len(y) or not (~y).any() or not y.any():
        raise ValueError("Validation needs both classes")
    candidates = [float(np.nextafter(max(scores), math.inf))] + sorted(set(scores), reverse=True)
    valid = []
    for threshold in candidates:
        pred = (scores >= threshold) & eligible
        fp = int((pred & ~y).sum())
        if fp / int((~y).sum()) <= maximum_fpr:
            valid.append((int((pred & y).sum()), -fp, threshold))
    return max(valid)[2]


def wilson_bounds(successes, total, z=1.96):
    if total <= 0:
        raise ValueError("A rate needs a positive denominator")
    p = successes / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    delta = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z/total)
    return [max(0.0, center-delta), min(1.0, center+delta)]


def metrics(cases, scores, threshold):
    y = np.array([case["label"] for case in cases], dtype=int)
    eligible = np.array([review_quality(case["features"]) for case in cases], dtype=bool)
    pred = (np.asarray(scores) >= threshold) & eligible
    matrix = confusion(y, pred)
    negatives = matrix["false_positives"] + matrix["true_negatives"]
    positives = matrix["true_positives"] + matrix["false_negatives"]
    by_site = {}
    for site in sorted({case["site_id"] for case in cases}):
        indices = [index for index, case in enumerate(cases) if case["site_id"] == site]
        site_matrix = confusion(y[indices], pred[indices])
        site_negatives = site_matrix["false_positives"] + site_matrix["true_negatives"]
        site_positives = site_matrix["true_positives"] + site_matrix["false_negatives"]
        by_site[site] = {**site_matrix, "cases": len(indices), "positives": site_positives,
                         "negatives": site_negatives,
                         "false_alert_rate_95pct": (wilson_bounds(site_matrix["false_positives"], site_negatives)
                                                    if site_negatives else None),
                         "recall_95pct": (wilson_bounds(site_matrix["true_positives"], site_positives)
                                          if site_positives else None)}
    return {**matrix, "cases": len(cases), "sites": len({case["site_id"] for case in cases}),
            "by_site": by_site,
            "quality_eligible_cases": int(eligible.sum()),
            "average_precision": float(average_precision_score(y, scores)),
            "false_alert_rate": matrix["false_positives"] / negatives,
            "false_alert_rate_95pct": wilson_bounds(matrix["false_positives"], negatives),
            "recall_95pct": wilson_bounds(matrix["true_positives"], positives),
            "rule": confusion(y, [case["rule_alert"] for case in cases])}


def readiness(by_split, validation, test):
    reasons = []
    for split in SPLITS:
        rows = by_split[split]
        positive = sum(row["label"] for row in rows)
        negative = len(rows) - positive
        if len({row["site_id"] for row in rows}) < 2:
            reasons.append(f"{split}: fewer than two independent sites")
        if positive < 50 or negative < 200:
            reasons.append(f"{split}: fewer than 50 positive or 200 negative cases")
    for name, result in (("validation", validation), ("test", test)):
        if result["quality_eligible_cases"] / result["cases"] < 0.8:
            reasons.append(f"{name}: fewer than 80% of cases have review-quality telemetry")
        if result["false_alert_rate_95pct"][1] > MAX_VALIDATION_FALSE_ALERT_RATE:
            reasons.append(f"{name}: upper 95% false-alert bound exceeds 5%")
        if result["recall_95pct"][0] < 0.8:
            reasons.append(f"{name}: lower 95% recall bound is below 80%")
        sites = list(result["by_site"].values())
        if any(site["positives"] < 20 or site["negatives"] < 100 for site in sites):
            reasons.append(f"{name}: a site has fewer than 20 positive or 100 negative cases")
        if any(site["positives"] >= 20 and site["negatives"] >= 100 and
               (site["false_alert_rate_95pct"][1] > MAX_VALIDATION_FALSE_ALERT_RATE or
                site["recall_95pct"][0] < 0.8) for site in sites):
            reasons.append(f"{name}: a site fails the false-alert or recall bound")
    return reasons


def train(path, output, backend="sklearn"):
    source = Path(path)
    by_split = validate_splits(load_cases(source))
    train_rows, validation_rows, test_rows = (by_split[name] for name in SPLITS)
    model, selection = fit_and_select(frame(train_rows), [row["label"] for row in train_rows],
                                      frame(validation_rows), [row["label"] for row in validation_rows],
                                      backend)
    threshold = choose_budget_threshold([row["label"] for row in validation_rows],
                                        probability(model, frame(validation_rows)),
                                        eligible=[review_quality(row["features"]) for row in validation_rows])
    validation = metrics(validation_rows, probability(model, frame(validation_rows)), threshold)
    test = metrics(test_rows, probability(model, frame(test_rows)), threshold)
    reasons = readiness(by_split, validation, test)
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "field_model.pkl"
    artifact.write_bytes(pickle.dumps(model))
    card = {"purpose": "copied observed pack ID, never counterfeit or medicine safety",
            "source_sha256": file_hash(source), "backend": backend, "features": FIELD_FEATURES,
            "feature_code_sha256": feature_fingerprint(),
            "selection": selection, "threshold": threshold,
            "threshold_rule": "maximum validation recall at <=5% empirical false-alert rate, with quality abstention",
            "split_counts": {name: {"cases": len(rows), "positives": sum(row["label"] for row in rows),
                                    "negatives": len(rows) - sum(row["label"] for row in rows),
                                    "sites": len({row["site_id"] for row in rows})}
                             for name, rows in by_split.items()},
            "validation": validation, "test": test, "readiness_reasons": reasons,
            "field_review_ready": not reasons,
            "artifact_sha256": file_hash(artifact)}
    write_json(directory / "field_model_card.json", card)
    return card


def load_card(model_directory):
    """Check local artifact integrity and feature compatibility before reporting readiness."""
    directory = Path(model_directory)
    card = json.loads((directory / "field_model_card.json").read_text())
    if card["features"] != FIELD_FEATURES or card["feature_code_sha256"] != feature_fingerprint():
        raise ValueError("Field model feature code changed")
    artifact = directory / "field_model.pkl"
    if file_hash(artifact) != card["artifact_sha256"]:
        raise ValueError("Field model artifact changed")
    if card["field_review_ready"] != (not card["readiness_reasons"]):
        raise ValueError("Field model readiness card is inconsistent")
    return card


def score(path, model_directory, output):
    directory = Path(model_directory)
    card = load_card(directory)
    artifact = directory / "field_model.pkl"
    cases = load_cases(path, labeled=False)
    model = pickle.loads(artifact.read_bytes())
    scores = probability(model, frame(cases))
    output_rows = [{"case_id": case["case_id"], "site_id": case["site_id"],
                    "model_score": float(value), "rule_pattern": case["rule_alert"],
                    "quality_eligible": review_quality(case["features"]),
                    "review_flag": bool(card["field_review_ready"] and review_quality(case["features"])
                                        and value >= card["threshold"]),
                    "status": ("research_only" if not card["field_review_ready"] else
                               "insufficient_scan_quality" if not review_quality(case["features"]) else
                               "field_model_review")}
                   for case, value in zip(cases, scores)]
    write_json(output, {"model_card_sha256": file_hash(directory / "field_model_card.json"),
                        "field_review_ready": card["field_review_ready"], "cases": output_rows})
    return output_rows


def write_template(path):
    """Write one deliberately non-trainable schema example for data integration."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    stamp = "2026-09-01T10:00:00+00:00"
    observations = []
    for index, (latitude, longitude, source) in enumerate(
            ((13.08, 80.27, "REPLACE-SCANNER-A"), (28.61, 77.21, "REPLACE-SCANNER-B"))):
        event_id = f"REPLACE-EVENT-{index + 1}"
        observations.append({
            "event": {"event_id": event_id, "pack_id": "REPLACE-OBSERVED-CODE",
                      "product": "REPLACE-PRODUCT", "batch_no": "REPLACE-BATCH",
                      "manufacturer_key": "REPLACE-MANUFACTURER",
                      "event_time": stamp if index == 0 else "2026-09-01T10:04:00+00:00",
                      "source_id": source, "latitude": latitude, "longitude": longitude,
                      "simulated": True},
            "received_at": stamp if index == 0 else "2026-09-01T10:04:03+00:00",
            "location_accuracy_m": 12.0, "clock_offset_seconds": 0.0,
            "scanner_authenticated": True})
    example = {"case_id": "REPLACE-CASE-ID", "site_id": "REPLACE-SITE-ID", "split": "train",
               "observations": observations,
               "physical_pack_ids": {"REPLACE-EVENT-1": "REPLACE-VERIFIED-PHYSICAL-PACK-A",
                                     "REPLACE-EVENT-2": "REPLACE-VERIFIED-PHYSICAL-PACK-B"},
               "adjudication": {"method": "physical_inspection", "evidence_ref": "REPLACE-PRIVATE-EVIDENCE-REF",
                                "reviewer_id": "REPLACE-REVIEWER-ID", "adjudicated_at": "2026-09-02T09:00:00+00:00"}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(example, separators=(",", ":")) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="write a non-trainable schema example")
    template.add_argument("--output", type=Path, required=True)
    training = commands.add_parser("train", help="fit from adjudicated field JSONL")
    training.add_argument("cases", type=Path)
    training.add_argument("--output", type=Path, required=True)
    training.add_argument("--backend", choices=("sklearn", "snapml"), default="sklearn")
    scoring = commands.add_parser("score", help="score unlabeled field JSONL")
    scoring.add_argument("cases", type=Path)
    scoring.add_argument("--model", type=Path, required=True)
    scoring.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "template":
            print(f"Wrote schema example to {write_template(args.output)}. Replace every placeholder with audited field data.")
        elif args.command == "train":
            if not args.cases.is_file():
                raise FileNotFoundError(
                    f"Training dataset not found: {args.cases}. The repository has no adjudicated scan data. "
                    "Collect real cases first; 'template' creates a placeholder, not training data.")
            card = train(args.cases, args.output, args.backend)
            print(json.dumps({"field_review_ready": card["field_review_ready"],
                              "readiness_reasons": card["readiness_reasons"], "test": card["test"]}, indent=2))
        else:
            if not args.cases.is_file():
                raise FileNotFoundError(f"Scoring input not found: {args.cases}; provide unlabeled field cases")
            card_path = args.model / "field_model_card.json"
            if not card_path.is_file():
                raise FileNotFoundError(f"No trained field model at {args.model}; train successfully before scoring")
            print(f"Scored {len(score(args.cases, args.model, args.output))} cases into {args.output}")
    except (FileNotFoundError, FileExistsError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
