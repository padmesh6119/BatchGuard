from pathlib import Path
import subprocess
import sys

import pandas as pd
import streamlit as st

from batchguard_engine import load_dataset, historical_priorities, monthly_summary
from primary_workflow import followup_queue, chronological_coverage
from snapshot_store import DATASETS, ROOT, active_snapshot

st.set_page_config(page_title="BatchGuard", page_icon="🛡️", layout="wide")
st.title("🛡️ BatchGuard")
st.caption("Medicine-quality evidence and explained inspection follow-up priorities")
st.info(
    "Review published CDSCO findings, choose a follow-up capacity, and inspect the source evidence. "
    "Historical recurrence supports review; it does not estimate whether an untested medicine is unsafe."
)

with st.sidebar:
    st.header("Official workbook data")
    st.caption("Add monthly YYYY-MM_all.xlsx workbooks to data/raw/.")
    if st.button("Refresh workbook data", type="primary", use_container_width=True):
        with st.spinner("Building and validating a complete snapshot..."):
            result = subprocess.run([sys.executable, str(ROOT / "refresh_data.py")],
                                    cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            st.error("Refresh failed. The previous published snapshot is retained.")
            st.code((result.stdout + result.stderr)[-5000:])
        else:
            st.cache_data.clear()
            st.rerun()

@st.cache_data(show_spinner="Validating historical evidence...")
def get_data(snapshot_token, _location):
    snapshot_identity = snapshot_token if isinstance(snapshot_token, str) else "legacy-local-files"
    return load_dataset((_location, snapshot_identity))

@st.cache_data(show_spinner="Checking earlier history against later reports...")
def get_coverage(snapshot_token, capacity, _df):
    return chronological_coverage(_df, capacity)

@st.cache_data(show_spinner=False)
def get_historical_context(snapshot_token, _df):
    return historical_priorities(_df), monthly_summary(_df)

try:
    location, identity = active_snapshot()
    token = identity if identity != "legacy-local-files" else tuple(
        (location / "data" / "processed" / name).stat().st_mtime_ns for name in DATASETS)
    df = get_data(token, location)
except Exception as exc:
    st.error(f"Could not load the historical dataset: {exc}")
    st.stop()

months = sorted(df["collection_month"].unique())
nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])]
spurious = df[df["source_category"].eq("spurious")]
a, b, c, d = st.columns(4)
a.metric("Analytical records", f"{len(df):,}")
b.metric("Reported NSQ findings", f"{len(nsq):,}")
c.metric("Spurious-report records", f"{len(spurious):,}")
d.metric("Months covered", len(months))
st.caption(f"Coverage: {months[0]} to {months[-1]} | Snapshot: {identity[:16]}")

priorities_tab, history_tab, evaluation_tab, quality_tab = st.tabs([
    "Inspection priorities", "Historical evidence", "History evaluation", "Data quality"
])

