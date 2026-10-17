"""Fit Layer A/B models, select on validation only, then evaluate once on the reserved test split."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pickle
import platform
import shutil
import tempfile
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from batchguard_engine import load_dataset
from decision_core import FUSION_POLICIES, fuse, rank_candidates
from inspection_stream import ScanEvent, digest
from model_foundation import HISTORY_FEATURES, HISTORY_TASK, SCAN_FEATURES, SCAN_TASK, load_model_inputs
from replay import environment
from snapshot_store import ROOT, file_hash

BUDGETS = (10, 25, 50, 100)
QUEUE_BUDGETS = (10, 25, 50, 100, 150)
BOOTSTRAP_ROUNDS = 1000


def candidates(backend, seed):
    """Small, fixed grids. Selection uses validation average precision only."""
    if backend == "snapml":
        from snapml import BoostingMachineClassifier, LogisticRegression as SnapLogisticRegression
        return {
            **{f"snap_logistic_r{r}": make_pipeline(StandardScaler(), SnapLogisticRegression(
                regularizer=r, fit_intercept=True, random_state=seed)) for r in (0.1, 1.0, 10.0)},
            **{f"snap_boosting_d{d}": BoostingMachineClassifier(
                num_round=150, max_depth=d, learning_rate=0.05, random_state=seed, n_jobs=1) for d in (2, 3)},
        }
    if backend == "sklearn":
        return {
            **{f"logistic_c{c}": make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000))
               for c in (0.1, 1.0, 10.0)},
            **{f"hist_gbm_d{d}": HistGradientBoostingClassifier(
                max_depth=d, learning_rate=0.05, max_iter=150, min_samples_leaf=20, random_state=seed) for d in (2, 3)},
        }
    raise ValueError("backend must be sklearn or snapml.")


def probability(model, x):
    return model.predict_proba(np.asarray(x, dtype=np.float32))[:, 1]


def fit_and_select(task, bundle, backend, seed):
    x, y, _ = load_model_inputs(bundle, task, "train")
    xv, yv, _ = load_model_inputs(bundle, task, "validation")
    scores, fitted, seconds = {}, {}, {}
    for name, model in candidates(backend, seed).items():
        start = time.perf_counter()
        model.fit(np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32))
        seconds[name] = time.perf_counter()-start
        scores[name] = float(average_precision_score(yv, probability(model, xv)))
        fitted[name] = model
    # Ties keep the earlier, simpler candidate.
    selected = max(scores, key=lambda name: (scores[name], -list(scores).index(name)))
    return fitted[selected], {"selected": selected, "candidate_validation_average_precision": scores,
                              "fit_seconds": seconds}


def selection_weights(scores, budget):
    """Expected selection at a budget; tied scores share remaining slots (exact random tie-break)."""
    scores = pd.Series(np.asarray(scores, dtype=float))
    weights = pd.Series(0.0, index=scores.index)
    remaining = min(budget, len(scores))
    for value in sorted(scores.unique(), reverse=True):
        if remaining <= 0:
            break
        tied = scores.index[scores.eq(value)]
        take = min(remaining, len(tied))
        weights[tied] = take/len(tied)
        remaining -= take
    return weights.to_numpy()


def bootstrap_ap_difference(y, a, b, seed):
    rng = np.random.default_rng(seed)
    y, a, b = np.asarray(y), np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    differences = []
    for _ in range(BOOTSTRAP_ROUNDS):
        index = rng.integers(0, len(y), len(y))
        if y[index].min() == y[index].max():
            continue
        differences.append(average_precision_score(y[index], a[index])-average_precision_score(y[index], b[index]))
    low, high = np.percentile(differences, [2.5, 97.5])
    return {"mean": float(np.mean(differences)), "ci95": [float(low), float(high)], "rounds": len(differences),
            "share_above_zero": float(np.mean(np.asarray(differences) > 0))}


def history_rankers(model, x, metadata):
    return {"trained_model": probability(model, x),
            "legacy_60_25_15_index": metadata["baseline_priority_index"].to_numpy(float),
            "most_past_records": x["prior_records"].to_numpy(float),
            "most_recent_3_months": x["records_last_3_months"].to_numpy(float),
            "random_expectation": np.zeros(len(x))}


def evaluate_history(model, bundle, df, seed):
    """Real CDSCO outcome: next-month NSQ report recurrence among earlier manufacturer signatures."""
    xv, yv, mv = load_model_inputs(bundle, HISTORY_TASK, "validation")
    validation = {name: float(average_precision_score(yv, s)) for name, s in history_rankers(model, xv, mv).items()
                  if name != "random_expectation"}
    strongest = max((n for n in validation if n != "trained_model"), key=validation.get)
    x, y, metadata = load_model_inputs(bundle, HISTORY_TASK, "test", final_evaluation=True)
    rankers = history_rankers(model, x, metadata)
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])]
    capture = []
    for month in sorted(metadata["target_month"].unique()):
        mask = metadata["target_month"].eq(month).to_numpy()
        counts = metadata.loc[mask, "target_report_count"].to_numpy(float)
        labels = y[mask].to_numpy(float)
        for budget in BUDGETS:
            row = {"target_month": month, "budget_manufacturers": budget,
                   "candidate_manufacturers": int(mask.sum()),
                   "reachable_records": int(counts.sum()),
                   "all_nsq_records_in_month": int(nsq["collection_month"].eq(month).sum()),
                   "recurring_manufacturers": int(labels.sum())}
            for name, scores in rankers.items():
                weights = selection_weights(scores[mask], budget)
                row[f"{name}_records"] = round(float(weights @ counts), 2)
                row[f"{name}_manufacturers"] = round(float(weights @ labels), 2)
            capture.append(row)
    test = {name: {"average_precision": float(average_precision_score(y, s)),
                   "roc_auc": float(roc_auc_score(y, s)) if len(set(s)) > 1 else 0.5}
            for name, s in rankers.items()}
    return {"unit": "manufacturer-text signature x target month", "label": "reported again in the target month",
            "test_months": sorted(metadata["target_month"].unique()), "test_examples": len(y),
            "test_positives": int(y.sum()), "validation_average_precision_vs_baselines": validation,
            "strongest_validation_baseline": strongest, "test": test, "capture_at_budget": capture,
            "bootstrap_ap_difference_vs_strongest_baseline": bootstrap_ap_difference(
                y, rankers["trained_model"], rankers[strongest], seed)}


def choose_threshold(y, scores):
    """Maximize validation F1; ties keep the higher threshold (fewer alerts)."""
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


def evaluate_scan(model, bundle, heldout):
    """Simulated outcome: clone scenario label for a batch observation episode."""
    xv, yv, _ = load_model_inputs(bundle, SCAN_TASK, "validation")
    threshold = choose_threshold(yv.to_numpy(), probability(model, xv))
    x, y, metadata = load_model_inputs(bundle, SCAN_TASK, "test", final_evaluation=True)
    scores = probability(model, x)
    predicted = scores >= threshold
    rule = metadata["baseline_rule_prediction"].to_numpy().astype(bool)
    families = []
    for scenario, part in metadata.groupby("scenario", sort=True):
        index = part.index.to_numpy()
        families.append({"scenario": scenario, "held_out_family": scenario in heldout,
                         "clone_label": int(y[index].iloc[0]), "episodes": len(index),
                         "model_alert_rate": float(predicted[index].mean()),
                         "rule_alert_rate": float(rule[index].mean())})
    return {"unit": "simulated batch observation episode", "threshold": threshold,
            "threshold_rule": "maximum validation F1", "test_episodes": len(y), "test_clones": int(y.sum()),
            "model": {**confusion(y, predicted), "average_precision": float(average_precision_score(y, scores))},
            "rule_baseline": confusion(y, rule), "families": families}


def queue_pool(df, bundle, split, month, history_model, scan_model, threshold):
    """Score a split's episodes through the live queue on the 15th of the target month.

    Episodes are re-timed to end together, so each keeps its own six-hour window; episodes sharing a
    real CDSCO reference batch merge into one candidate, exactly as the queue would merge them. Two labels
    per candidate: simulated clone (any merged episode) and whether its manufacturer text is really
    reported in that month's NSQ lists. They measure different risks.
    """
    _, y, metadata = load_model_inputs(bundle, SCAN_TASK, split, final_evaluation=split == "test")
    labels = dict(zip(metadata["episode_id"], y))
    end = datetime.fromisoformat(f"{month}-15T12:00:00+00:00")
    events, clone = [], {}
    with (Path(bundle) / "scan_episodes.jsonl").open() as stream:
        for line in stream:
            episode = json.loads(line)
            if episode["split"] != split:
                continue
            shift = timedelta(seconds=end.timestamp()-max(ScanEvent.parse(p).timestamp for p in episode["events"]))
            events.extend(dict(p, event_id=f"{episode['episode_id']}:{p['event_id']}",
                               event_time=(datetime.fromisoformat(p["event_time"])+shift).isoformat())
                          for p in episode["events"])
            cid = ScanEvent.parse(episode["events"][0]).candidate
            clone[cid] = max(clone.get(cid, 0), int(labels[episode["episode_id"]]))
    models = SimpleNamespace(history=history_model, scan=scan_model, threshold=threshold,
                             policy="weighted", version=f"evaluation-{split}")
    reported = set(df.loc[df["source_category"].isin(["central_nsq", "state_nsq"]) & df["collection_month"].eq(month),
                          "manufacturer_name_normalized"].str.strip().str.casefold()) - {""}
    return pd.DataFrame([{"clone": clone[c["candidate_id"]], "recurrence": int(c["manufacturer"].strip().casefold() in reported),
                          "history": c["historical_risk"], "rule": c["scan_anomaly"], "scan": 100*c["scan_probability"],
                          "quality": c["evidence_quality"]}
                         for c in rank_candidates(df, events, end.timestamp(), models)])


def queue_policies(pool):
    """Fused policies use the rule alert, as the live queue does."""
    return {"history_only": pool["history"],
            "scan_rule_only": pool["rule"],
            "scan_model_only": pool["scan"],
            **{f"fused_{policy}": pool.apply(lambda r: fuse(policy, r["history"], r["rule"], r["quality"], r["rule"] > 0), axis=1)
               for policy in FUSION_POLICIES},
            "random_expectation": pd.Series(0.0, index=pool.index)}


def queue_metrics(pool):
    rows = []
    for name, scores in queue_policies(pool).items():
        for budget in QUEUE_BUDGETS:
            weights = selection_weights(scores, budget)
            clone = float(weights @ pool["clone"])/max(1, pool["clone"].sum())
            recurrence = float(weights @ pool["recurrence"])/max(1, pool["recurrence"].sum())
            rows.append({"policy": name, "budget_batches": budget, "clone_capture": round(clone, 4),
                         "recurrence_capture": round(recurrence, 4), "balanced_capture": round((clone+recurrence)/2, 4)})
    return rows


def evaluate_queue(df, bundle, history_model, scan_model, threshold):
    _, _, history_validation = load_model_inputs(bundle, HISTORY_TASK, "validation")
    _, _, history_test = load_model_inputs(bundle, HISTORY_TASK, "test", final_evaluation=True)
    validation_month = history_validation["target_month"].iloc[0]
    validation = queue_metrics(queue_pool(df, bundle, "validation", validation_month, history_model, scan_model, threshold))
    means = {policy: np.mean([r["balanced_capture"] for r in validation if r["policy"] == f"fused_{policy}"])
             for policy in FUSION_POLICIES}
    selected = max(FUSION_POLICIES, key=lambda policy: (means[policy], -FUSION_POLICIES.index(policy)))
    test = []
    for month in sorted(history_test["target_month"].unique()):
        pool = queue_pool(df, bundle, "test", month, history_model, scan_model, threshold)
        test.extend({"target_month": month, "candidates": len(pool), "clones": int(pool["clone"].sum()),
                     "recurring_manufacturer_candidates": int(pool["recurrence"].sum()), **row}
                    for row in queue_metrics(pool))
    return {"unit": "unique batch candidate in the live queue (episodes on the same real reference batch merged)",
            "clone_label": "simulated clone scenario", "recurrence_label": "real: manufacturer text reported in the target month",
            "validation_month": validation_month, "validation": validation,
            "validation_mean_balanced_capture": {k: float(v) for k, v in means.items()},
            "selected_policy": selected, "test": test}


def train(bundle, output, backend="sklearn", seed=2026):
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise FileExistsError("Use a fresh model directory; test results must not be overwritten silently.")
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest["features_sha256"] != file_hash(ROOT / "scan_features.py"):
        raise ValueError("scan_features.py differs from the code that built this bundle.")
    location = ROOT / "data" / "snapshots" / manifest["snapshot_id"]
    df = load_dataset((location, manifest["snapshot_id"]))
    start = time.perf_counter()
    history_model, history_selection = fit_and_select(HISTORY_TASK, bundle, backend, seed)
    scan_model, scan_selection = fit_and_select(SCAN_TASK, bundle, backend, seed)
    selection_seconds = time.perf_counter()-start
    history = {**history_selection, **evaluate_history(history_model, bundle, df, seed)}
    scan = {**scan_selection, **evaluate_scan(scan_model, bundle, set(manifest["heldout_scan_families"]))}
    fusion = evaluate_queue(df, bundle, history_model, scan_model, scan["threshold"])
    x, _, _ = load_model_inputs(bundle, HISTORY_TASK, "test", final_evaluation=True)
    start = time.perf_counter()
    for _ in range(200):
        probability(history_model, x.iloc[:1])
    single_row_ms = (time.perf_counter()-start)*1000/200
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".models-", dir=output.parent))
    try:
        (stage / "history_model.pkl").write_bytes(pickle.dumps(history_model))
        (stage / "scan_model.pkl").write_bytes(pickle.dumps(scan_model))
        scan_x, _, _ = load_model_inputs(bundle, SCAN_TASK, "test", final_evaluation=True)
        x_ids = load_model_inputs(bundle, HISTORY_TASK, "test", final_evaluation=True)[2]
        scan_ids = load_model_inputs(bundle, SCAN_TASK, "test", final_evaluation=True)[2]
        pd.DataFrame({"example_id": x_ids["example_id"], "probability": probability(history_model, x)}).to_csv(
            stage / "history_test_predictions.csv", index=False, float_format="%.9f")
        pd.DataFrame({"example_id": scan_ids["example_id"], "probability": probability(scan_model, scan_x)}).to_csv(
            stage / "scan_test_predictions.csv", index=False, float_format="%.9f")
        card = {
            "model_version": f"layer-ab-{backend}-{digest([manifest['files'], seed, backend])[:12]}",
            "created_at": datetime.now(timezone.utc).isoformat(), "backend": backend, "seed": seed,
            "bundle": {"path": bundle.resolve().relative_to(ROOT).as_posix() if bundle.resolve().is_relative_to(ROOT) else str(bundle),
                       "manifest_sha256": file_hash(bundle / "manifest.json"), "snapshot_id": manifest["snapshot_id"]},
            "history": {**history, "features": HISTORY_FEATURES},
            "scan": {**scan, "features": SCAN_FEATURES, "features_sha256": manifest["features_sha256"]},
            "fusion": fusion,
            "timing": {"fit_and_validation_selection_seconds": selection_seconds,
                       "history_single_row_inference_ms": single_row_ms,
                       "scope": "In-process on this host; excludes data loading. Not an IBM Z result unless machine is s390x."},
            "environment": environment(), "python_platform": platform.platform(),
            "test_evaluated_once": True,
            "limitations": [
                "Layer A predicts reported recurrence of earlier manufacturer text, not medicine safety.",
                "Collection months stand in for unverified publication dates.",
                "Layer B labels and all scan behavior are simulated; seen families are nearly separable by design.",
                "Fusion capture mixes a simulated clone label with a real manufacturer recurrence label.",
                "Manufacturer text is not verified legal identity; source independence is asserted, not verified."]}
        card["artifacts"] = {name: file_hash(stage / name) for name in (
            "history_model.pkl", "scan_model.pkl", "history_test_predictions.csv", "scan_test_predictions.csv")}
        (stage / "model_card.json").write_text(json.dumps(card, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stage.rename(output)
        return card
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "data" / "training" / "foundation-ready-v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=["sklearn", "snapml"], default="sklearn")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    card = train(args.bundle, args.output, args.backend, args.seed)
    history, scan = card["history"], card["scan"]
    print(json.dumps({
        "model_version": card["model_version"], "machine": card["environment"]["machine"],
        "history_selected": history["selected"],
        "history_test_average_precision": {k: round(v["average_precision"], 4) for k, v in history["test"].items()},
        "scan_selected": scan["selected"], "scan_model_test": scan["model"], "scan_rule_test": scan["rule_baseline"],
        "fusion_selected_on_validation": card["fusion"]["selected_policy"]}, indent=2))


if __name__ == "__main__":
    main()
