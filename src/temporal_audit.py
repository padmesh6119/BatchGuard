"""Retrospective expanding-window diagnostics for the existing history features.

Hyperparameters were already selected in the project; this is a stability audit,
not a new untouched test or a prospective inspection-yield estimate.
"""
import json

from sklearn.metrics import average_precision_score

from src import layer_a
from src.common import OUTPUTS, model_grid, probability, selection_weights, write_json


def build(output=OUTPUTS / "temporal_audit.json"):
    df = layer_a.load_dataset()
    examples = layer_a.history_examples(df)
    months = sorted(examples["target_month"].unique())
    folds = []
    for month in months[3:]:
        training = examples[examples["target_month"].lt(month)]
        current = examples[examples["target_month"].eq(month)].reset_index(drop=True)
        if training["label"].nunique() < 2 or current["label"].nunique() < 2:
            continue
        model = model_grid("sklearn")["logistic_c0.1"]
        model.fit(training[layer_a.HISTORY_FEATURES].to_numpy(float), training["label"].to_numpy(float))
        x = current[layer_a.HISTORY_FEATURES]
        scores = layer_a.rankers(model, x, current)
        counts = current["target_report_count"].to_numpy(float)
        all_records = int((layer_a.nsq_records(df)["collection_month"] == month).sum())
        folds.append({"target_month": month, "training_through": training["target_month"].max(),
                      "candidates": len(current), "positive_manufacturer_texts": int(current["label"].sum()),
                      "all_nsq_records": all_records, "reachable_report_records": int(counts.sum()),
                      "new_or_unavailable_manufacturer_records": all_records - int(counts.sum()),
                      "average_precision": {name: float(average_precision_score(current["label"], values))
                                            for name, values in scores.items()},
                      "captured_report_records": {str(b): {name: float(selection_weights(values, b) @ counts)
                                                           for name, values in scores.items()} for b in (10, 25)}})
    report = {"status": "retrospective stability audit; previously selected hyperparameters",
              "model": "fixed logistic_c0.1; refit only on earlier target months for each fold",
              "folds": folds,
              "model_beats_legacy_index_months": sum(f["average_precision"]["trained_model"] >
                                                      f["average_precision"]["legacy_60_25_15_index"] for f in folds),
              "fold_count": len(folds),
              "missing_release_dates": int(df["release_date"].str.strip().eq("").sum()),
              "records": len(df),
              "limits": ["Collection month substitutes for unavailable publication date; event-time availability is unverified.",
                         "Reported failures have no representative tested/sold-medicine denominator.",
                         "Rows repeat manufacturer text over months; no independent-row confidence claim is made.",
                         "A zero recurrence label means no matching report, not a safe medicine.",
                         "This audit does not replace the recorded legacy two-month evaluation."]}
    write_json(output, report)
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps({"months": result["fold_count"], "months_model_beats_legacy": result["model_beats_legacy_index_months"]}))
