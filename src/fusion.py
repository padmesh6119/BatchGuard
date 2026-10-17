"""M3 — three separate signals and one capacity-aware queue; end-to-end run and stream benchmark.

Historical risk (real data), scan anomaly (simulated, declared rule) and evidence quality stay separate columns.
Humans decide what to sample. Nothing here blocks medicine or declares counterfeiting.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import importlib.util
import inspect
import json
import math
from pathlib import Path
import pickle
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src import detector, layer_a, simulator
from src.common import (BANNER, MODELS, OUTPUTS, SEED, digest, environment, file_hash, host_label, probability,
                        selection_weights, write_json)
from src.detector import OBSERVATION_SECONDS, SCAN_FEATURES, corroboration, extract_scan_features, rule_scan_score
from src.layer_a import HISTORY_FEATURES, historical_priorities, history_features, history_scores
from src.simulator import CITIES, ScanEvent, candidate_id

FUSION_POLICIES = ("weighted", "tiered")
QUEUE_BUDGETS = (10, 25, 50, 100, 150)
SIMULATED_STATES = {(lat, lon): state for _, state, lat, lon in CITIES}
FEATURE_CODE_SHA256 = {"history": digest(inspect.getsource(history_features)),
                       "scan": digest(inspect.getsource(extract_scan_features))}


def fuse(policy, history, scan, quality, alert):
    """Untrained fusion candidates; one is chosen on validation data only."""
    if policy == "tiered":
        return 50+scan/2 if alert else history/2
    if policy == "weighted":
        return .50*history + .35*scan + .15*quality*int(alert)
    raise ValueError("Unknown fusion policy.")


class ReferenceIndex:
    """Earlier published records for an exact product/batch/manufacturer-text candidate."""

    def __init__(self, df, priorities):
        self.rows = defaultdict(list)
        self.scores = {str(k).strip().casefold(): float(s) for k, s in zip(priorities["manufacturer_key"], priorities["priority_index"])}
        for row in df[["build_record_id", "product", "batch_no", "manufacturer_name_normalized", "source_category"]].to_dict("records"):
            if str(row["batch_no"]).strip():
                self.rows[candidate_id(row["product"], row["batch_no"], row["manufacturer_name_normalized"])].append(row)

    def evidence(self, event):
        rows = self.rows.get(event.candidate, [])
        return {"reference_match": bool(rows), "historical_priority": self.scores.get(event.manufacturer_key.strip().casefold(), 0.0),
                "record_ids": sorted({r["build_record_id"] for r in rows}),
                "spurious_report_match": any(r["source_category"] == "spurious" for r in rows)}


class TrainedModels:
    """Layer A/B models with a card; artifacts are hash-checked before unpickling (unpickling runs code)."""

    def __init__(self, directory):
        directory = Path(directory)
        card = json.loads((directory / "model_card.json").read_text())
        for name, expected in card["artifacts"].items():
            if file_hash(directory / name) != expected:
                raise ValueError(f"Model artifact changed: {name}")
        if card["feature_code_sha256"] != FEATURE_CODE_SHA256:
            raise ValueError("Feature code differs from the code these models were trained with.")
        self.card, self.directory = card, directory
        self.history = pickle.loads((directory / "history_model.pkl").read_bytes())
        self.scan = pickle.loads((directory / "scan_model.pkl").read_bytes())
        self.threshold = float(card["scan"]["threshold"])
        self.policy = card["fusion"]["selected_policy"]
        self.version = card["model_version"]


def load_models(backend="sklearn", root=MODELS):
    """None when the backend was never trained or its package (sklearn, snapml) is not installed here."""
    directory = Path(root) / backend
    if not (directory / "model_card.json").is_file() or importlib.util.find_spec(backend) is None:
        return None
    return TrainedModels(directory)


def decision_context(df, month, models=None):
    """Everything that depends only on the data and decision month; build once, reuse for every scan."""
    historical_df = df[df["collection_month"].lt(month)]
    context = {"month": month, "models": None if models is None else models.version,
               "reference": ReferenceIndex(historical_df, historical_priorities(historical_df))}
    if models is not None:
        context["history"] = history_scores(models.history, df, str(pd.Period(month, freq="M")-1))
    return context


def rank_candidates(df, payloads, as_of=None, models=None, context=None):
    """Rank every candidate seen in the six-hour scan window; capacity is applied by the caller.

    The rule drives scan alerts (the trained scan model lost to it on held-out families); the model's
    probability is shown alongside. History comes only from months before the decision.
    """
    events = [ScanEvent.parse(payload) for payload in payloads]
    if not events:
        return []
    if as_of is None:
        as_of = max(event.timestamp for event in events)
    if isinstance(as_of, bool) or not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        raise ValueError("as_of must be a finite timestamp.")
    month = datetime.fromtimestamp(as_of, timezone.utc).strftime("%Y-%m")
    if context is None or context["month"] != month or context["models"] != (None if models is None else models.version):
        context = decision_context(df, month, models)
    reference = context["reference"]
    groups, seen = defaultdict(list), {}
    for payload, event in zip(payloads, events):
        if event.event_id in seen and seen[event.event_id] != event:
            raise ValueError("Conflicting event_id in decision input.")
        seen[event.event_id] = event
        if as_of-OBSERVATION_SECONDS <= event.timestamp <= as_of:
            groups[event.candidate].append((payload, event))
    if not groups:
        return []
    cids = sorted(groups)
    features = [extract_scan_features([p for p, _ in groups[cid]], as_of) for cid in cids]
    if models is not None:
        scan_probabilities = probability(models.scan, features, SCAN_FEATURES)
        history, policy, version = context["history"], models.policy, models.version
    else:
        policy, version = "weighted", "untrained-baseline"
    output = []
    for index, cid in enumerate(cids):
        observations, event, values = [p for p, _ in groups[cid]], groups[cid][0][1], features[index]
        rule, travel, burst = rule_scan_score(values)
        quality, historical = corroboration(values), reference.evidence(event)
        key = event.manufacturer_key.strip().casefold()
        reasons = (["CLONE_PATTERN_TRAVEL_REVIEW"] if travel else []) + (["REPEATED_PACK_BURST_REVIEW"] if burst else [])
        if models is not None:
            scan_probability = float(scan_probabilities[index])
            model_alert = scan_probability >= models.threshold
            row = history.loc[key] if key and key in history.index else None
            history_probability = None if row is None else float(row["probability"])
            history_score = 0.0 if row is None else round(float(row["percentile"]), 1)
            # The model has only synthetic labels and fails the separate nuisance challenge.
            # Keep its score for research, never add an operational alert or reason from it.
            if row is not None:
                reasons.append(f"PRIOR_NSQ_RECORDS={int(row['prior_records'])}")
                if row["records_last_3_months"]:
                    reasons.append(f"REPORTED_IN_LAST_3_MONTHS={int(row['records_last_3_months'])}")
        else:
            scan_probability, history_probability, model_alert = None, None, None
            history_score = round(historical["historical_priority"], 2)
        if rule > 0:
            reasons.append("SCAN_CAUSE_UNVERIFIED")
        reasons.append("MANUFACTURER_HISTORY" if key in reference.scores else "NO_EARLIER_MANUFACTURER_HISTORY")
        reasons += ["BATCH_REPORT_REFERENCE"] if historical["record_ids"] else []
        reasons += ["SPURIOUS_REPORT_REFERENCE"] if historical["spurious_report_match"] else []
        reasons += [] if historical["reference_match"] else ["REFERENCE_COVERAGE_UNKNOWN"]
        reasons.append("FOLLOWUP_SAMPLE_STATUS_UNKNOWN")
        states = sorted({SIMULATED_STATES.get((e.latitude, e.longitude), "Unmapped location") for _, e in groups[cid]})
        output.append({
            "candidate_id": cid, "batch_no": event.batch_no, "product": event.product,
            "manufacturer": event.manufacturer_key or "Unavailable", "state": " / ".join(states) + " (simulated scans)",
            "historical_risk": history_score, "scan_anomaly": rule, "evidence_quality": quality,
            "asserted_sources": int(values["max_sources_per_pack"]),
            "history_probability": history_probability, "scan_probability": scan_probability,
            "scan_alert": rule > 0, "model_scan_alert": None if model_alert is None else bool(model_alert),
            "priority_score": round(fuse(policy, history_score, rule, quality, rule > 0), 2),
            "reason_codes": reasons, "historical_record_ids": historical["record_ids"], "scan_features": values,
            "scan_timeline": sorted(observations, key=lambda p: (p["event_time"], p["event_id"])),
            "scan_simulated": all(p["simulated"] for p in observations), "fusion_policy": policy, "fusion_version": version})
    output.sort(key=lambda item: (-item["priority_score"], item["candidate_id"]))
    for rank, item in enumerate(output, 1):
        item["rank"] = rank
    return output


def build_decision_queue(df, payloads, capacity=10, as_of=None, models=None, context=None):
    """At most capacity unique candidates; capacity is a maximum, not an obligation to sample."""
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    return rank_candidates(df, payloads, as_of, models, context)[:capacity]


def retime(episodes, end):
    """Shift each episode so it ends at `end`; keeps every episode's own six-hour window intact."""
    events = []
    for episode in episodes:
        shift = timedelta(seconds=end.timestamp()-max(ScanEvent.parse(p).timestamp for p in episode["events"]))
        events.extend(dict(p, event_id=f"{episode['episode_id']}:{p['event_id']}",
                           event_time=(datetime.fromisoformat(p["event_time"])+shift).isoformat()) for p in episode["events"])
    return events


