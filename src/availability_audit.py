"""Sensitivity to assumed one-, two- and three-month reporting lags.

All three assumptions are reported, not selected on test performance. Actual
publication dates are unavailable, so this is retrospective sensitivity only.
"""
import json

import pandas as pd
from sklearn.metrics import average_precision_score

from src import layer_a
from src.common import OUTPUTS, file_hash, model_grid, probability, selection_weights, write_json


def build(output=OUTPUTS / "availability_audit.json"):
    df = layer_a.load_dataset()
    nsq = layer_a.nsq_records(df)
    months = sorted(nsq["collection_month"].unique())
    validation, test = months[-3], months[-2:]
    reports = []
    for lag in (1, 2, 3):
        frames = []
        for target in months[2:]:
            cutoff = str(pd.Period(target, freq="M") - lag)
            part = layer_a.history_features(df, cutoff)
            if part.empty:
                continue
            future = nsq[nsq["collection_month"].eq(target)]["manufacturer_name_normalized"].value_counts()
            part["target_month"] = target
            part["target_report_count"] = part["manufacturer_key"].map(future).fillna(0).astype(int)
            part["label"] = part["target_report_count"].gt(0).astype(int)
            frames.append(part)
        examples = pd.concat(frames, ignore_index=True)
        train = examples[examples["target_month"].lt(validation)]
        model = model_grid("sklearn")["logistic_c0.1"]
        model.fit(train[layer_a.HISTORY_FEATURES].to_numpy(float), train["label"].to_numpy(float))
        evaluations = []
        for month in [validation, *test]:
            current = examples[examples["target_month"].eq(month)].reset_index(drop=True)
            scores = probability(model, current, layer_a.HISTORY_FEATURES)
            counts = current["target_report_count"].to_numpy(float)
            evaluations.append({"month": month, "split": "validation" if month == validation else "retrospective_test",
                                "feature_cutoff": current["feature_cutoff_month"].iloc[0],
                                "average_precision": float(average_precision_score(current["label"], scores)),
                                "candidate_manufacturer_texts": len(current), "reachable_report_records": int(counts.sum()),
                                "all_report_records": int(nsq["collection_month"].eq(month).sum()),
                                "captured_report_records": {str(b): float(selection_weights(scores, b) @ counts) for b in (10, 25)},
                                "legacy_captured_report_records": {str(b): float(selection_weights(current["baseline_priority_index"], b) @ counts) for b in (10, 25)}})
        reports.append({"assumed_reporting_lag_months": lag, "training_through": train["target_month"].max(),
                        "training_examples": len(train), "months": evaluations})
    result = {"status": "retrospective sensitivity; all lag assumptions reported; publication dates unverified",
              "model": "fixed existing logistic_c0.1 configuration; no lag chosen on test results",
              "processed_manifest_sha256": file_hash(layer_a.DATA_PROCESSED / "manifest.json"),
              "scenarios": reports,
              "limits": ["A two/three-month lag is an assumption, not proof that every report was available then.",
                         "This measures report recurrence, not unsafe batches, population prevalence or field scan accuracy."]}
    write_json(output, result)
    return result


if __name__ == "__main__":
    report = build()
    print(json.dumps({row["assumed_reporting_lag_months"]: sum(m["captured_report_records"]["25"] for m in row["months"] if m["split"] == "retrospective_test") for row in report["scenarios"]}))
