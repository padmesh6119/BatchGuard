from __future__ import annotations

from pathlib import Path
import random
import uuid
from datetime import datetime, timedelta

import pandas as pd
from snapshot_store import active_snapshot, validate_snapshot

DATA_DIR = Path(__file__).resolve().parent / "data" / "processed"
ANALYTICAL_PATH = DATA_DIR / "all_months_analytical.csv"
MANUFACTURER_PATH = DATA_DIR / "all_months_manufacturer_normalized.csv"
FAILURE_PATH = DATA_DIR / "all_months_failure_normalized.csv"

def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Required dataset not found: {path}. Run refresh_data.py first."
        )
    return pd.read_csv(path, dtype=str, keep_default_na=False)

def load_dataset(snapshot=None) -> pd.DataFrame:
    """Load the current analytical snapshot and attach derived fields by stable record ID."""
    location, identity = snapshot if snapshot is not None else active_snapshot()
    if identity != "legacy-local-files":
        validate_snapshot(location)
    directory = location / "data" / "processed"
    df = _read_csv(directory / ANALYTICAL_PATH.name)
    if "build_record_id" not in df:
        raise ValueError("Analytical dataset is missing build_record_id.")
    for path, columns in [
        (directory / MANUFACTURER_PATH.name, ["build_record_id", "manufacturer_name_normalized",
                             "manufacturer_text_for_review"]),
        (directory / FAILURE_PATH.name, ["build_record_id", "failure_categories",
                        "failure_mapping_status"]),
    ]:
        derived = _read_csv(path)
        missing = [c for c in columns if c not in derived.columns]
        if missing:
            raise ValueError(f"{path.name} missing columns: {missing}")
        # A one-to-one merge is required; otherwise the snapshot is inconsistent.
        if derived["build_record_id"].duplicated().any():
            raise ValueError(f"{path.name} has duplicate build_record_id values.")
        if set(df["build_record_id"]) != set(derived["build_record_id"]):
            raise ValueError(
                f"{path.name} record IDs do not match the analytical snapshot. "
                "Refresh all derived datasets together."
            )
        df = df.merge(derived[columns], on="build_record_id", how="left",
                      validate="one_to_one")
    if len(df) == 0:
        raise ValueError("Analytical dataset is empty.")
    if df["build_record_id"].duplicated().any():
        raise ValueError("Dataset has duplicate build_record_id values.")
    return df

def _minmax(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0)
    if values.max() == values.min():
        return pd.Series(0.0, index=series.index)
    return (values - values.min()) / (values.max() - values.min())

def historical_priorities(df: pd.DataFrame) -> pd.DataFrame:
    """Transparent descriptive index from observed NSQ records, not probability."""
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])].copy()
    nsq["manufacturer_key"] = nsq.get("manufacturer_name_normalized", pd.Series("", index=nsq.index)).astype(str).str.strip()
    nsq = nsq[nsq["manufacturer_key"].ne("")].copy()
    if nsq.empty:
        return pd.DataFrame(columns=[
            "priority_rank", "priority_index", "manufacturer_key", "nsq_records",
            "months_observed", "distinct_products", "central_records", "state_records",
            "unresolved_records", "reason_codes", "products", "months"
        ])

    nsq["failure_mapping_status"] = nsq.get("failure_mapping_status", pd.Series("", index=nsq.index)).astype(str)
    nsq["failure_categories"] = nsq.get("failure_categories", pd.Series("", index=nsq.index)).astype(str)
    summary = nsq.groupby("manufacturer_key", dropna=False).agg(
        nsq_records=("build_record_id", "size"),
        months_observed=("collection_month", "nunique"),
        distinct_products=("product", lambda s: s.astype(str).str.strip().replace("", pd.NA).nunique()),
        central_records=("source_category", lambda s: int((s == "central_nsq").sum())),
        state_records=("source_category", lambda s: int((s == "state_nsq").sum())),
        unresolved_records=("failure_mapping_status", lambda s: int(s.isin(["manual_review_required", "missing"]).sum())),
        products=("product", lambda s: " | ".join(sorted(set(v.strip() for v in s if v.strip()))[:12])),
        months=("collection_month", lambda s: " | ".join(sorted(set(v for v in s if v)))),
        categories=("failure_categories", lambda s: " | ".join(sorted({
            cat for value in s for cat in str(value).split(";")
            if cat and cat not in {"other_or_unclassified", "missing_failure_type"}
        }))),
    ).reset_index()

    # Explicitly defined, reproducible descriptive index; not calibrated to outcomes.
    summary["_records_norm"] = _minmax(summary["nsq_records"])
    summary["_months_norm"] = _minmax(summary["months_observed"])
    summary["_products_norm"] = _minmax(summary["distinct_products"])
    summary["priority_index"] = (
        60 * summary["_records_norm"]
        + 25 * summary["_months_norm"]
        + 15 * summary["_products_norm"]
    ).round(1)
    summary["reason_codes"] = summary.apply(
        lambda r: "; ".join(
            ([f"REPEAT_NSQ_RECORDS={int(r['nsq_records'])}"] if r["nsq_records"] >= 2 else ["SINGLE_OBSERVED_NSQ_RECORD"])
            + ([f"OBSERVED_ACROSS_MONTHS={int(r['months_observed'])}"] if r["months_observed"] >= 2 else [])
            + ([f"DISTINCT_PRODUCTS={int(r['distinct_products'])}"] if r["distinct_products"] >= 2 else [])
            + ([f"UNRESOLVED_FAILURES={int(r['unresolved_records'])}"] if r["unresolved_records"] else [])
        ), axis=1
    )
    summary = summary.sort_values(
        ["priority_index", "nsq_records", "months_observed", "distinct_products"],
        ascending=False
    ).reset_index(drop=True)
    summary.insert(0, "priority_rank", range(1, len(summary) + 1))
    summary["interpretation"] = "Descriptive inspection-priority index; not probability or verified legal identity."
    return summary.drop(columns=["_records_norm", "_months_norm", "_products_norm", "categories"])