def queue_pool(df, episodes, split, month, history_model, scan_model, threshold):
    """A split's episodes scored through the live queue on the 15th of the target month.

    Episodes on the same real reference batch merge into one candidate. Two labels: simulated clone,
    and whether the manufacturer text is really reported in that month's NSQ lists. Only batches published
    before the month enter the pool: a batch first published in or after it would be selected on the outcome.
    """
    earlier = df[df["collection_month"].lt(month)]
    known = {candidate_id(p, b, m) for p, b, m in zip(earlier["product"], earlier["batch_no"], earlier["manufacturer_name_normalized"])}
    chosen = [e for e in episodes if e["split"] == split and ScanEvent.parse(e["events"][0]).candidate in known]
    clone = defaultdict(int)
    for episode in chosen:
        cid = ScanEvent.parse(episode["events"][0]).candidate
        clone[cid] = max(clone[cid], episode["label"])
    end = datetime.fromisoformat(f"{month}-15T12:00:00+00:00")
    models = SimpleNamespace(history=history_model, scan=scan_model, threshold=threshold, policy="weighted",
                             version=f"evaluation-{split}")
    reported = set(layer_a.nsq_records(df).loc[lambda d: d["collection_month"].eq(month),
                                                "manufacturer_name_normalized"].str.strip().str.casefold()) - {""}
    return pd.DataFrame([{"clone": clone[c["candidate_id"]], "recurrence": int(c["manufacturer"].strip().casefold() in reported),
                          "history": c["historical_risk"], "rule": c["scan_anomaly"], "scan": 100*c["scan_probability"],
                          "quality": c["evidence_quality"]}
                         for c in rank_candidates(df, retime(chosen, end), end.timestamp(), models)])


