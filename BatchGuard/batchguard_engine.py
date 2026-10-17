from __future__ import annotations

from pathlib import Path

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
