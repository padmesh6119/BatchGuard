
from pathlib import Path
import argparse
import json
import pandas as pd

from src.schema import (
    MASTER_COLUMNS,
    COLUMN_MAP,
    CATEGORY_MAP,
    ensure_master_columns,
)
from src.clean_spurious import clean_spurious_sheet

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")


def normalize_sheet(df, category, month, filename):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    required = {"Name of Product", "Batch No", "Manufactured By", "NSQ Result"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{filename}/{category} missing required headers: {sorted(missing)}")

    # Rename source columns to canonical names.
    df = df.rename(columns=COLUMN_MAP)

    df["source_category"] = CATEGORY_MAP[category]
    df["source_file"] = filename
    df["collection_month"] = month

    # Preserve an existing serial number in the raw data only
    # if needed later for traceability.
    df = df.drop(columns=["serial_no"], errors="ignore")

    # Standardize to the canonical 27-column schema.
    return ensure_master_columns(df)


def process_month(month):
    workbook_path = RAW_DIR / f"{month}_all.xlsx"

    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    with pd.ExcelFile(workbook_path) as excel:
        sheet_names = excel.sheet_names
    # Resolve sheet names case-insensitively so "Spurious" and "spurious"
    # are treated consistently. Central and state NSQ sheets are required;
    # the spurious sheet may be absent in a month workbook.
    sheet_lookup = {str(name).strip().lower(): name for name in sheet_names}
    missing_required = {"central", "state"} - set(sheet_lookup)
    if missing_required:
        raise ValueError(
            f"Missing required sheets in {workbook_path.name}: "
            f"{sorted(missing_required)}. Available sheets: {sheet_names}"
        )
    spurious_sheet_present = "spurious" in sheet_lookup

    print(f"\n=== BATCHGUARD: {month} ===")
    if not spurious_sheet_present:
        print(
            "WARNING: No spurious sheet in this workbook. This means "
            "spurious data is unavailable for this month, not that there "
            "were zero spurious cases."
        )

    central_raw = pd.read_excel(workbook_path, sheet_name=sheet_lookup["central"])
    state_raw = pd.read_excel(workbook_path, sheet_name=sheet_lookup["state"])
    provenance_rows = []
    for category, raw in [("central", central_raw), ("state", state_raw)]:
        for index, row in raw.iterrows():
            serial = row.get("S.No")
            provenance_rows.append({"source_file": workbook_path.name, "source_sheet": sheet_lookup[category],
                                    "source_excel_rows_json": json.dumps([int(index)+2]),
                                    "source_serial": "" if pd.isna(serial) else str(serial)})
    central = normalize_sheet(
        central_raw,
        "central", month, workbook_path.name
    )
    state = normalize_sheet(
        state_raw,
        "state", month, workbook_path.name
    )

    if spurious_sheet_present:
        spurious = clean_spurious_sheet(
            workbook_path, month, sheet_name=sheet_lookup["spurious"]
        )
        for _, row in spurious.iterrows():
            serial = row.get("S.No")
            provenance_rows.append({"source_file": workbook_path.name, "source_sheet": sheet_lookup["spurious"],
                                    "source_excel_rows_json": row["source_excel_rows_json"],
                                    "source_serial": "" if pd.isna(serial) else str(serial)})
        spurious = spurious.rename(columns=COLUMN_MAP)
        spurious["source_category"] = CATEGORY_MAP["spurious"]
        spurious["source_file"] = workbook_path.name
        spurious["collection_month"] = month
        spurious = ensure_master_columns(spurious)
    else:
        # Empty category with canonical schema. A separate availability report
        # records that the source sheet was absent, so this is not interpreted
        # as evidence that there were no spurious reports.
        spurious = ensure_master_columns(pd.DataFrame(columns=MASTER_COLUMNS))
        spurious["source_category"] = CATEGORY_MAP["spurious"]
        spurious["source_file"] = workbook_path.name
        spurious["collection_month"] = month
        empty_path = PROCESSED_DIR / f"{month}_spurious_clean.csv"
        empty_path.parent.mkdir(parents=True, exist_ok=True)
        spurious.to_csv(empty_path, index=False, encoding="utf-8-sig")
        print(f"Saved empty placeholder: {empty_path} (source sheet unavailable)")

    master = pd.concat(
        [central, state, spurious],
        ignore_index=True,
    )
    master["record_status"] = master["source_category"].map(
        {"central_nsq": "reported_nsq", "state_nsq": "reported_nsq", "spurious": "reported_spurious_allegation"})
    missing_identity = master["product"].fillna("").astype(str).str.strip().eq("") | master["batch_no"].fillna("").astype(str).str.strip().eq("")
    master["parse_status"] = missing_identity.map({True: "review_required_missing_product_or_batch", False: "required_identity_present"})

    # This is an intermediate output. Do not automatically deduplicate.
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if len(provenance_rows) != len(master):
        raise ValueError("Source provenance row count differs from master records.")
    provenance = pd.DataFrame(provenance_rows)
    provenance.insert(0, "build_record_id", [f"{month}:{i+1:04d}" for i in range(len(master))])
    provenance.to_csv(PROCESSED_DIR / f"{month}_provenance.csv", index=False, encoding="utf-8-sig")
    review = master.loc[missing_identity, ["collection_month", "source_category", "product", "batch_no", "parse_status"]].copy()
    review.insert(0, "build_record_id", provenance.loc[missing_identity.to_numpy(), "build_record_id"].to_numpy())
    review.to_csv(REPORT_DIR / f"{month}_parse_review.csv", index=False, encoding="utf-8-sig")

    output = PROCESSED_DIR / f"{month}_master.csv"
    master.to_csv(output, index=False, encoding="utf-8-sig")

    summary = (
        master.groupby("source_category")
        .size()
        .rename("record_count")
        .reset_index()
    )
    summary.insert(0, "month", month)

    report = REPORT_DIR / f"{month}_processing_summary.csv"
    summary.to_csv(report, index=False)

    availability = pd.DataFrame([{
        "month": month,
        "workbook": workbook_path.name,
        "central_sheet_present": True,
        "state_sheet_present": True,
        "spurious_sheet_present": spurious_sheet_present,
        "spurious_data_status": (
            "available" if spurious_sheet_present else "source_sheet_missing"
        ),
        "spurious_record_count": len(spurious),
    }])
    availability.to_csv(
        REPORT_DIR / f"{month}_source_availability.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print(f"Total records: {len(master)}")
    print(summary.to_string(index=False))
    print(f"Master CSV: {output}")
    print(f"Columns: {len(master.columns)}")

    assert list(master.columns) == MASTER_COLUMNS
    print("Schema validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("month", help="Month in YYYY-MM format")
    args = parser.parse_args()

    try:
        pd.Period(args.month, freq="M")
    except Exception:
        parser.error("Month must be in YYYY-MM format, e.g. 2025-08")

    process_month(args.month)