def queue_metrics(pool):
    policies = {"history_only": pool["history"], "scan_rule_only": pool["rule"], "scan_model_only": pool["scan"],
                **{f"fused_{p}": pool.apply(lambda r: fuse(p, r["history"], r["rule"], r["quality"], r["rule"] > 0), axis=1)
                   for p in FUSION_POLICIES},
                "random_expectation": pd.Series(0.0, index=pool.index)}
    rows = []
    for name, scores in policies.items():
        for budget in QUEUE_BUDGETS:
            weights = selection_weights(scores, budget)
            clone = float(weights @ pool["clone"])/max(1, pool["clone"].sum())
            recurrence = float(weights @ pool["recurrence"])/max(1, pool["recurrence"].sum())
            rows.append({"policy": name, "budget_batches": budget, "clone_capture": round(clone, 4),
                         "recurrence_capture": round(recurrence, 4), "balanced_capture": round((clone+recurrence)/2, 4)})
    return rows


def evaluate_fusion(df, examples, episodes, history_model, scan_model, threshold):
    validation_month = examples.loc[examples["split"].eq("validation"), "target_month"].iloc[0]
    validation = queue_metrics(queue_pool(df, episodes, "validation", validation_month, history_model, scan_model, threshold))
    means = {p: float(np.mean([r["balanced_capture"] for r in validation if r["policy"] == f"fused_{p}"])) for p in FUSION_POLICIES}
    selected = max(FUSION_POLICIES, key=lambda p: (means[p], -FUSION_POLICIES.index(p)))
    test = []
    for month in sorted(examples.loc[examples["split"].eq("test"), "target_month"].unique()):
        pool = queue_pool(df, episodes, "test", month, history_model, scan_model, threshold)
        test.extend({"target_month": month, "candidates": len(pool), "clones": int(pool["clone"].sum()),
                     "recurring_manufacturer_candidates": int(pool["recurrence"].sum()), **row} for row in queue_metrics(pool))
    return {"unit": "unique batch candidate in the live queue", "clone_label": "simulated",
            "recurrence_label": "real: manufacturer text reported in the target month", "validation_month": validation_month,
            "validation": validation, "validation_mean_balanced_capture": means, "selected_policy": selected, "test": test}


