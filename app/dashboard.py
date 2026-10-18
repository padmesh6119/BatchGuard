"""Builds outputs/dashboard.html: the inspector decision screen as one self-contained file.

Every number comes from the pipeline. The demo feed is replayed through rank_candidates scan by scan for each
trained backend, so the page plays back exactly what the live queue decided. No server, network or external assets.
"""
from datetime import datetime, timezone
import json
import inspect
import tempfile
import base64
from pathlib import Path

import pandas as pd

from src import identity, layer_a, simulator
from src.common import BANNER, DATA_PROCESSED, OUTPUTS, digest, file_hash
from src.field_model import load_card as load_field_card
from src.fusion import decision_context, load_models, rank_candidates
from src.simulator import CITIES
from src.planning import protected_order
from src.workflow import make_tasks

TEMPLATE = Path(__file__).with_name("template.html")
CITY = {(lat, lon): (name, state) for name, state, lat, lon in CITIES}
RECORD_COLUMNS = ["build_record_id", "collection_month", "source_category", "product", "batch_no",
                  "manufacturer_name_normalized", "failure_type", "reporting_state", "reporting_lab", "source_file",
                  "source_sheet", "source_excel_rows_json"]
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
    recorded_versions = {b: values["model_version"] for b, values in result["backends"].items()}
    current_versions = {b: (read_json(OUTPUTS / "models" / b / "model_card.json") or {}).get("model_version")
                        for b in recorded_versions}
    return {"created_at": result["created_at"], "scope": result["scope"], "workload": result["workload"],
            "recorded_model_versions": recorded_versions, "matches_current_models": recorded_versions == current_versions,
            "workload_sha256": result["workload_sha256"][:16],
            "machine": env["machine"], "python": env["python"], "platform": env["platform"],
            "cpu": env["cpu"].get("model name") or f"IBM Z machine type {env['cpu'].get('machine_type', '?')}",
            "cpus": env["cpu"].get("affinity_cpus"), "nnpa_listed": env["cpu"].get("nnpa_facility_listed"),
            "packages": env["packages"],
            "backends": {b: {"events_per_second": v["events_per_second_median"],
                             "stages": {s: {k: v["stages_ms"][s][k] for k in ("p50", "p95", "p99")} for s in v["stages_ms"]}}
                         for b, v in result["backends"].items()}}


def render_template(payload):
    """Embed bundled fonts so the single-file dashboard also works offline."""
    declarations = []
    for family, name in (("Geist", "Geist.woff2"), ("Geist Mono", "GeistMono.woff2")):
        encoded = base64.b64encode((TEMPLATE.parent / "fonts" / name).read_bytes()).decode("ascii")
        declarations.append('@font-face{font-family:"' + family + '";src:url(data:font/woff2;base64,' + encoded + ') format("woff2");font-weight:100 900;font-style:normal;font-display:swap;}')
    return TEMPLATE.read_text().replace("/*__BATCHGUARD_FONTS__*/", "\n".join(declarations)).replace("/*__BATCHGUARD_DATA__*/null", payload)