def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    nsq = df[df["source_category"].isin(["central_nsq", "state_nsq"])]
    if nsq.empty:
        return pd.DataFrame(columns=["collection_month", "central_nsq", "state_nsq", "total_nsq"])
    out = nsq.pivot_table(index="collection_month", columns="source_category",
                          values="build_record_id", aggfunc="count", fill_value=0).reset_index()
    for col in ["central_nsq", "state_nsq"]:
        if col not in out:
            out[col] = 0
    out["total_nsq"] = out["central_nsq"] + out["state_nsq"]
    return out.sort_values("collection_month")

def make_simulated_scans(df: pd.DataFrame, count: int = 60, seed: int = 2026) -> pd.DataFrame:
    """Create synthetic events for demonstration; never represents real market scans."""
    rng = random.Random(seed)
    source = df[df["source_category"].isin(["central_nsq", "state_nsq", "spurious"])].copy()
    source = source[(source["product"].str.strip() != "") & (source["batch_no"].str.strip() != "")]
    if source.empty:
        raise ValueError("No product/batch pairs available to seed the simulator.")
    pairs = source[["product", "batch_no", "manufacturer_raw", "source_category"]].drop_duplicates().to_dict("records")
    sites = ["SITE-COIMBATORE-01", "SITE-CHENNAI-02", "SITE-BENGALURU-03",
             "SITE-HYDERABAD-04", "SITE-DELHI-05", "SITE-MUMBAI-06"]
    now = datetime.now()
    events = []
    for i in range(max(1, count)):
        known = rng.random() < 0.82
        if known:
            pair = rng.choice(pairs)
            product, batch = pair["product"], pair["batch_no"]
            manufacturer = pair["manufacturer_raw"]
        else:
            pair = rng.choice(pairs)
            product = pair["product"]
            batch = f"SIM-{rng.randrange(100000, 999999)}"
            manufacturer = pair["manufacturer_raw"]
        events.append({
            "scan_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "event_time": (now - timedelta(minutes=rng.randrange(0, 240))).isoformat(timespec="seconds"),
            "product": product,
            "batch_no": batch,
            "manufacturer_text": manufacturer,
            "site_id": rng.choice(sites),
            "simulated": True,
            "seed_source_category": pair["source_category"] if known else "synthetic_unknown_batch",
        })
    # Inject two deliberately synthetic patterns so the demo visibly exercises detection.
    if len(events) >= 8:
        chosen = events[0].copy()
        chosen["scan_id"] = events[1]["scan_id"]  # duplicate scan token
        chosen["event_time"] = (now - timedelta(minutes=1)).isoformat(timespec="seconds")
        chosen["site_id"] = sites[-1]
        events[1] = chosen
        repeated = events[2].copy()
        repeated["site_id"] = sites[0]
        repeated["event_time"] = (now - timedelta(minutes=2)).isoformat(timespec="seconds")
        events[2] = repeated
        repeated2 = repeated.copy()
        repeated2["site_id"] = sites[1]
        repeated2["event_time"] = (now - timedelta(minutes=3)).isoformat(timespec="seconds")
        events[3] = repeated2
    return pd.DataFrame(events)

