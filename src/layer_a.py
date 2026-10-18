"""M1 — Layer A, real CDSCO history: features, baselines, training and held-out evaluation.

Target: does a manufacturer-text signature already seen in NSQ reports appear again next month?
A zero label means no next-month report, not a safe medicine. Manufacturer text is not legal identity.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import (DATA_PROCESSED, NSQ, SEED, SPLITS, digest, file_hash, fit_and_select, probability,
                        selection_weights)

HISTORY_FEATURES = ["prior_records", "prior_months", "prior_products", "records_last_month",
                    "records_last_3_months", "months_since_last_report", "unresolved_failure_records"]
BUDGETS = (10, 25, 50, 100)
BOOTSTRAP_ROUNDS = 1000


def load_dataset(directory=DATA_PROCESSED):
    """Analytical records with manufacturer and failure fields, after checking every file against the manifest."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, expected in manifest["outputs"].items():
        if file_hash(directory / name) != expected:
            raise ValueError(f"Processed file missing or changed: {name}. Rebuild with python -m src.ingest.")
    df = pd.read_csv(directory / "all_months_analytical.csv", dtype=str, keep_default_na=False)
    for name, columns in [("all_months_manufacturer_normalized.csv", ["build_record_id", "manufacturer_name_normalized",
                                                                      "manufacturer_text_for_review"]),
                          ("all_months_failure_normalized.csv", ["build_record_id", "failure_categories",
                                                                 "failure_mapping_status"])]:
        derived = pd.read_csv(directory / name, dtype=str, keep_default_na=False)
        if derived["build_record_id"].duplicated().any() or set(df["build_record_id"]) != set(derived["build_record_id"]):
            raise ValueError(f"{name} record IDs do not match the analytical dataset.")
        df = df.merge(derived[columns], on="build_record_id", how="left", validate="one_to_one")
    if df.empty or df["build_record_id"].duplicated().any():
        raise ValueError("Analytical dataset is empty or has duplicate record IDs.")
    return df


def load_provenance(directory=DATA_PROCESSED):
    return pd.read_csv(Path(directory) / "all_months_provenance.csv", dtype=str, keep_default_na=False)


def nsq_records(df):
    return df[df["source_category"].isin(NSQ)]


def _minmax(series):
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    if values.max() == values.min():
        return pd.Series(0.0, index=series.index)
    return (values - values.min()) / (values.max() - values.min())


def historical_priorities(df):
    """Legacy descriptive index (60 records + 25 months + 15 products, min-max scaled); a baseline, not a probability."""
    nsq = nsq_records(df).copy()
    nsq["manufacturer_key"] = nsq.get("manufacturer_name_normalized", pd.Series("", index=nsq.index)).astype(str).str.strip()
    nsq = nsq[nsq["manufacturer_key"].ne("")].copy()
    if nsq.empty:
        return pd.DataFrame(columns=["priority_rank", "priority_index", "manufacturer_key", "nsq_records",
                                     "months_observed", "distinct_products", "central_records", "state_records",
                                     "unresolved_records", "reason_codes", "products", "months"])
    nsq["failure_mapping_status"] = nsq.get("failure_mapping_status", pd.Series("", index=nsq.index)).astype(str)
    summary = nsq.groupby("manufacturer_key", dropna=False).agg(
        nsq_records=("build_record_id", "size"),
        months_observed=("collection_month", "nunique"),
        distinct_products=("product", lambda s: s.astype(str).str.strip().replace("", pd.NA).nunique()),
        central_records=("source_category", lambda s: int((s == "central_nsq").sum())),
        state_records=("source_category", lambda s: int((s == "state_nsq").sum())),
        unresolved_records=("failure_mapping_status", lambda s: int(s.isin(["manual_review_required", "missing"]).sum())),
        products=("product", lambda s: " | ".join(sorted(set(v.strip() for v in s if v.strip()))[:12])),
        months=("collection_month", lambda s: " | ".join(sorted(set(v for v in s if v)))),
    ).reset_index()
    summary["priority_index"] = (60*_minmax(summary["nsq_records"]) + 25*_minmax(summary["months_observed"])
                                 + 15*_minmax(summary["distinct_products"])).round(1)
    summary["reason_codes"] = summary.apply(lambda r: "; ".join(
        ([f"REPEAT_NSQ_RECORDS={int(r['nsq_records'])}"] if r["nsq_records"] >= 2 else ["SINGLE_OBSERVED_NSQ_RECORD"])
        + ([f"OBSERVED_ACROSS_MONTHS={int(r['months_observed'])}"] if r["months_observed"] >= 2 else [])
        + ([f"DISTINCT_PRODUCTS={int(r['distinct_products'])}"] if r["distinct_products"] >= 2 else [])
        + ([f"UNRESOLVED_FAILURES={int(r['unresolved_records'])}"] if r["unresolved_records"] else [])), axis=1)
    summary = summary.sort_values(["priority_index", "nsq_records", "months_observed", "distinct_products"],
                                  ascending=False).reset_index(drop=True)
    summary.insert(0, "priority_rank", range(1, len(summary) + 1))
    return summary