def train_backend(df, examples, episodes, features, backend="sklearn", seed=SEED, output=MODELS):
    """Fit both layers, select on validation, evaluate the test split once, and save models with a card."""
    start = time.perf_counter()
    history_model, history_selection = layer_a.train(examples, backend, seed)
    scan_model, scan_selection = detector.train(features, backend, seed)
    fit_seconds = time.perf_counter()-start
    history = {**history_selection, **layer_a.evaluate(history_model, examples, df, seed)}
    scan = {**scan_selection, **detector.evaluate(scan_model, features, scan_selection["threshold"])}
    fusion = evaluate_fusion(df, examples, episodes, history_model, scan_model, scan_selection["threshold"])
    directory = Path(output) / backend
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "history_model.pkl").write_bytes(pickle.dumps(history_model))
    (directory / "scan_model.pkl").write_bytes(pickle.dumps(scan_model))
    history.pop("test_predictions").to_csv(directory / "history_test_predictions.csv", index=False, float_format="%.9f")
    scan.pop("test_predictions").to_csv(directory / "scan_test_predictions.csv", index=False, float_format="%.9f")
    card = {"model_version": f"layer-ab-{backend}-{digest([examples['example_id'].tolist(), features['example_id'].tolist(), seed, backend, FEATURE_CODE_SHA256])[:12]}",
            "created_at": datetime.now(timezone.utc).isoformat(), "backend": backend, "seed": seed,
            "feature_code_sha256": FEATURE_CODE_SHA256, "fit_and_selection_seconds": fit_seconds,
            "history": {**history, "features": HISTORY_FEATURES}, "scan": {**scan, "features": SCAN_FEATURES},
            "fusion": fusion, "environment": environment(), "test_evaluated_once_per_run": True}
    card["artifacts"] = {n: file_hash(directory / n) for n in ("history_model.pkl", "scan_model.pkl",
                                                                "history_test_predictions.csv", "scan_test_predictions.csv")}
    write_json(directory / "model_card.json", card)
    return card


