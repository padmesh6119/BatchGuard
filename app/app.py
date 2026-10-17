"""BatchGuard inspector screen: which batches to sample first within this week's capacity. Humans decide."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import layer_a, simulator
from src.common import BANNER, DATA_PROCESSED, OUTPUTS
from src.fusion import decision_context, load_models, rank_candidates
from src.simulator import CITIES

REVIEW_LOG = ROOT / "data" / "review_actions.jsonl"
STATUSES = ["unreviewed", "sample requested", "reviewed - no sample", "escalated to laboratory"]
CITY = {(lat, lon): f"{name}, {state}" for name, state, lat, lon in CITIES}
POLICIES = {"history_only": "History only", "scan_rule_only": "Scan rule only", "scan_model_only": "Scan model only",
            "fused_weighted": "Fused (weighted)", "fused_tiered": "Fused (tiered)", "random_expectation": "Random"}
RANKERS = {"trained_model": "Trained model", "legacy_60_25_15_index": "Legacy 60/25/15 index",
           "most_past_records": "Most past records", "most_recent_3_months": "Most recent 3 months", "random_expectation": "Random"}
pct = lambda v: None if v is None else round(100*v, 1)

st.set_page_config(page_title="BatchGuard", page_icon="🛡️", layout="wide")


@st.cache_resource(show_spinner="Verifying data and models, building decision context...")
def load(backend):
    df = layer_a.load_dataset()
    feed = simulator.demo_feed(df)
    models = load_models(backend)
    return df, feed, models, decision_context(df, feed[-1]["event_time"][:7], models)


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else None


def reviews():
    latest = {}
    if REVIEW_LOG.is_file():
        for line in REVIEW_LOG.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["candidate_id"]] = row
    return latest


def arrivals(events, alerted):
    ids, packs, rows = set(), set(), []
    for e in events:
        pack = (e["product"], e["batch_no"], e["manufacturer_key"], e["pack_id"])
        tag = "delivery retry (ignored)" if e["event_id"] in ids else "same pack again" if pack in packs else "new pack"
        ids.add(e["event_id"])
        packs.add(pack)
        rows.append({"time (UTC)": e["event_time"][11:19], "location": CITY.get((e["latitude"], e["longitude"]), "unmapped"),
                     "batch": e["batch_no"], "pack": e["pack_id"], "source": e["source_id"], "observed": tag,
                     "alert": simulator.candidate_id(e["product"], e["batch_no"], e["manufacturer_key"]) in alerted})
    return pd.DataFrame(rows[::-1])


backends = [b for b in ("sklearn", "snapml") if (OUTPUTS / "models" / b / "model_card.json").is_file()] or ["sklearn"]
with st.sidebar:
    st.header("Controls")
    backend = st.selectbox("Model backend", backends, key="backend")
try:
    df, feed, models, context = load(backend)
except Exception as exc:
    st.error(f"Could not load verified data or models: {exc}")
    st.stop()

st.session_state.setdefault("received", len(feed))


def step(n):
    st.session_state.received = max(1, min(len(feed), st.session_state.received+n))


with st.sidebar:
    st.slider("Simulated scans received", 1, len(feed), key="received")
    a, b, c = st.columns(3)
    a.button("Start", key="start", on_click=step, args=(-len(feed),), width="stretch")
    b.button("+1", key="plus1", on_click=step, args=(1,), width="stretch")
    c.button("+10", key="plus10", on_click=step, args=(10,), width="stretch")
    capacity = st.slider("This week's sampling capacity (batches)", 1, 50, 10, key="capacity")
    st.caption("Capacity is a maximum, not an obligation to sample.")

received = feed[:st.session_state.received]
ranked = rank_candidates(df, received, models=models, context=context)
latest = reviews()
alerted = {c["candidate_id"] for c in ranked if c["scan_alert"]}
results = read_json(OUTPUTS / "results.json")
card = models.card if models else None

st.title("🛡️ BatchGuard")
st.warning(f"**{BANNER}** Humans decide; nothing here blocks medicine or declares counterfeiting.")
if models is None:
    st.error("No trained models found; showing the untrained historical index. Run `python -m src.fusion run`.")

m = st.columns(5)
m[0].metric("Candidates in 6-hour window", len(ranked))
m[1].metric("Scan alerts (declared rule)", len(alerted))
m[2].metric("Selected / capacity", f"{min(capacity, len(ranked))} / {capacity}")
m[3].metric("Fusion policy", ranked[0]["fusion_policy"] if ranked else "-")
m[4].metric("Decision time (UTC)", received[-1]["event_time"][:16].replace("T", " "))

decision, evaluation, platform, quality = st.tabs(["Decision", "Evaluation", "Platform", "Data quality"])

with decision:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Ranked batches")
        queue = pd.DataFrame([{
            "rank": c["rank"], "within_capacity": c["rank"] <= capacity, "batch": c["batch_no"], "product": c["product"],
            "manufacturer": c["manufacturer"], "historical_risk": c["historical_risk"], "scan_anomaly": c["scan_anomaly"],
            "evidence_quality": c["evidence_quality"], "priority": c["priority_score"],
            "scan_model_p": pct(c["scan_probability"]), "history_model_p": pct(c["history_probability"]),
            "reasons": ", ".join(c["reason_codes"]), "review": latest.get(c["candidate_id"], {}).get("status", "unreviewed")}
            for c in ranked])
        score = lambda label, help: st.column_config.ProgressColumn(label, help=help, min_value=0, max_value=100, format="%.0f")
        st.dataframe(queue, hide_index=True, width="stretch", height=420, column_config={
            "within_capacity": st.column_config.CheckboxColumn("Sample"),
            "historical_risk": score("Historical risk (real)", "Percentile of the Layer A model among earlier manufacturer texts."),
            "scan_anomaly": score("Scan anomaly (simulated)", "Declared rule: 100 impossible travel, 70 repeated-pack burst."),
            "evidence_quality": score("Evidence quality", "0/50/100 for 1/2/3+ asserted sources on one pack; independence unverified."),
            "priority": st.column_config.NumberColumn("Priority", format="%.1f"),
            "scan_model_p": st.column_config.NumberColumn("Scan model %", help="Shown alongside; the rule drives alerts."),
            "history_model_p": st.column_config.NumberColumn("Recurrence model %", help="Next-month report recurrence, not medicine safety.")})
        st.download_button("Download queue (CSV)", queue.to_csv(index=False).encode("utf-8-sig"), "batchguard_queue.csv", "text/csv")
        if results:
            fusion = results["backends"][backend]["fusion"]["test_by_budget"]
            n = min(fusion, key=lambda k: abs(int(k)-capacity))
            fused = f"fused_{results['backends'][backend]['fusion']['selected_on_validation']}"
            st.caption(f"Measured coverage on held-out Jul-Aug 2026 queues at N={n}: {POLICIES[fused]} captured "
                       f"{pct(fusion[n][fused]['clone'])}% of simulated clones and {pct(fusion[n][fused]['recurrence'])}% of "
                       f"real recurring-manufacturer batches; random {pct(fusion[n]['random_expectation']['clone'])}%. See Evaluation.")
    with right:
        st.subheader("Arriving simulated scans")
        st.dataframe(arrivals(received, alerted).head(15), hide_index=True, width="stretch", height=420,
                     column_config={"alert": st.column_config.CheckboxColumn("Alert")})
        st.caption("Exact delivery retries are deduplicated by event_id and never raise an alert.")

    st.divider()
    st.subheader("Batch evidence")
    if not ranked:
        st.info("No scans in the window yet.")
    else:
        chosen = st.selectbox("Batch", range(len(ranked)), key="batch",
                              format_func=lambda i: f"{ranked[i]['rank']}. {ranked[i]['product']} | {ranked[i]['batch_no']}")
        item = ranked[chosen]
        s = st.columns(4)
        s[0].metric("Historical risk (real)", f"{item['historical_risk']:.0f}")
        s[1].metric("Scan anomaly (simulated)", f"{item['scan_anomaly']:.0f}")
        s[2].metric("Evidence quality", f"{item['evidence_quality']:.0f}")
        s[3].metric("Priority", f"{item['priority_score']:.1f}")
        st.write(" ".join(f"`{r}`" for r in item["reason_codes"]))
        timeline = pd.DataFrame([{"time (UTC)": e["event_time"][11:19], "location": CITY.get((e["latitude"], e["longitude"]), "unmapped"),
                                  "pack": e["pack_id"], "source": e["source_id"], "event_id": e["event_id"],
                                  "lat": e["latitude"], "lon": e["longitude"]} for e in item["scan_timeline"]])
        t, mp = st.columns([3, 2])
        with t:
            st.markdown("**Scan timeline (simulated)**")
            st.dataframe(timeline.drop(columns=["lat", "lon"]), hide_index=True, width="stretch")
            packs = timeline.groupby("pack").agg(scans=("event_id", "nunique"), asserted_sources=("source", "nunique"),
                                                 locations=("location", lambda v: " / ".join(sorted(set(v))))).reset_index()
            st.markdown("**Packs, sources and districts**")
            st.dataframe(packs, hide_index=True, width="stretch")
        with mp:
            st.map(timeline[["lat", "lon"]].drop_duplicates(), size=20000)
            st.caption("Synthetic city centroids, not real pharmacy locations.")
        month = received[-1]["event_time"][:7]
        key = item["manufacturer"].strip().casefold()
        earlier = df[df["collection_month"].lt(month)]
        columns = [c for c in ["collection_month", "source_category", "product", "batch_no", "manufacturer_name_normalized",
                               "failure_type", "failure_categories", "reporting_lab", "source_file", "build_record_id"] if c in df]
        st.markdown(f"**Manufacturer history (real CDSCO records before {month})**")
        history = earlier[earlier["manufacturer_name_normalized"].str.strip().str.casefold().eq(key)][columns]
        if history.empty:
            st.info("No earlier record with this manufacturer text. Absence of history is not evidence of quality.")
        else:
            st.dataframe(history.sort_values("collection_month", ascending=False), hide_index=True, width="stretch")
        st.caption("Matched on normalized manufacturer text, which is not a verified legal identity.")
        references = df[df["build_record_id"].isin(item["historical_record_ids"])][columns]
        st.markdown(f"**Published reports of this exact batch: {len(references)}**")
        if not references.empty:
            st.dataframe(references, hide_index=True, width="stretch")
        with st.form("review"):
            previous = latest.get(item["candidate_id"], {})
            status = st.radio("Inspector decision", STATUSES, horizontal=True,
                              index=STATUSES.index(previous.get("status", "unreviewed")))
            note = st.text_input("Note", previous.get("note", ""))
            if st.form_submit_button("Save decision"):
                REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
                with REVIEW_LOG.open("a") as stream:
                    stream.write(json.dumps({"candidate_id": item["candidate_id"], "batch_no": item["batch_no"],
                                             "status": status, "note": note, "priority": item["priority_score"],
                                             "model_version": item["fusion_version"],
                                             "saved_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                st.rerun()

with evaluation:
    if not results or backend not in results["backends"]:
        st.info("No evaluation yet. Run `python -m src.fusion run`.")
    else:
        summary = results["backends"][backend]
        a_, b_, f_ = summary["layer_a"], summary["layer_b"], summary["fusion"]
        finding = results["recurrence_finding"]
        st.subheader("Layer A - real CDSCO history: next-month report recurrence")
        st.write(f"Test months {', '.join(a_['test_months'])}: {a_['test_examples']:,} earlier manufacturer texts, "
                 f"{a_['test_positives']} reported again. Model `{a_['selected']}` chosen on validation only.")
        ap = pd.DataFrame([{"ranker": RANKERS[k], "average_precision": v} for k, v in a_["average_precision"].items()])
        gain = a_["ap_gain_vs_strongest_baseline"]
        c1, c2 = st.columns(2)
        c1.dataframe(ap, hide_index=True, width="stretch")
        c1.caption(f"AP gain vs {RANKERS[a_['strongest_baseline']]}: {gain['mean']:.3f} "
                   f"(bootstrap 95% CI {gain['ci95'][0]:.3f} to {gain['ci95'][1]:.3f}, {gain['rounds']} rounds).")
        captured = pd.DataFrame(a_["reports_captured_by_budget"]).T.rename(columns=RANKERS).rename_axis("top manufacturers")
        c2.dataframe(captured, width="stretch")
        c2.caption(f"Later NSQ reports captured; {a_['reachable_reports']} of {a_['all_reports']} test-month reports "
                   "came from manufacturer texts seen earlier. New texts cannot be ranked from history.")
        st.info(f"Recurrence finding: with history through {finding['history_through']}, "
                f"{finding['previously_seen_pct']:.1f}% ({finding['previously_seen_text_records']} of {finding['later_records']:,}) "
                "of later NSQ records carried exact manufacturer text seen earlier. This is a split-specific measurement, "
                "not a prediction ceiling and not evidence about scan detection.")
        st.subheader("Layer B - simulated scans: clone-pattern detection")
        rows = [{"detector": name, "precision": pct(v["precision"]), "recall": pct(v["recall"]),
                 "true_positives": v["true_positives"], "false_positives": v["false_positives"]}
                for name, v in (("Declared rule (drives alerts)", b_["rule"]), (f"Trained `{b_['selected']}`", b_["model"]))]
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        c2.dataframe(pd.DataFrame([{"held-out family": f["scenario"], "clone": bool(f["clone_label"]), "episodes": f["episodes"],
                                    "rule alert %": pct(f["rule_alert_rate"]), "model alert %": pct(f["model_alert_rate"])}
                                   for f in b_["held_out_families"]]), hide_index=True, width="stretch")
        st.caption("Labels come from the simulator. The trained model did not beat the rule on held-out families, so the rule drives alerts.")
        st.subheader("Fusion - one queue, two risks")
        table = pd.DataFrame({f"N={n}": {f"{POLICIES[p]} - {k}": pct(v[k]) for p, v in row.items() for k in ("clone", "recurrence")}
                              for n, row in f_["test_by_budget"].items()})
        st.dataframe(table, width="stretch")
        st.caption(f"Policy `{f_['selected_on_validation']}` chosen on the June 2026 validation queue. Share of simulated clones and of "
                   "real recurring-manufacturer batches captured in held-out Jul-Aug 2026 queues; only batches published before each "
                   "month enter its queue. Recurring batches per month are few, so recurrence shares move in large steps.")
        if card:
            st.dataframe(pd.DataFrame([{"month": t["target_month"], "candidates": t["candidates"], "simulated clones": t["clones"],
                                        "recurring-manufacturer batches": t["recurring_manufacturer_candidates"]}
                                       for t in card["fusion"]["test"]]).drop_duplicates(), hide_index=True)
        charts = [OUTPUTS / "charts" / name for name in results.get("charts", [])]
        cols = st.columns(max(1, len(charts)))
        for col, chart in zip(cols, charts):
            if chart.is_file():
                col.image(str(chart))

with platform:
    st.subheader("Measured stream benchmark: laptop vs IBM LinuxONE")
    rows = []
    for host in ("laptop", "linuxone"):
        bench = read_json(OUTPUTS / f"benchmark_{host}.json")
        if bench is None:
            st.info(f"{host}: not measured yet (`python -m src.fusion benchmark` on that host).")
            continue
        env = bench["environment"]
        for name, result in bench["backends"].items():
            stage = result["stages_ms"]
            rows.append({"host": host, "machine": env["machine"], "cpu": env["cpu"].get("model name") or env["cpu"].get("machine_type", ""),
                         "python": env["python"], "backend": name, "events/s": round(result["events_per_second_median"]),
                         "per-scan p50 ms": round(stage["per_scan_decision_ms"]["p50"], 2),
                         "per-scan p99 ms": round(stage["per_scan_decision_ms"]["p99"], 2),
                         "queue rebuild p50 ms": round(stage["queue_rebuild_with_cached_context_ms"]["p50"], 1),
                         "context build p50 ms": round(stage["decision_context_build_ms"]["p50"])})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Same workload hash on every host; single process, in memory. No accelerator use is claimed unless measured.")

with quality:
    manifest = read_json(DATA_PROCESSED / "manifest.json")
    if manifest:
        st.write(f"{manifest['summary']['analytical_records']:,} analytical records, months "
                 f"{manifest['summary']['months'][0]} to {manifest['summary']['months'][-1]}; every file hash-verified on load.")
    st.bar_chart(layer_a.monthly_summary(df).set_index("collection_month")[["central_nsq", "state_nsq"]])
    availability = DATA_PROCESSED / "review" / "source_availability.csv"
    if availability.is_file():
        st.markdown("**Source availability**")
        st.dataframe(pd.read_csv(availability), hide_index=True, width="stretch")
        st.caption("An absent spurious sheet means unavailable source data, not zero incidents.")
    fields = ["product", "batch_no", "manufacturer_name_normalized", "manufacture_date_raw", "expiry_date_raw"]
    st.markdown("**Missing evidence**")
    st.dataframe(pd.DataFrame([{"field": f, "missing_records": int(df[f].str.strip().eq("").sum())} for f in fields if f in df]),
                 hide_index=True)
    st.markdown("**Failure mapping**")
    st.dataframe(df["failure_mapping_status"].value_counts().rename_axis("status").reset_index(name="records"), hide_index=True)