def monthly_summary(df):
    nsq = nsq_records(df)
    if nsq.empty:
        return pd.DataFrame(columns=["collection_month", "central_nsq", "state_nsq", "total_nsq"])
    out = nsq.pivot_table(index="collection_month", columns="source_category", values="build_record_id",
                          aggfunc="count", fill_value=0).reset_index()
    for column in NSQ:
        if column not in out:
            out[column] = 0
    out["total_nsq"] = out["central_nsq"] + out["state_nsq"]
    return out.sort_values("collection_month")


def history_features(df, cutoff):
    """Features per previously observed manufacturer text, from NSQ records through cutoff only.

    Training and live scoring both call this function.
    """
    past = nsq_records(df)
    past = past[past["collection_month"].le(cutoff)]
    priorities = historical_priorities(past).set_index("manufacturer_key")["priority_index"].to_dict()
    recent_start = str(pd.Period(cutoff, freq="M")-2)
    rows = []
    for manufacturer, group in past.groupby("manufacturer_name_normalized", sort=True):
        if not str(manufacturer).strip():
            continue
        last = group["collection_month"].max()
        rows.append({
            "manufacturer_key": manufacturer, "feature_cutoff_month": cutoff,
            "prior_records": len(group), "prior_months": group["collection_month"].nunique(),
            "prior_products": group["product"].str.strip().replace("", pd.NA).nunique(),
            "records_last_month": int(group["collection_month"].eq(cutoff).sum()),
            "records_last_3_months": int(group["collection_month"].ge(recent_start).sum()),
            "months_since_last_report": pd.Period(cutoff, freq="M").ordinal-pd.Period(last, freq="M").ordinal,
            "unresolved_failure_records": int(group["failure_mapping_status"].isin(["missing", "manual_review_required"]).sum()),
            "baseline_priority_index": float(priorities.get(manufacturer, 0)),
        })
    return pd.DataFrame(rows, columns=["manufacturer_key", "feature_cutoff_month", *HISTORY_FEATURES,
                                       "baseline_priority_index"])


def history_examples(df):
    """One example per earlier manufacturer x target month. Test = last two months, validation = the month before."""
    nsq = nsq_records(df).copy()
    months = sorted(nsq["collection_month"].unique())
    if len(months) < 6:
        raise ValueError("Need at least six collection months for chronological splits.")
    targets = months[2:]
    split_for = {m: "test" if m in targets[-2:] else "validation" if m == targets[-3] else "train" for m in targets}
    frames = []
    for target in targets:
        cutoff = str(pd.Period(target, freq="M")-1)
        future = nsq[nsq["collection_month"].eq(target)]["manufacturer_name_normalized"].value_counts()
        part = history_features(nsq, cutoff)
        part.insert(0, "example_id", [digest([m, target])[:24] for m in part["manufacturer_key"]])
        part.insert(2, "split", split_for[target])
        part.insert(4, "target_month", target)
        part["target_report_count"] = part["manufacturer_key"].map(future).fillna(0).astype(int)
        part["label"] = part["target_report_count"].gt(0).astype(int)
        frames.append(part)
    examples = pd.concat(frames, ignore_index=True)
    if not examples["feature_cutoff_month"].lt(examples["target_month"]).all():
        raise ValueError("Historical feature leakage across target month.")
    ranges = {s: examples.loc[examples["split"].eq(s), "target_month"] for s in SPLITS}
    if not (ranges["train"].max() < ranges["validation"].min() and ranges["validation"].max() < ranges["test"].min()):
        raise ValueError("Historical time splits overlap.")
    for split in SPLITS:
        if set(examples.loc[examples["split"].eq(split), "label"]) != {0, 1}:
            raise ValueError(f"Both labels are required in {split}.")
    return examples


