"""Historical follow-up review and month-ordered report-coverage checks."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from batchguard_engine import historical_priorities, load_dataset
from snapshot_store import ROOT, active_snapshot

QUEUE_COLUMNS = ["rank", "candidate_id", "product", "batch_no", "manufacturer_key",
                 "historical_priority_index", "prior_nsq_records", "prior_months_observed",
                 "history_status", "source_categories", "failure_categories", "record_ids",
                 "source_files", "reason", "collection_month"]


def followup_queue(df, month, capacity=10, category="nsq"):
    """Review published findings; candidates are not an inventory of untested batches."""
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    if month not in set(df["collection_month"]):
        raise ValueError("Choose a month in the dataset.")
    if category not in {"nsq", "spurious"}:
        raise ValueError("category must be nsq or spurious.")
    allowed = ["central_nsq", "state_nsq"] if category == "nsq" else ["spurious"]
    history = df[df["collection_month"].lt(month)]
    priorities = historical_priorities(history)
    lookup = priorities.set_index("manufacturer_key").to_dict("index")
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
        identifiers = sorted(group["build_record_id"].unique())
        identity = json.dumps([str(row[name]).strip().casefold() for name in keys])
        evidence = "; ".join(sorted(set(v for v in group["failure_categories"] if v)))
        rows.append({
            "candidate_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
            "product": row["product"], "batch_no": row["batch_no"], "manufacturer_key": manufacturer,
            "historical_priority_index": float(previous.get("priority_index", 0)),
            "prior_nsq_records": int(previous.get("nsq_records", 0)),
            "prior_months_observed": int(previous.get("months_observed", 0)),
            "history_status": "earlier_reported_findings" if previous else "no_earlier_matching_manufacturer_text",
            "source_categories": " | ".join(sorted(group["source_category"].unique())),
            "failure_categories": evidence, "record_ids": " | ".join(identifiers),
            "source_files": " | ".join(sorted(group["source_file"].unique())),
            "reason": previous.get("reason_codes", "No earlier matching history; review published evidence directly."),
            "collection_month": month,
        })
    if not rows:
        return pd.DataFrame(columns=QUEUE_COLUMNS)
    output = pd.DataFrame(rows).sort_values(
        ["historical_priority_index", "prior_nsq_records", "candidate_id"], ascending=[False, False, True])
    output = output.head(capacity).reset_index(drop=True)
    output.insert(0, "rank", range(1, len(output)+1))
    return output[QUEUE_COLUMNS]


def chronological_coverage(df, capacity=10):
    """Measure subsequent report coverage, not defect probability or inspection yield.

    Candidate universe for each month: manufacturer text signatures in earlier NSQ reports.
    Collection months are proxies; publication/revision timestamps remain unavailable.
    """
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
        raise ValueError("capacity must be a nonnegative integer.")
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])].copy()
    rows = []
    for month in sorted(nsq["collection_month"].unique())[1:]:
        prior = nsq[nsq["collection_month"].lt(month)]
        later = nsq[nsq["collection_month"].eq(month)]
        priorities = historical_priorities(prior)
        universe = set(priorities["manufacturer_key"])
        count_ranking = priorities.sort_values(["nsq_records", "manufacturer_key"], ascending=[False, True])
        index_names = set(priorities.head(capacity)["manufacturer_key"])
        count_names = set(count_ranking.head(capacity)["manufacturer_key"])
        seen_rows = int(later["manufacturer_name_normalized"].isin(universe).sum())
        k = min(capacity, len(universe))
        rows.append({
            "test_month": month, "training_through": prior["collection_month"].max(),
            "prior_manufacturer_signatures": len(universe), "selected_signatures": k,
            "later_nsq_records": len(later), "seen_manufacturer_records": seen_rows,
            "new_or_unavailable_manufacturer_records": len(later)-seen_rows,
            "history_coverage_pct": round(100*seen_rows/len(later), 2),
            "index_captured_records": int(later["manufacturer_name_normalized"].isin(index_names).sum()),
            "past_count_captured_records": int(later["manufacturer_name_normalized"].isin(count_names).sum()),
            "random_expected_captured_records": round(seen_rows*k/len(universe), 4) if universe else 0,
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month")
    parser.add_argument("--capacity", type=int, default=10)
    parser.add_argument("--category", choices=["nsq", "spurious"], default="nsq")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "primary_workflow")
    args = parser.parse_args()
    location, identity = active_snapshot()
    df = load_dataset((location, identity))
    month = args.month or max(df["collection_month"])
    queue = followup_queue(df, month, args.capacity, args.category).assign(snapshot_id=identity)
    coverage = chronological_coverage(df, args.capacity)
    args.output.mkdir(parents=True, exist_ok=True)
    queue.to_csv(args.output / "followup_queue.csv", index=False, encoding="utf-8-sig")
    coverage.to_csv(args.output / "chronological_coverage.csv", index=False, encoding="utf-8-sig")
    summary = {"snapshot_id": identity, "month": month, "category": args.category,
               "selected_candidates": len(queue), "capacity": args.capacity,
               "interpretation": "Retrospective review of published findings. Not prospective medicine-safety prediction.",
               "limitations": ["Manufacturer text is not verified legal identity.",
                               "Collection-month ordering does not prove publication-time availability.",
                               "No complete market/test denominator; no defect-rate or inspection-yield claim."]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
