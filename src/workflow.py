"""Small timed workflow pilot; actual user answers and server times only."""
from collections import defaultdict
from statistics import median

from src.common import digest


def make_tasks(candidates, before, limit=12):
    seen, tasks = set(), []
    for cid, candidate in sorted(candidates.items()):
        manufacturer = candidate["manufacturer"]
        records = [r for r in candidate["history"] if r["source_category"] in {"central_nsq", "state_nsq"}]
        if not records or manufacturer in seen:
            continue
        seen.add(manufacturer)
        tasks.append({"task_id": digest([manufacturer, before])[:24], "candidate_id": cid,
                      "manufacturer": manufacturer, "before": before,
                      "question": f"How many earlier NSQ records match this exact manufacturer text before {before}? Count reports, not distinct batches.",
                      "expected_count": len(records), "source_files": sorted({r["source_file"] for r in records})})
    return tasks[:limit]


def summarize(starts, finishes):
    methods, participants = defaultdict(list), defaultdict(dict)
    for study_id, result in finishes.items():
        start = starts[study_id]
        methods[start["method"]].append(result)
        participants[start["reviewer_id"]].setdefault(start["method"], []).append(result["elapsed_seconds"])
    paired = []
    for values in participants.values():
        if "manual" in values and "batchguard" in values:
            baseline, aided = median(values["manual"]), median(values["batchguard"])
            paired.append({"manual_median_seconds": baseline, "batchguard_median_seconds": aided,
                           "observed_manual_to_batchguard_ratio": baseline / max(aided, .001)})
    return {"completed_tasks": len(finishes), "participants": len(participants),
            "methods": {method: {"tasks": len(rows), "correct_answers": sum(r["correct"] for r in rows),
                                 "median_seconds": median(r["elapsed_seconds"] for r in rows)}
                        for method, rows in methods.items()},
            "paired_participants": paired,
            "status": "no human results yet" if not finishes else "exploratory workflow pilot",
            "limits": ["Roles and method adherence are self-declared; no professional identity is verified.",
                       "Tasks use distinct manufacturers per participant and alternate methods; difficulty can still differ.",
                       "Timing includes reading and interruptions. This is not a controlled detection-accuracy study."]}
