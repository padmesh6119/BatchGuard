"""Capacity allocation between historical follow-up and scan-pattern review.

This policy reserves history slots explicitly rather than adding unlike scores.
It uses no outcome labels. Labels are used only by the separate evaluation.
"""
import math


def protected_order(history, scan, quality, identifiers, history_share=0.5):
    if not 0 < history_share <= 1:
        raise ValueError("history_share must be in (0, 1]")
    if len({len(history), len(scan), len(quality), len(identifiers)}) != 1:
        raise ValueError("Planning columns must have the same length")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Planning candidate IDs must be unique")
    history_order = sorted(range(len(history)), key=lambda i: (-history[i], identifiers[i]))
    alert_order = sorted((i for i in range(len(scan)) if scan[i] > 0),
                         key=lambda i: (-scan[i], -quality[i], -history[i], identifiers[i]))
    used, result = set(), []
    for position in range(1, len(history) + 1):
        history_turn = math.ceil(position * history_share) > math.ceil((position - 1) * history_share)
        preferred = history_order if history_turn else alert_order
        chosen = next((i for i in preferred if i not in used), None)
        lane = "history" if history_turn else "scan review"
        if chosen is None:
            chosen = next(i for i in history_order if i not in used)
            lane = "history"
        if lane == "history" and history[chosen] <= 0:
            # Missing history is never presented as positive historical evidence.
            chosen = next((i for i in alert_order if i not in used), chosen)
            lane = "scan review" if scan[chosen] > 0 else "coverage unknown"
        used.add(chosen)
        result.append((chosen, lane))
    return result


def plan_candidates(candidates, history_share=0.5):
    order = protected_order([c["historical_risk"] for c in candidates],
                            [c["scan_anomaly"] for c in candidates],
                            [c["evidence_quality"] for c in candidates],
                            [c["candidate_id"] for c in candidates], history_share)
    return [{**candidates[index], "rank": rank, "selection_lane": lane,
             "queue_strategy": "protected_history", "history_share": history_share}
            for rank, (index, lane) in enumerate(order, 1)]