def split(examples, name):
    part = examples[examples["split"].eq(name)].reset_index(drop=True)
    return part[HISTORY_FEATURES], part["label"], part


def history_scores(model, df, cutoff):
    """Model probability and percentile among every earlier manufacturer signature, indexed by casefolded text."""
    features = history_features(df, cutoff)
    features["probability"] = probability(model, features, HISTORY_FEATURES)
    features["percentile"] = features["probability"].rank(pct=True)*100 if len(features) else []
    return features.set_index(features["manufacturer_key"].str.strip().str.casefold())


def recurrence_finding(df, cutoff="2026-01"):
    """Share of later NSQ records whose exact manufacturer text appeared at or before cutoff."""
    nsq = nsq_records(df)
    prior, later = nsq[nsq["collection_month"].le(cutoff)], nsq[nsq["collection_month"].gt(cutoff)]
    known = set(prior.loc[prior["manufacturer_name_normalized"].ne(""), "manufacturer_name_normalized"])
    observed = int(later["manufacturer_name_normalized"].isin(known).sum())
    return {"history_through": cutoff, "later_records": len(later), "previously_seen_text_records": observed,
            "previously_seen_pct": 100*observed/len(later) if len(later) else None}


def rankers(model, x, metadata):
    return {"trained_model": probability(model, x),
            "legacy_60_25_15_index": metadata["baseline_priority_index"].to_numpy(float),
            "most_past_records": x["prior_records"].to_numpy(float),
            "most_recent_3_months": x["records_last_3_months"].to_numpy(float),
            "random_expectation": np.zeros(len(x))}


def bootstrap_ap_difference(y, a, b, seed=SEED):
    from sklearn.metrics import average_precision_score
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


def train(examples, backend="sklearn", seed=SEED):
    x, y, _ = split(examples, "train")
    xv, yv, _ = split(examples, "validation")
    return fit_and_select(x, y, xv, yv, backend, seed)