def summarize(card):
    h, s, f = card["history"], card["scan"], card["fusion"]
    fused = f"fused_{f['selected_policy']}"
    test_rows = lambda policy, n: [r for r in f["test"] if r["policy"] == policy and r["budget_batches"] == n]
    mean = lambda rows, key: round(float(np.mean([r[key] for r in rows])), 4)
    capture = defaultdict(dict)
    for row in h["capture_at_budget"]:
        for name in h["test"]:
            capture[row["budget_manufacturers"]][name] = round(capture[row["budget_manufacturers"]].get(name, 0) + row[f"{name}_records"], 2)
    return {
        "model_version": card["model_version"], "backend": card["backend"],
        "layer_a": {"selected": h["selected"], "test_months": h["test_months"], "test_examples": h["test_examples"],
                    "test_positives": h["test_positives"],
                    "average_precision": {k: round(v["average_precision"], 4) for k, v in h["test"].items()},
                    "ap_gain_vs_strongest_baseline": h["bootstrap_ap_difference_vs_strongest_baseline"],
                    "strongest_baseline": h["strongest_validation_baseline"],
                    "reports_captured_by_budget": dict(capture),
                    "reachable_reports": sum(r["reachable_records"] for r in h["capture_at_budget"] if r["budget_manufacturers"] == 10),
                    "all_reports": sum(r["all_nsq_records_in_month"] for r in h["capture_at_budget"] if r["budget_manufacturers"] == 10)},
        "layer_b": {"selected": s["selected"], "threshold": s["threshold"], "model": s["model"], "rule": s["rule_baseline"],
                    "held_out_families": [x for x in s["families"] if x["held_out_family"]]},
        "fusion": {"selected_on_validation": f["selected_policy"],
                   "test_by_budget": {n: {p: {"clone": mean(test_rows(p, n), "clone_capture"),
                                              "recurrence": mean(test_rows(p, n), "recurrence_capture")}
                                          for p in ("history_only", "scan_rule_only", "scan_model_only", fused, "random_expectation")}
                                      for n in QUEUE_BUDGETS}},
    }


def inspector_queue(df, models, capacity=10):
    feed = simulator.demo_feed(df)
    ranked = rank_candidates(df, feed, models=models)
    rows = [{"rank": c["rank"], "selected": c["rank"] <= capacity, "batch_no": c["batch_no"], "product": c["product"],
             "manufacturer": c["manufacturer"], "state": c["state"], "historical_risk": c["historical_risk"],
             "scan_anomaly": c["scan_anomaly"], "scan_model_probability": None if c["scan_probability"] is None else round(c["scan_probability"], 4),
             "evidence_quality": c["evidence_quality"], "priority": c["priority_score"],
             "reasons": "; ".join(c["reason_codes"]), "review_status": "unreviewed", "simulated_scans": c["scan_simulated"]}
            for c in ranked]
    return pd.DataFrame(rows)


