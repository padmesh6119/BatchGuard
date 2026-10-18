"""Select a history reservation on June validation; report retrospective comparisons.

The new policy was developed after legacy test results were known. July/August
comparisons are retrospective, not a fresh independent test of this design.
"""
import argparse
import json
import inspect
from pathlib import Path

import numpy as np

from src import layer_a, simulator
from src.common import OUTPUTS, digest, file_hash, selection_weights, write_json
from src.fusion import load_models, queue_pool
from src.planning import protected_order

BUDGETS = (10, 25, 50, 100)
SHARES = (0.5, 0.75, 1.0)


def measure(pool, share=None):
    if share is not None:
        identifiers = pool["candidate_id"].tolist()
        order = protected_order(pool["history"].tolist(), pool["rule"].tolist(),
                                pool["quality"].tolist(), identifiers, share)
    result = {}
    for budget in BUDGETS:
        if share is None:
            values = .5 * pool["history"] + .35 * pool["rule"] + .15 * pool["quality"] * pool["rule"].gt(0)
            weights = selection_weights(values, budget)
        else:
            weights = np.zeros(len(pool))
            for index, _ in order[:budget]:
                weights[index] = 1
        result[str(budget)] = {
            "candidates_selected": float(sum(weights)),
            "recurrence_capture": float(weights @ pool["recurrence"] / max(1, pool["recurrence"].sum())),
            "clone_capture": float(weights @ pool["clone"] / max(1, pool["clone"].sum())),
        }
    return result


def build(output=OUTPUTS / "capacity_audit.json", backends=("sklearn",)):
    df = layer_a.load_dataset()
    examples = layer_a.history_examples(df)
    episodes = simulator.scan_corpus(df)
    validation_month = examples.loc[examples["split"].eq("validation"), "target_month"].iloc[0]
    test_months = sorted(examples.loc[examples["split"].eq("test"), "target_month"].unique())
    reports = {}
    for backend in backends:
        models = load_models(backend)
        if models is None:
            continue
        validation_pool = queue_pool(df, episodes, "validation", validation_month,
                                     models.history, models.scan, models.threshold)
        choices = {str(share): measure(validation_pool, share) for share in SHARES}
        # Predeclared objective: maximize the weaker capture at budgets 10 and 25.
        objectives = {share: float(np.mean([min(values[str(b)]["clone_capture"],
                                                   values[str(b)]["recurrence_capture"])
                                            for b in (10, 25)])) for share, values in choices.items()}
        selected = max(objectives, key=lambda share: (objectives[share], -float(share)))
        comparisons = []
        for month in test_months:
            pool = queue_pool(df, episodes, "test", month, models.history, models.scan, models.threshold)
            comparisons.append({"month": month, "candidates": len(pool),
                                "recurring_candidates": int(pool["recurrence"].sum()),
                                "simulated_clone_candidates": int(pool["clone"].sum()),
                                "legacy_weighted": measure(pool),
                                "protected_history": measure(pool, float(selected))})
        reports[backend] = {"model_version": models.version, "selected_history_share": float(selected),
                            "validation_candidates": choices, "validation_objectives": objectives,
                            "retrospective_months": comparisons}
    report = {"validation_month": validation_month, "selection_budgets": [10, 25],
              "planner_sha256": digest(inspect.getsource(protected_order)),
              "selection_objective": "mean minimum of historical-recurrence and simulated-clone capture",
              "evaluation_status": "retrospective: policy designed after legacy test results were known",
              "source_manifest_sha256": file_hash(layer_a.DATA_PROCESSED / "manifest.json"),
              "limits": ["Reservation is a policy preference, not an estimate of field inspection benefit.",
                         "Clone outcomes are synthetic; recurrence outcomes are published manufacturer-text reports.",
                         "History reservations need candidates with nonzero history; otherwise slots fall back to alerts or unknown coverage."],
              "backends": reports}
    write_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUTS / "capacity_audit.json")
    parser.add_argument("--backends", nargs="+", choices=("sklearn", "snapml"), default=["sklearn"])
    args = parser.parse_args()
    report = build(args.output, args.backends)
    print(json.dumps({b: r["selected_history_share"] for b, r in report["backends"].items()}))