def evaluate(model, examples, df, seed=SEED):
    """Validation names the strongest baseline; the test months are then read once."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    xv, yv, mv = split(examples, "validation")
    validation = {n: float(average_precision_score(yv, s)) for n, s in rankers(model, xv, mv).items()
                  if n != "random_expectation"}
    strongest = max((n for n in validation if n != "trained_model"), key=validation.get)
    x, y, metadata = split(examples, "test")
    scores = rankers(model, x, metadata)
    nsq = nsq_records(df)
    capture = []
    for month in sorted(metadata["target_month"].unique()):
        mask = metadata["target_month"].eq(month).to_numpy()
        counts, labels = metadata.loc[mask, "target_report_count"].to_numpy(float), y[mask].to_numpy(float)
        for budget in BUDGETS:
            row = {"target_month": month, "budget_manufacturers": budget, "candidate_manufacturers": int(mask.sum()),
                   "reachable_records": int(counts.sum()),
                   "all_nsq_records_in_month": int(nsq["collection_month"].eq(month).sum()),
                   "recurring_manufacturers": int(labels.sum())}
            for name, values in scores.items():
                weights = selection_weights(values[mask], budget)
                row[f"{name}_records"] = round(float(weights @ counts), 2)
                row[f"{name}_manufacturers"] = round(float(weights @ labels), 2)
            capture.append(row)
    test = {n: {"average_precision": float(average_precision_score(y, s)),
                "roc_auc": float(roc_auc_score(y, s)) if len(set(s)) > 1 else 0.5} for n, s in scores.items()}
    return {"unit": "manufacturer-text signature x target month", "label": "reported again in the target month",
            "test_months": sorted(metadata["target_month"].unique()), "test_examples": len(y),
            "test_positives": int(y.sum()), "validation_average_precision_vs_baselines": validation,
            "strongest_validation_baseline": strongest, "test": test, "capture_at_budget": capture,
            "bootstrap_ap_difference_vs_strongest_baseline": bootstrap_ap_difference(
                y, scores["trained_model"], scores[strongest], seed),
            "test_predictions": pd.DataFrame({"example_id": metadata["example_id"],
                                              "probability": scores["trained_model"]})}


def followup_queue(df, month, capacity=10, category="nsq"):
    """Published findings in one month, one row per product/batch/manufacturer text, ordered by earlier history only."""
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    if month not in set(df["collection_month"]):
        raise ValueError("Choose a month in the dataset.")
    if category not in {"nsq", "spurious"}:
        raise ValueError("category must be nsq or spurious.")
    allowed = list(NSQ) if category == "nsq" else ["spurious"]
    lookup = historical_priorities(df[df["collection_month"].lt(month)]).set_index("manufacturer_key").to_dict("index")
    current = df[df["collection_month"].eq(month) & df["source_category"].isin(allowed)].copy()
    current = current[current["product"].str.strip().ne("") & current["batch_no"].str.strip().ne("")]
    keys = ["product", "batch_no", "manufacturer_name_normalized"]
    for i, name in enumerate(keys):
        current[f"_key_{i}"] = current[name].str.strip().str.casefold()
    rows = []
    for _, group in current.groupby(["_key_0", "_key_1", "_key_2"], sort=False):
        row = group.iloc[0]
        manufacturer = row["manufacturer_name_normalized"].strip()
        previous = lookup.get(manufacturer, {})
        rows.append({
            "candidate_id": hashlib.sha256(json.dumps([str(row[n]).strip().casefold() for n in keys]).encode()).hexdigest()[:24],
            "product": row["product"], "batch_no": row["batch_no"], "manufacturer_key": manufacturer,
            "historical_priority_index": float(previous.get("priority_index", 0)),
            "prior_nsq_records": int(previous.get("nsq_records", 0)),
            "prior_months_observed": int(previous.get("months_observed", 0)),
            "history_status": "earlier_reported_findings" if previous else "no_earlier_matching_manufacturer_text",
            "source_categories": " | ".join(sorted(group["source_category"].unique())),
            "failure_categories": "; ".join(sorted(set(v for v in group["failure_categories"] if v))),
            "record_ids": " | ".join(sorted(group["build_record_id"].unique())),
            "source_files": " | ".join(sorted(group["source_file"].unique())),
            "reason": previous.get("reason_codes", "No earlier matching history; review published evidence directly."),
            "collection_month": month})
    columns = ["rank", "candidate_id", "product", "batch_no", "manufacturer_key", "historical_priority_index",
               "prior_nsq_records", "prior_months_observed", "history_status", "source_categories",
               "failure_categories", "record_ids", "source_files", "reason", "collection_month"]
    if not rows:
        return pd.DataFrame(columns=columns)
    output = pd.DataFrame(rows).sort_values(["historical_priority_index", "prior_nsq_records", "candidate_id"],
                                            ascending=[False, False, True]).head(capacity).reset_index(drop=True)
    output.insert(0, "rank", range(1, len(output)+1))
    return output[columns]


def chronological_coverage(df, capacity=10):
    """Month by month: how many later NSQ records come from the top-K earlier manufacturers (index, count, random)."""
    nsq = nsq_records(df)
    rows = []
    for month in sorted(nsq["collection_month"].unique())[1:]:
        prior, later = nsq[nsq["collection_month"].lt(month)], nsq[nsq["collection_month"].eq(month)]
        priorities = historical_priorities(prior)
        universe = set(priorities["manufacturer_key"])
        by_count = priorities.sort_values(["nsq_records", "manufacturer_key"], ascending=[False, True])
        seen = int(later["manufacturer_name_normalized"].isin(universe).sum())
        k = min(capacity, len(universe))
        rows.append({"test_month": month, "training_through": prior["collection_month"].max(),
                     "prior_manufacturer_signatures": len(universe), "selected_signatures": k,
                     "later_nsq_records": len(later), "seen_manufacturer_records": seen,
                     "new_or_unavailable_manufacturer_records": len(later)-seen,
                     "history_coverage_pct": round(100*seen/len(later), 2),
                     "index_captured_records": int(later["manufacturer_name_normalized"].isin(set(priorities.head(capacity)["manufacturer_key"])).sum()),
                     "past_count_captured_records": int(later["manufacturer_name_normalized"].isin(set(by_count.head(capacity)["manufacturer_key"])).sum()),
                     "random_expected_captured_records": round(seen*k/len(universe), 4) if universe else 0})
    return pd.DataFrame(rows)