def detect_scan_anomalies(scans: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Rule-based anomaly flags for synthetic events; flags are not counterfeit verdicts."""
    result = scans.copy()
    reference = df.copy()
    reference["pair_key"] = reference["product"].str.strip().str.casefold() + "||" + reference["batch_no"].str.strip().str.casefold()
    valid_reference = (
        reference["product"].str.strip().ne("")
        & reference["batch_no"].str.strip().ne("")
    )
    known_keys = set(reference.loc[valid_reference, "pair_key"])
    spurious_keys = set(reference.loc[
        valid_reference & reference["source_category"].eq("spurious"),
        "pair_key"
    ])
    result["pair_key"] = result["product"].str.strip().str.casefold() + "||" + result["batch_no"].str.strip().str.casefold()
    result["reference_match"] = result["pair_key"].isin(known_keys)
    result["spurious_report_match"] = result["pair_key"].isin(spurious_keys)
    result["duplicate_scan_token"] = result["scan_id"].duplicated(keep=False)
    repeated = result.groupby("pair_key")["site_id"].transform("nunique")
    result["multi_site_same_batch"] = (repeated > 1) & result["reference_match"]
    result["anomaly_reasons"] = result.apply(
        lambda r: "; ".join(
            (["UNKNOWN_PRODUCT_BATCH_IN_REFERENCE"] if not r["reference_match"] else [])
            + (["MATCHED_SPURIOUS_REPORT_REFERENCE_REQUIRES_REVIEW"] if r["spurious_report_match"] else [])
            + (["DUPLICATE_SCAN_TOKEN"] if r["duplicate_scan_token"] else [])
            + (["SAME_BATCH_SEEN_AT_MULTIPLE_SIMULATED_SITES"] if r["multi_site_same_batch"] else [])
        ) or "NO_RULE_TRIGGERED", axis=1
    )
    result["anomaly_flag"] = result["anomaly_reasons"].ne("NO_RULE_TRIGGERED")
    result["review_note"] = result["anomaly_flag"].map(
        {True: "Review signal only; verify source, packaging and supply chain.",
         False: "No configured rule triggered; this does not prove authenticity."}
    )
    return result.drop(columns=["pair_key"])

def build_inspection_queue(df: pd.DataFrame, scans: pd.DataFrame) -> pd.DataFrame:
    """Fuse descriptive historical priority and simulated anomaly signals."""
    flagged = detect_scan_anomalies(scans, df)
    priorities = historical_priorities(df)
    if priorities.empty:
        priority_lookup = {}
    else:
        priority_lookup = priorities.set_index("manufacturer_key")["priority_index"].to_dict()
    # exact product+batch lookup; if multiple rows exist, retain all evidence in a compact lookup.
    lookup = {}
    for _, row in df.iterrows():
        key = (str(row.get("product", "")).strip().casefold(), str(row.get("batch_no", "")).strip().casefold())
        if key[0] and key[1]:
            lookup.setdefault(key, []).append(row)
    hist_scores, hist_refs, evidence_categories = [], [], []
    for _, scan in flagged.iterrows():
        key = (str(scan["product"]).strip().casefold(), str(scan["batch_no"]).strip().casefold())
        matches = lookup.get(key, [])
        names = sorted(set(str(m.get("manufacturer_name_normalized", "")) for m in matches if str(m.get("manufacturer_name_normalized", ""))))
        hist_scores.append(max([float(priority_lookup.get(n, 0)) for n in names] or [0]))
        hist_refs.append(" | ".join(sorted({str(m.get("build_record_id", "")) for m in matches if str(m.get("build_record_id", ""))})))
        evidence_categories.append(" | ".join(sorted({str(m.get("source_category", "")) for m in matches if str(m.get("source_category", ""))})))
    flagged["historical_priority_index"] = hist_scores
    flagged["historical_record_ids"] = hist_refs
    flagged["matched_source_categories"] = evidence_categories
    flagged["queue_priority"] = (
        flagged["historical_priority_index"].astype(float)
        + flagged["anomaly_flag"].astype(int) * 40
    ).clip(upper=100).round(1)
    flagged["queue_reason"] = flagged.apply(
        lambda r: "; ".join(
            ([str(r["anomaly_reasons"])] if r["anomaly_flag"] else [])
            + ([f"HISTORICAL_PRIORITY_INDEX={r['historical_priority_index']}"] if r["historical_priority_index"] else [])
            + (["REFERENCE_RECORDS=" + str(r["historical_record_ids"])] if r["historical_record_ids"] else [])
        ) or "No configured priority trigger", axis=1
    )
    return flagged.sort_values(["queue_priority", "event_time"], ascending=[False, True]).reset_index(drop=True)