with priorities_tab:
    st.subheader("Follow-up queue from published findings")
    a, b, c = st.columns(3)
    month = a.selectbox("Report month", months, index=len(months)-1)
    category_label = b.selectbox("Evidence category", ["NSQ findings", "Spurious reports"])
    capacity = c.slider("Follow-up capacity (unique candidates)", 1, 100, 10)
    category = "nsq" if category_label == "NSQ findings" else "spurious"
    queue = followup_queue(df, month, int(capacity), category).assign(snapshot_id=identity)
    st.caption(
        "One candidate per product, batch, and manufacturer-text signature. Ordering uses only "
        "NSQ history from earlier collection months; a zero index means no higher measured recurrence, "
        "not proven safety. This is follow-up of published findings, not a list of untested market batches."
    )
    st.metric("Selected follow-up candidates", len(queue))
    if queue.empty:
        st.info("No batch-identifiable records in this category/month. Check source availability below.")
    else:
        st.dataframe(queue[["rank", "product", "batch_no", "historical_priority_index", "prior_nsq_records",
                            "prior_months_observed", "history_status", "failure_categories", "reason"]],
                     use_container_width=True, hide_index=True)
        st.download_button("Download follow-up queue", queue.to_csv(index=False).encode("utf-8-sig"),
                           "batchguard_followup_queue.csv", "text/csv")
        st.subheader("Evidence for a selected candidate")
        selected = st.selectbox("Candidate evidence", queue["candidate_id"].tolist(),
                                format_func=lambda cid: next(f"{r['rank']}. {r['product']} | {r['batch_no']}"
                                for r in queue.to_dict("records") if r["candidate_id"] == cid))
        candidate = queue.loc[queue["candidate_id"].eq(selected)].iloc[0]
        record_ids = candidate["record_ids"].split(" | ")
        evidence = df[df["build_record_id"].isin(record_ids)]
        evidence_columns = ["build_record_id", "collection_month", "source_category", "product", "batch_no",
                            "manufacturer_raw", "manufacturer_name_raw", "manufacture_date_raw", "expiry_date_raw",
                            "failure_type", "failure_categories", "failure_mapping_status", "nsq_remark", "firm_reply",
                            "reporting_lab", "source_file"]
        st.dataframe(evidence[evidence_columns], use_container_width=True, hide_index=True)
        st.download_button("Download candidate evidence", evidence.assign(snapshot_id=identity).to_csv(index=False).encode("utf-8-sig"),
                           "batchguard_candidate_evidence.csv", "text/csv")
        for source in sorted(evidence["source_file"].unique()):
            workbook = location / "data" / "raw" / Path(source).name
            if workbook.is_file():
                st.download_button(f"Download source workbook: {source}", workbook.read_bytes(), source,
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if category == "spurious":
        st.warning("A reported spurious allegation or manufacturer denial requires verification. Manufacturer identity may be unavailable.")

with history_tab:
    st.subheader("Reported NSQ history")
    st.write("Snapshot-wide descriptive context. The follow-up queue uses earlier months only.")
    historical, monthly = get_historical_context(token, df)
    st.bar_chart(monthly.set_index("collection_month")[["central_nsq", "state_nsq"]])
    st.dataframe(monthly, use_container_width=True, hide_index=True)
    st.caption("Index weights: record recurrence 60, months observed 25, distinct products 15; each component is min-max scaled.")
    st.dataframe(historical.head(50), use_container_width=True, hide_index=True)
    st.download_button("Download historical manufacturer context", historical.to_csv(index=False).encode("utf-8-sig"),
                       "batchguard_historical_context.csv", "text/csv")

with evaluation_tab:
    st.subheader("How much later reporting can earlier history cover?")
    evaluation_k = st.slider("Manufacturer signatures in evaluation (K)", 1, 100, 10)
    coverage = get_coverage(token, int(evaluation_k), df)
    st.write(
        "Each row ranks manufacturer-text signatures from earlier months and checks later NSQ reports. "
        "Compare the descriptive index, most past records, and the exact random-selection expectation. "
        "K counts manufacturer signatures here; the follow-up queue capacity counts product/batch candidates."
    )
    if not coverage.empty:
        st.dataframe(coverage, use_container_width=True, hide_index=True)
        st.download_button("Download chronological coverage check", coverage.to_csv(index=False).encode("utf-8-sig"),
                           "batchguard_chronological_coverage.csv", "text/csv")
    st.warning(
        "These are subsequent-report coverage counts, not defect rates or failures caught per inspection. "
        "New manufacturer signatures cannot be selected from earlier history. Publication dates are unavailable; "
        "collection-month ordering is not proof of when evidence became public. No trained model is claimed."
    )

with quality_tab:
    st.subheader("Source availability")
    availability_files = sorted((location / "reports").glob("????-??_source_availability.csv"))
    if availability_files:
        availability = pd.concat([pd.read_csv(p) for p in availability_files], ignore_index=True)
        st.dataframe(availability, use_container_width=True, hide_index=True)
        if availability["spurious_data_status"].eq("source_sheet_missing").any():
            st.warning("An absent spurious sheet means unavailable source data, not zero incidents.")
    fields = ["product", "batch_no", "manufacturer_name_normalized", "manufacture_date_raw", "expiry_date_raw"]
    st.subheader("Missing evidence")
    st.dataframe(pd.DataFrame([{"field": field, "missing_records": int(df[field].str.strip().eq("").sum())}
                               for field in fields]), use_container_width=True, hide_index=True)
    st.caption("Normalized manufacturer text is not a verified legal manufacturer identity. Do not merge company/address variants without review.")
    st.subheader("Failure mapping review")
    st.dataframe(df["failure_mapping_status"].value_counts().rename_axis("status").reset_index(name="records"),
                 use_container_width=True, hide_index=True)
    st.download_button("Download analytical evidence snapshot", df.to_csv(index=False).encode("utf-8-sig"),
                       "batchguard_analytical_snapshot.csv", "text/csv")

st.caption("BatchGuard: human review and laboratory verification determine action.")
