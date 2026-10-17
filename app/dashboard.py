"""Builds outputs/dashboard.html: the inspector decision screen as one self-contained file.

Every number comes from the pipeline. The demo feed is replayed through rank_candidates scan by scan for each
trained backend, so the page plays back exactly what the live queue decided. No server, network or external assets.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from src import layer_a, simulator
from src.common import BANNER, DATA_PROCESSED, OUTPUTS
from src.fusion import decision_context, load_models, rank_candidates
from src.simulator import CITIES

TEMPLATE = Path(__file__).with_name("template.html")
CITY = {(lat, lon): (name, state) for name, state, lat, lon in CITIES}
RECORD_COLUMNS = ["build_record_id", "collection_month", "source_category", "product", "batch_no",
                  "manufacturer_name_normalized", "failure_type", "reporting_state", "reporting_lab", "source_file"]
MISSING_FIELDS = ["product", "batch_no", "manufacturer_name_normalized", "manufacture_date_raw", "expiry_date_raw"]


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def rows(frame):
    return frame[[c for c in RECORD_COLUMNS if c in frame]].fillna("").astype(str).to_dict("records")


def rounded(value, digits=4):
    return None if value is None else round(float(value), digits)


def replay(df, feed, models, codes):
    """Rank after every arriving scan, exactly as the live queue would."""
    context = decision_context(df, feed[-1]["event_time"][:7], models)
    index = lambda code: codes.setdefault(code, len(codes))
    steps, ranked = [], []
    for k in range(1, len(feed)+1):
        ranked = rank_candidates(df, feed[:k], models=models, context=context)
        steps.append([[c["candidate_id"], c["priority_score"], c["historical_risk"], c["scan_anomaly"], c["evidence_quality"],
                       rounded(c["scan_probability"]), rounded(c["history_probability"]), [index(r) for r in c["reason_codes"]]]
                      for c in ranked])
    return steps, ranked, len(context.get("history", []))


def evaluation(summary, card):
    fusion = card["fusion"] if card else {}
    months = {(t["target_month"], t["candidates"], t["clones"], t["recurring_manufacturer_candidates"]) for t in fusion.get("test", [])}
    return {**summary,
            "fusion_months": [dict(zip(("month", "candidates", "clones", "recurring"), m)) for m in sorted(months)],
            "validation_month": fusion.get("validation_month"),
            "validation_balanced": fusion.get("validation_mean_balanced_capture"),
            "families": card["scan"]["families"] if card else [],
            "validation_baselines": card["history"]["validation_average_precision_vs_baselines"] if card else {}}


def benchmark(host):
    result = read_json(OUTPUTS / f"benchmark_{host}.json")
    if result is None:
        return None
    env = result["environment"]
    return {"created_at": result["created_at"], "scope": result["scope"], "workload": result["workload"],
            "workload_sha256": result["workload_sha256"][:16],
            "machine": env["machine"], "python": env["python"], "platform": env["platform"],
            "cpu": env["cpu"].get("model name") or f"IBM Z machine type {env['cpu'].get('machine_type', '?')}",
            "cpus": env["cpu"].get("affinity_cpus"), "nnpa_listed": env["cpu"].get("nnpa_facility_listed"),
            "packages": env["packages"],
            "backends": {b: {"events_per_second": v["events_per_second_median"],
                             "stages": {s: {k: v["stages_ms"][s][k] for k in ("p50", "p95", "p99")} for s in v["stages_ms"]}}
                         for b, v in result["backends"].items()}}


def build(output=OUTPUTS / "dashboard.html"):
    df = layer_a.load_dataset()
    feed = simulator.demo_feed(df)
    month = feed[-1]["event_time"][:7]
    results = read_json(OUTPUTS / "results.json") or {"backends": {}}
    backends = [b for b in ("sklearn", "snapml") if load_models(b) is not None] or [None]
    codes, steps, models_info, final = {}, {}, {}, []
    for backend in backends:
        models = load_models(backend) if backend else None
        key = backend or "untrained"
        steps[key], ranked, universe = replay(df, feed, models, codes)
        final = final or ranked
        models_info[key] = {"version": models.version if models else "untrained-baseline",
                            "policy": models.policy if models else "weighted",
                            "threshold": models.threshold if models else None, "history_universe": universe,
                            "history_selected": models.card["history"]["selected"] if models else None,
                            "scan_selected": models.card["scan"]["selected"] if models else None}
    earlier = df[df["collection_month"].lt(month)]
    keys = earlier["manufacturer_name_normalized"].str.strip().str.casefold()
    candidates = {c["candidate_id"]: {"product": c["product"], "batch": c["batch_no"], "manufacturer": c["manufacturer"],
                                      "history": rows(earlier[keys.eq(c["manufacturer"].strip().casefold())].sort_values("collection_month", ascending=False)),
                                      "reports": rows(df[df["build_record_id"].isin(c["historical_record_ids"])])}
                  for c in final}
    events = [{"id": e["event_id"], "pack": e["pack_id"], "time": e["event_time"], "source": e["source_id"],
               "lat": e["latitude"], "lon": e["longitude"], "city": CITY[(e["latitude"], e["longitude"])][0],
               "state": CITY[(e["latitude"], e["longitude"])][1],
               "cand": simulator.candidate_id(e["product"], e["batch_no"], e["manufacturer_key"])} for e in feed]
    manifest = read_json(DATA_PROCESSED / "manifest.json")
    availability = DATA_PROCESSED / "review" / "source_availability.csv"
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "banner": BANNER, "decision_month": month,
        "backends": list(steps), "models": models_info, "codes": list(codes), "feed": events, "steps": steps,
        "candidates": candidates, "cities": [{"city": n, "state": s, "lat": la, "lon": lo} for n, s, la, lo in CITIES],
        "evaluation": {b: evaluation(results["backends"][b], read_json(OUTPUTS / "models" / b / "model_card.json"))
                       for b in steps if b in results["backends"]},
        "recurrence": results.get("recurrence_finding"), "limits": results.get("limits", []),
        "benchmarks": {host: benchmark(host) for host in ("laptop", "linuxone")},
        "data": {"summary": manifest["summary"] if manifest else {}, "manifest_sha256": results.get("data", {}).get("processed_manifest_sha256", ""),
                 "monthly": layer_a.monthly_summary(df).astype({"collection_month": str}).to_dict("records"),
                 "spurious_monthly": df[df["source_category"].eq("spurious")]["collection_month"].value_counts().sort_index().to_dict(),
                 "availability": pd.read_csv(availability, dtype=str, keep_default_na=False).to_dict("records") if availability.is_file() else [],
                 "missing": [{"field": f, "missing": int(df[f].str.strip().eq("").sum()), "records": len(df)} for f in MISSING_FIELDS if f in df],
                 "mapping": df["failure_mapping_status"].value_counts().rename_axis("status").reset_index(name="records").to_dict("records")},
    }
    payload = json.dumps(data, separators=(",", ":"), default=lambda v: v.item() if hasattr(v, "item") else str(v)).replace("</", "<\\/")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(TEMPLATE.read_text().replace("/*__BATCHGUARD_DATA__*/null", payload))
    return output


if __name__ == "__main__":
    path = build()
    skipped = [b for b in ("sklearn", "snapml") if (OUTPUTS / "models" / b).is_dir() and load_models(b) is None]
    print(path, f"(skipped {', '.join(skipped)}: package not installed)" if skipped else "")