def build(output=OUTPUTS / "dashboard.html"):
    df = layer_a.load_dataset()
    df = df.merge(layer_a.load_provenance()[["build_record_id", "source_sheet", "source_excel_rows_json"]],
                  on="build_record_id", how="left", validate="one_to_one")
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
    capacity_report = read_json(OUTPUTS / "capacity_audit.json")
    if capacity_report and (capacity_report.get("planner_sha256") != digest(inspect.getsource(protected_order))
                            or capacity_report.get("source_manifest_sha256") != file_hash(DATA_PROCESSED / "manifest.json")):
        raise ValueError("Capacity audit is stale; rerun python -m src.capacity_audit --backends sklearn snapml")
    protected_steps = {}
    for backend, snapshots in steps.items():
        report = (capacity_report or {}).get("backends", {}).get(backend, {})
        share = report.get("selected_history_share", 0.5)
        if report and report.get("model_version") != models_info[backend]["version"]:
            raise ValueError("Capacity audit uses a different model; rerun python -m src.capacity_audit")
        models_info[backend]["history_share"] = share
        models_info[backend]["reservation_selected_on_validation"] = bool(report)
        protected_steps[backend] = []
        for snapshot in snapshots:
            order = protected_order([r[2] for r in snapshot], [r[3] for r in snapshot],
                                    [r[4] for r in snapshot], [r[0] for r in snapshot], share)
            protected_steps[backend].append([snapshot[index] + [lane] for index, lane in order])
    earlier = df[df["collection_month"].lt(month)]
    keys = earlier["manufacturer_name_normalized"].str.strip().str.casefold()
    product_keys = earlier["product"].str.strip().str.casefold()
    def product_context(candidate):
        product = candidate["product"].strip().casefold()
        if not product:
            return {"total": 0, "records": []}
        manufacturer = candidate["manufacturer"].strip().casefold()
        related = earlier[product_keys.eq(product) & keys.ne(manufacturer)
                          & earlier["source_category"].isin(("central_nsq", "state_nsq"))]
        related = related.sort_values(["collection_month", "build_record_id"], ascending=[False, True])
        return {"total": len(related), "records": rows(related.head(12))}

    candidates = {c["candidate_id"]: {"product": c["product"], "batch": c["batch_no"], "manufacturer": c["manufacturer"],
                                      "history": rows(earlier[keys.eq(c["manufacturer"].strip().casefold())].sort_values("collection_month", ascending=False)),
                                      "product_context": product_context(c),
                                      "reports": rows(df[df["build_record_id"].isin(c["historical_record_ids"])])}
                  for c in final}
    events = [{"id": e["event_id"], "pack": e["pack_id"], "time": e["event_time"], "source": e["source_id"],
               "lat": e["latitude"], "lon": e["longitude"], "city": CITY[(e["latitude"], e["longitude"])][0],
               "state": CITY[(e["latitude"], e["longitude"])][1],
               "cand": simulator.candidate_id(e["product"], e["batch_no"], e["manufacturer_key"])} for e in feed]
    manifest = read_json(DATA_PROCESSED / "manifest.json")
    learning_curve = read_json(OUTPUTS / "scan_learning_curve.json")
    field_directory = OUTPUTS / "field_model"
    if (field_directory / "field_model_card.json").is_file():
        try:
            field_card = load_field_card(field_directory)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            field_card = {"field_review_ready": False, "readiness_reasons": [f"Field model files invalid: {exc}"],
                          "validation": None, "test": None, "source_sha256": ""}
    else:
        field_card = None
    availability = DATA_PROCESSED / "review" / "source_availability.csv"
    name_pairs = identity.suggestions(df, month)
    identity_ids = {record_id for pair in name_pairs for record_id in pair["record_ids"]}
    source_report = read_json(OUTPUTS / "source_audit.json")
    lag_report = read_json(OUTPUTS / "availability_audit.json")
    manifest_sha = file_hash(DATA_PROCESSED / "manifest.json")
    if source_report and source_report.get("processed_manifest_sha256") != manifest_sha:
        source_report = None
    if lag_report and lag_report.get("processed_manifest_sha256") != manifest_sha:
        lag_report = None
    # An offline Start button can replay a genuine saved integration case.
    # Its checks ran in disposable storage at build time, never in the operator database.
    from src.audit_store import AuditStore
    from src.live import LiveEngine
    demo_cases = {}
    demo_clock = datetime(2026, 9, 15, 9, 5, tzinfo=timezone.utc).timestamp()
    for backend in backends:
        if backend:
            with tempfile.TemporaryDirectory() as directory:
                demo_engine = LiveEngine(AuditStore(Path(directory) / "fixture.sqlite3"), df,
                                         {backend: load_models(backend)}, now=lambda: demo_clock)
                demo_cases[backend] = demo_engine.run_demo("dashboard-build-demo", backend, models_info[backend]["history_share"])
                demo_cases[backend]["recorded_at_build"] = True
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "banner": BANNER, "decision_month": month,
        "backends": list(steps), "models": models_info, "codes": list(codes), "feed": events, "steps": steps,
        "protected_steps": protected_steps, "capacity_audit": capacity_report, "demo_cases": demo_cases,
        "india_map": json.loads((TEMPLATE.parent / "maps/india.json").read_text()),
        "demo_input_csv": (Path(__file__).resolve().parents[1] / "data/demo/inspection_case.csv").read_text(),
        "temporal_audit": read_json(OUTPUTS / "temporal_audit.json"),
        "source_audit": source_report,
        "availability_audit": lag_report,
        "delivery_status": read_json(OUTPUTS / "delivery_status.json"),
        "identity_candidates": name_pairs,
        "identity_evidence": rows(earlier[earlier["build_record_id"].isin(identity_ids)].sort_values("collection_month", ascending=False)),
        "workflow_tasks": make_tasks(candidates, month),
        "candidates": candidates, "cities": [{"city": n, "state": s, "lat": la, "lon": lo} for n, s, la, lo in CITIES],
        "evaluation": {b: evaluation(results["backends"][b], read_json(OUTPUTS / "models" / b / "model_card.json"))
                       for b in steps if b in results["backends"]},
        "recurrence": results.get("recurrence_finding"), "limits": results.get("limits", []),
        "field_model": None if field_card is None else {
            "ready": field_card["field_review_ready"], "reasons": field_card["readiness_reasons"],
            "validation": None if field_card["validation"] is None else {k: v for k, v in field_card["validation"].items() if k != "by_site"},
            "test": None if field_card["test"] is None else {k: v for k, v in field_card["test"].items() if k != "by_site"},
            "source_sha256": field_card["source_sha256"][:16]},
        "scan_learning_curve": None if learning_curve is None else {
            "matches_current_dataset": learning_curve.get("processed_manifest_sha256") == file_hash(DATA_PROCESSED / "manifest.json"),
            "fixed_test_episodes": learning_curve["fixed_test_episodes"],
            "challenge_cases": learning_curve["challenge_cases"],
            "rows": [{"training_episodes": row["training_episodes"],
                      "fixed_test_ap": row["fixed_test"]["model"]["average_precision"],
                      "challenge_fp": row["challenge"]["model"]["false_positives"],
                      "challenge_fn": row["challenge"]["model"]["false_negatives"]}
                     for row in learning_curve["results"]]},
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
    output.write_text(render_template(payload))
    return output


if __name__ == "__main__":
    path = build()
    skipped = [b for b in ("sklearn", "snapml") if (OUTPUTS / "models" / b).is_dir() and load_models(b) is None]
    print(path, f"(skipped {', '.join(skipped)}: package not installed)" if skipped else "")