def charts(results, directory):
    if importlib.util.find_spec("matplotlib") is None:
        return []
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    summary = results["backends"][results["primary_backend"]]
    names = {"trained_model": "Trained model", "legacy_60_25_15_index": "Legacy index", "most_past_records": "Most past records",
             "most_recent_3_months": "Most recent 3 months", "random_expectation": "Random"}
    capture = summary["layer_a"]["reports_captured_by_budget"]
    budgets = sorted(capture, key=int)
    fig, ax = plt.subplots(figsize=(7, 4))
    width = 0.16
    for i, key in enumerate(names):
        ax.bar([b + (i-2)*width for b in range(len(budgets))], [capture[k][key] for k in budgets], width, label=names[key])
    ax.set_xticks(range(len(budgets)), [f"top {b}" for b in budgets])
    ax.set_ylabel("Later NSQ reports captured (Jul+Aug 2026)")
    ax.set_title("Layer A (real CDSCO data): reports captured at equal budget")
    ax.legend(fontsize=8)
    fig.tight_layout()
    paths = [directory / "layer_a_capture.png"]
    fig.savefig(paths[-1], dpi=150)
    plt.close(fig)
    fusion = summary["fusion"]["test_by_budget"]
    fig, ax = plt.subplots(figsize=(7, 4))
    for policy, marker in zip(next(iter(fusion.values())), "osd^x"):
        ax.plot([fusion[n][policy]["clone"] for n in fusion], [fusion[n][policy]["recurrence"] for n in fusion],
                marker=marker, label=policy)
    ax.set_xlabel("Simulated clone candidates captured")
    ax.set_ylabel("Real recurring-manufacturer candidates captured")
    ax.set_title("Same budget, two risks (N = 10…150)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    paths.append(directory / "fusion_tradeoff.png")
    fig.savefig(paths[-1], dpi=150)
    plt.close(fig)
    return [p.name for p in paths]


def run_all(backends=None, output=OUTPUTS, seed=SEED, capacity=10):
    """Everything for the final run: data -> both layers -> fusion -> inspector queue -> results.json and charts."""
    backends = backends or ["sklearn"] + (["snapml"] if importlib.util.find_spec("snapml") else [])
    output = Path(output)
    df = layer_a.load_dataset()
    examples = layer_a.history_examples(df)
    episodes = simulator.scan_corpus(df, seed=seed)
    features = detector.featurize(episodes)
    cards = {b: train_backend(df, examples, episodes, features, b, seed, output / "models") for b in backends}
    primary = backends[0]
    models = TrainedModels(output / "models" / primary)
    queue = inspector_queue(df, models, capacity)
    queue.to_csv(output / "inspector_queue.csv", index=False)
    manifest = json.loads((layer_a.DATA_PROCESSED / "manifest.json").read_text())
    results = {"banner": BANNER, "created_at": datetime.now(timezone.utc).isoformat(), "environment": environment(),
               "data": {**manifest["summary"], "processed_manifest_sha256": file_hash(layer_a.DATA_PROCESSED / "manifest.json")},
               "recurrence_finding": layer_a.recurrence_finding(df), "primary_backend": primary,
               "backends": {b: summarize(c) for b, c in cards.items()},
               "inspector_queue": {"capacity": capacity, "candidates": len(queue), "scan_alerts": int((queue["scan_anomaly"] > 0).sum()),
                                   "top": queue.head(capacity)[["rank", "batch_no", "product", "priority", "reasons"]].to_dict("records")},
               "limits": ["Layer A label is next-month report recurrence of earlier manufacturer text, not medicine safety.",
                          "Layer B labels, packs, sources and locations are simulated.",
                          "Manufacturer text is not verified legal identity; source independence is asserted, not verified."]}
    results["charts"] = charts(results, output / "charts")
    write_json(output / "results.json", results)
    return results


def live_window(episodes, count=50, end=datetime(2026, 9, 15, 12, tzinfo=timezone.utc)):
    """Test episodes round-robin across scenario families, re-timed to end together."""
    families = defaultdict(list)
    for episode in episodes:
        if episode["split"] == "test":
            families[episode["scenario"]].append(episode)
    chosen = [family[i] for i in range(count) for family in families.values() if i < len(family)][:count]
    return retime(chosen, end), sorted({e["scenario"] for e in chosen})


def _percentiles(samples):
    values = np.asarray(samples, dtype=float)
    return {"count": int(values.size), "p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)), "mean": float(values.mean()), "max": float(values.max())}


def _timed(function, *args):
    start = time.perf_counter()
    value = function(*args)
    return value, (time.perf_counter()-start)*1000


def _benchmark_pass(df, models, workload, window):
    stages = defaultdict(list)
    flat = [p for payloads in workload for p in payloads]
    stages["event_validation_total_ms"].append(_timed(lambda: [ScanEvent.parse(p) for p in flat])[1])
    values = []
    for payloads in workload:
        result, ms = _timed(extract_scan_features, payloads)
        values.append(result)
        stages["feature_extraction_ms"].append(ms)
    for row in values:
        stages["scan_inference_single_ms"].append(_timed(probability, models.scan, [row], SCAN_FEATURES)[1])
    stages["scan_inference_batch_total_ms"].append(_timed(probability, models.scan, values, SCAN_FEATURES)[1])
    context, ms = _timed(decision_context, df, max(p["event_time"] for p in window)[:7], models)
    stages["decision_context_build_ms"].append(ms)
    by_candidate = defaultdict(list)
    for payload in sorted(window, key=lambda p: (p["event_time"], p["event_id"])):
        start = time.perf_counter()
        event = ScanEvent.parse(payload)
        by_candidate[event.candidate].append(payload)
        row = extract_scan_features(by_candidate[event.candidate], event.timestamp)
        probability(models.scan, [row], SCAN_FEATURES)
        key = event.manufacturer_key.strip().casefold()
        history = float(context["history"]["percentile"].get(key, 0.0)) if key else 0.0
        rule = rule_scan_score(row)[0]
        fuse(models.policy, history, rule, corroboration(row), rule > 0)
        stages["per_scan_decision_ms"].append((time.perf_counter()-start)*1000)
    stages["queue_rebuild_with_cached_context_ms"].append(_timed(rank_candidates, df, window, None, models, context)[1])
    return stages, len(flat)


def benchmark(backends=None, repeats=5, output=OUTPUTS):
    """Same workload on any host: stage timings in one process, data preloaded; no network, UI or disk."""
    output = Path(output)
    backends = backends or [b for b in ("sklearn", "snapml")
                            if (output / "models" / b / "model_card.json").is_file() and importlib.util.find_spec(b)]
    if not backends:
        raise FileNotFoundError("No trained models; run run_all() first.")
    df = layer_a.load_dataset()
    episodes = simulator.scan_corpus(df)
    window, scenarios = live_window(episodes)
    workload = [e["events"] for e in episodes]
    result = {"host": host_label(), "created_at": datetime.now(timezone.utc).isoformat(), "environment": environment(),
              "workload_sha256": digest(workload), "window_sha256": digest(window),
              "workload": {"episodes": len(workload), "events": sum(map(len, workload)), "window_events": len(window),
                           "window_scenarios": scenarios, "repeats": repeats, "warmup": "one reduced pass excluded"},
              "scope": "Single process, sequential, in memory, data preloaded. Excludes network, UI and persistence. No accelerator use is claimed.",
              "backends": {}}
    for backend in backends:
        models = TrainedModels(output / "models" / backend)
        _benchmark_pass(df, models, workload[:20], window[:50])
        pooled, runs = defaultdict(list), []
        for _ in range(repeats):
            start = time.perf_counter()
            stages, events = _benchmark_pass(df, models, workload, window)
            seconds = time.perf_counter()-start
            runs.append({"seconds": seconds, "events": events, "events_per_second_end_to_end": events/seconds})
            for name, samples in stages.items():
                pooled[name].extend(samples)
        result["backends"][backend] = {"model_version": models.version, "runs": runs,
                                       "events_per_second_median": float(np.median([r["events_per_second_end_to_end"] for r in runs])),
                                       "stages_ms": {n: _percentiles(s) for n, s in pooled.items()}}
    write_json(output / f"benchmark_{host_label()}.json", result)
    return result


if __name__ == "__main__":
    import sys
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "benchmark"}:
        raise SystemExit("usage: python -m src.fusion [run|benchmark]")
    output = run_all() if command == "run" else benchmark()
    print(json.dumps(output.get("inspector_queue") or {b: round(v["events_per_second_median"]) for b, v in output["backends"].items()}, indent=2))
