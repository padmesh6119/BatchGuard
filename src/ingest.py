"""CDSCO monthly workbooks -> validated, hashed CSVs in data/processed/. Nothing is guessed or merged silently."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from src.common import DATA_PROCESSED, DATA_RAW, file_hash

MASTER_COLUMNS = [
    "collection_month", "source_category", "source_file", "revision_status", "release_date",
    "product", "batch_no", "manufacture_date_raw", "manufacture_date_normalized", "manufacture_month",
    "expiry_date_raw", "expiry_date_normalized",
    "manufacturer_raw", "manufacturer_name_raw", "manufactured_by_raw", "manufacturer_state",
    "reporting_source_raw", "reporting_state", "reporting_lab", "reporting_month",
    "failure_type", "nsq_remark", "firm_reply", "other_remarks", "record_status",
    "parse_status", "notes",
]
COLUMN_MAP = {
    "S.No": "serial_no", "Name of Product": "product", "Batch No": "batch_no",
    "Manufacturing Date": "manufacture_date_raw", "Manufacturing Dates": "manufacture_date_raw",
    "Expiry Date": "expiry_date_raw", "Manufactured By": "manufacturer_raw",
    "Manufacturer Details": "manufacturer_details_raw", "NSQ Result": "failure_type",
    "Reporting Source": "reporting_source_raw", "Reporting by Lab/State": "reporting_lab",
    "Reporting Month & Year": "reporting_month",
}
CATEGORY_MAP = {"central": "central_nsq", "state": "state_nsq", "spurious": "spurious"}

# Duplicate pairs verified against the original Excel workbooks; one copy of each is excluded.
CONFIRMED_DUPLICATES = [
    {"month": "2025-07", "category": "central_nsq", "product": "Telmisartan Tablets IP 40 mg", "batch": "TLL-505"},
    {"month": "2025-10", "category": "state_nsq", "product": "Nitrazepam I.P. 10mg tablets(NITRVET 10)", "batch": "AXZ24003P"},
    {"month": "2025-10", "category": "state_nsq", "product": "Paracetamol I.P 500 mg (PARA 500)", "batch": "NBRT-018"},
]

# Broad, explainable keyword rules. These are not clinical classifications.
FAILURE_RULES = [
    ("microbial_contamination", r"microbial|microbiological|total aerobic|bacterial count|fungal"),
    ("sterility", r"\bsterility\b|sterile test"),
    ("dissolution", r"dissolution"),
    ("disintegration", r"disintegration"),
    ("assay", r"\bassay\b|drug content|^content$|content of [a-z]|content\s+(?:of|for)\s+[a-z]"),
    ("description_or_appearance", r"\bdescription\b|appearance|colour|color of"),
    ("identification", r"\bidentification\b|identified as|identity test"),
    ("labeling_or_packing", r"labelling|labeling|packing material|packaging"),
    ("misbranding", r"misbrand"),
    ("pH", r"\bph\b"),
    ("impurity_or_contamination", r"impurit|contaminant|ethylene glycol|diethylene glycol"),
    ("uniformity_or_variation", r"uniformity|weight variation|variation in weight|content uniformity"),
    ("particulate_matter", r"particulate matter|visible particles"),
    ("hardness_or_friability", r"hardness|friability"),
    ("volume_or_fill", r"volume|extractable volume|fill volume"),
    ("bacterial_endotoxins", r"bacterial endotoxin|endotoxin test|\bBET\b"),
    ("loss_on_drying", r"loss on drying"),
    ("weight_per_volume", r"weight per ml|weight per m[lL]|weight per millilitre|weight per milliliter"),
    ("descriptive_part", r"descriptive part"),
    ("storage_compliance", r"storage.*(?:comply|compliance)|(?:comply|compliance).*storage"),
    ("matter_insoluble", r"matter insoluble in alcohol"),
    ("brittleness", r"\bbrittle tablets?\b"),
    ("total_viable_count", r"total viable count"),
    ("label_claim_or_labelling", r"label.*(?:claim|mentioned|printed)|(?:claim|mentioned|printed).*label"),
    ("loss_or_excess_content", r"less than.*limit|more than.*labelled claim|less than.*labelled claim"),
]

DATASETS = ("all_months_analytical.csv", "all_months_manufacturer_normalized.csv",
            "all_months_failure_normalized.csv", "all_months_provenance.csv")
REVIEW_FILES = ("confirmed_duplicate_exclusions.csv", "december_sorbitol_manual_review.csv",
                "all_months_manufacturer_normalization_review.csv", "failure_type_manual_review.csv",
                "all_months_dataset_summary.csv")
PROCESSED, REPORTS = Path("data/processed"), Path("reports")


def ensure_master_columns(df):
    result = df.copy()
    for column in MASTER_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    return result[MASTER_COLUMNS]


def normalize_sheet(df, category, month, filename):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing = {"Name of Product", "Batch No", "Manufactured By", "NSQ Result"} - set(df.columns)
    if missing:
        raise ValueError(f"{filename}/{category} missing required headers: {sorted(missing)}")
    df = df.rename(columns=COLUMN_MAP)
    df["source_category"] = CATEGORY_MAP[category]
    df["source_file"] = filename
    df["collection_month"] = month
    return ensure_master_columns(df.drop(columns=["serial_no"], errors="ignore"))


def clean_spurious_sheet(input_path, month, sheet_name="spurious"):
    """Spurious sheets spread one record over rows; S.No starts a record and prefixes name its fields."""
    input_path = Path(input_path)
    # A batch code is an identifier. Numeric cells mixed with blank continuation
    # rows must not be promoted to floats and acquire a spurious '.0' suffix.
    df = pd.read_excel(input_path, sheet_name=sheet_name, converters={"Batch No": str})
    missing = {"S.No", "Name of Product", "Batch No", "Manufacturing Dates", "Manufacturer Details", "Remarks"} - set(df.columns)
    if missing:
        raise ValueError(f"Spurious sheet missing required headers: {sorted(missing)}")
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")
    records, current, source_rows, excel_rows = [], None, [], []

    def finish_record():
        nonlocal current, source_rows, excel_rows
        if current is None:
            return
        current["source_rows_json"] = json.dumps(source_rows, ensure_ascii=False, default=str)
        records.append(current)
        current["source_excel_rows_json"] = json.dumps(excel_rows)
        current, source_rows, excel_rows = None, [], []

    for row_index, row in df.iterrows():
        if pd.notna(row.get("S.No")):
            finish_record()
            current = row.to_dict()
            for name in ("nsq_remark", "firm_reply", "manufacture_date_raw", "expiry_date_raw",
                         "manufacturer_name_raw", "manufactured_by_raw", "other_remarks"):
                current[name] = pd.NA
        elif current is None:
            raise ValueError(f"Orphan continuation row {row_index + 2} in {input_path.name}; source requires review.")
        source_rows.append({str(column): None if pd.isna(value) else str(value) for column, value in row.to_dict().items()})
        excel_rows.append(int(row_index)+2)
        date_text = row.get("Manufacturing Dates")
        if pd.notna(date_text):
            text = str(date_text).strip()
            if text.startswith("Manufacturing Date:"):
                current["manufacture_date_raw"] = text
            elif text.startswith("Expiry Date:"):
                current["expiry_date_raw"] = text
        manufacturer_text = row.get("Manufacturer Details")
        if pd.notna(manufacturer_text):
            text = str(manufacturer_text).strip()
            if text.startswith("Manufacturer Name:"):
                current["manufacturer_name_raw"] = text
            elif text.startswith("Manufactured By:"):
                current["manufactured_by_raw"] = text
        remarks = row.get("Remarks")
        if pd.notna(remarks):
            text = str(remarks).strip()
            if text.startswith("NSQ Remark:"):
                current["nsq_remark"] = text
            elif text.startswith("Firm Reply:"):
                current["firm_reply"] = text
            else:
                existing = current.get("other_remarks", pd.NA)
                current["other_remarks"] = text if pd.isna(existing) else f"{existing} | {text}"
    finish_record()
    clean = pd.DataFrame(records).drop(columns=["Remarks", "Manufacturing Dates", "Manufacturer Details"], errors="ignore")
    clean["source_category"] = "spurious"
    clean["source_file"] = input_path.name
    clean["collection_month"] = month
    PROCESSED.mkdir(parents=True, exist_ok=True)
    clean.to_csv(PROCESSED / f"{month}_spurious_clean.csv", index=False, encoding="utf-8-sig")
    return clean


def process_month(month):
    """Central and state sheets are required; an absent spurious sheet means unavailable data, not zero cases."""
    workbook_path = Path("data/raw") / f"{month}_all.xlsx"
    with pd.ExcelFile(workbook_path) as excel:
        sheet_names = excel.sheet_names
    sheet_lookup = {str(name).strip().lower(): name for name in sheet_names}
    missing_required = {"central", "state"} - set(sheet_lookup)
    if missing_required:
        raise ValueError(f"Missing required sheets in {workbook_path.name}: {sorted(missing_required)}. Available: {sheet_names}")
    spurious_sheet_present = "spurious" in sheet_lookup
    central_raw = pd.read_excel(workbook_path, sheet_name=sheet_lookup["central"], converters={"Batch No": str})
    state_raw = pd.read_excel(workbook_path, sheet_name=sheet_lookup["state"], converters={"Batch No": str})
    provenance_rows = []
    for category, raw in [("central", central_raw), ("state", state_raw)]:
        for index, row in raw.iterrows():
            serial = row.get("S.No")
            provenance_rows.append({"source_file": workbook_path.name, "source_sheet": sheet_lookup[category],
                                    "source_excel_rows_json": json.dumps([int(index)+2]),
                                    "source_serial": "" if pd.isna(serial) else str(serial)})
    central = normalize_sheet(central_raw, "central", month, workbook_path.name)
    state = normalize_sheet(state_raw, "state", month, workbook_path.name)
    if spurious_sheet_present:
        spurious = clean_spurious_sheet(workbook_path, month, sheet_name=sheet_lookup["spurious"])
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
        spurious = ensure_master_columns(pd.DataFrame(columns=MASTER_COLUMNS))
        spurious["source_category"] = CATEGORY_MAP["spurious"]
        spurious["source_file"] = workbook_path.name
        spurious["collection_month"] = month
        PROCESSED.mkdir(parents=True, exist_ok=True)
        spurious.to_csv(PROCESSED / f"{month}_spurious_clean.csv", index=False, encoding="utf-8-sig")
    master = pd.concat([central, state, spurious], ignore_index=True)
    master["record_status"] = master["source_category"].map(
        {"central_nsq": "reported_nsq", "state_nsq": "reported_nsq", "spurious": "reported_spurious_allegation"})
    missing_identity = (master["product"].fillna("").astype(str).str.strip().eq("")
                        | master["batch_no"].fillna("").astype(str).str.strip().eq(""))
    master["parse_status"] = missing_identity.map({True: "review_required_missing_product_or_batch",
                                                   False: "required_identity_present"})
    PROCESSED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    if len(provenance_rows) != len(master):
        raise ValueError("Source provenance row count differs from master records.")
    provenance = pd.DataFrame(provenance_rows)
    provenance.insert(0, "build_record_id", [f"{month}:{i+1:04d}" for i in range(len(master))])
    provenance.to_csv(PROCESSED / f"{month}_provenance.csv", index=False, encoding="utf-8-sig")
    review = master.loc[missing_identity, ["collection_month", "source_category", "product", "batch_no", "parse_status"]].copy()
    review.insert(0, "build_record_id", provenance.loc[missing_identity.to_numpy(), "build_record_id"].to_numpy())
    review.to_csv(REPORTS / f"{month}_parse_review.csv", index=False, encoding="utf-8-sig")
    master.to_csv(PROCESSED / f"{month}_master.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"month": month, "workbook": workbook_path.name, "central_sheet_present": True,
                   "state_sheet_present": True, "spurious_sheet_present": spurious_sheet_present,
                   "spurious_data_status": "available" if spurious_sheet_present else "source_sheet_missing",
                   "spurious_record_count": len(spurious)}]).to_csv(
        REPORTS / f"{month}_source_availability.csv", index=False, encoding="utf-8-sig")
    if list(master.columns) != MASTER_COLUMNS:
        raise ValueError("Master schema mismatch.")


def find_monthly_masters():
    pattern = re.compile(r"^\d{4}-\d{2}_master\.csv$")
    files = sorted(path for path in PROCESSED.glob("*_master.csv") if pattern.fullmatch(path.name))
    if not files:
        raise FileNotFoundError(f"No monthly master CSV files found in {PROCESSED}")
    frames, months = [], []
    for path in files:
        month = path.name.removesuffix("_master.csv")
        pd.Period(month, freq="M")
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        missing = set(MASTER_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        df = df[MASTER_COLUMNS].copy()
        df.insert(0, "build_record_id", [f"{month}:{i + 1:04d}" for i in range(len(df))])
        frames.append(df)
        months.append(month)
    return months, pd.concat(frames, ignore_index=True)


def select_confirmed_duplicates(combined):
    """Validate exact pairs before excluding one copy from analysis."""
    exclusions, excluded_ids = [], set()
    for rule in CONFIRMED_DUPLICATES:
        if rule["month"] not in set(combined["collection_month"]):
            continue
        mask = (combined["collection_month"].eq(rule["month"]) & combined["source_category"].eq(rule["category"])
                & combined["product"].str.strip().eq(rule["product"]) & combined["batch_no"].str.strip().eq(rule["batch"]))
        candidates = combined.loc[mask].copy()
        if len(candidates) != 2:
            raise ValueError(f"Duplicate verification failed for {rule['month']} | {rule['product']} | {rule['batch']}: "
                             f"expected 2 rows, found {len(candidates)}. Review the source records.")
        if not candidates.iloc[0][MASTER_COLUMNS].equals(candidates.iloc[1][MASTER_COLUMNS]):
            raise ValueError(f"Candidate rows differ across canonical columns: {rule['month']} | {rule['product']} | {rule['batch']}.")
        retained_id, excluded_id = candidates.iloc[0]["build_record_id"], candidates.iloc[1]["build_record_id"]
        if excluded_id in excluded_ids:
            raise ValueError(f"Record {excluded_id} was selected for exclusion twice.")
        excluded_ids.add(excluded_id)
        exclusions.append({"collection_month": rule["month"], "source_category": rule["category"],
                           "product": rule["product"], "batch_no": rule["batch"],
                           "retained_record_id": retained_id, "excluded_record_id": excluded_id,
                           "reason": "Exact match across all canonical master columns; verified against original workbook"})
    audit = pd.DataFrame(exclusions, columns=["collection_month", "source_category", "product", "batch_no",
                                              "retained_record_id", "excluded_record_id", "reason"])
    return combined[~combined["build_record_id"].isin(excluded_ids)].copy(), audit


def create_manual_review_report(combined):
    """Keep both December Sorbitol records pending source verification."""
    if "2025-12" not in set(combined["collection_month"]):
        review = combined.iloc[:0].copy()
        review.insert(1, "review_reason", "")
        return review
    mask = (combined["collection_month"].eq("2025-12") & combined["source_category"].eq("central_nsq")
            & combined["product"].str.strip().eq("Sorbitol Solution 70% IP (Non-Crystallizing)")
            & combined["batch_no"].str.strip().eq("KA/017"))
    review = combined.loc[mask].copy()
    if len(review) != 2:
        raise ValueError(f"Expected 2 December Sorbitol records for manual review; found {len(review)}.")
    review.insert(1, "review_reason", "Expiry dates differ; verify against authoritative source")
    return review


def build_dataset():
    months, combined = find_monthly_masters()
    provenance_files = [PROCESSED / f"{month}_provenance.csv" for month in months]
    if all(path.exists() for path in provenance_files):
        provenance = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in provenance_files], ignore_index=True)
        if provenance["build_record_id"].duplicated().any() or set(provenance["build_record_id"]) != set(combined["build_record_id"]):
            raise ValueError("Source provenance does not match the combined master.")
        provenance.to_csv(PROCESSED / "all_months_provenance.csv", index=False, encoding="utf-8-sig")
    analytical, duplicate_audit = select_confirmed_duplicates(combined)
    december_review = create_manual_review_report(combined)
    expected = sum(rule["month"] in months for rule in CONFIRMED_DUPLICATES)
    if len(duplicate_audit) != expected or len(analytical) != len(combined) - expected:
        raise ValueError("Duplicate exclusion count validation failed.")
    columns = ["build_record_id"] + MASTER_COLUMNS
    combined[columns].to_csv(PROCESSED / "all_months_combined_master.csv", index=False, encoding="utf-8-sig")
    analytical[columns].to_csv(PROCESSED / "all_months_analytical.csv", index=False, encoding="utf-8-sig")
    duplicate_audit.to_csv(REPORTS / "confirmed_duplicate_exclusions.csv", index=False, encoding="utf-8-sig")
    december_review.to_csv(REPORTS / "december_sorbitol_manual_review.csv", index=False, encoding="utf-8-sig")
    analytical.groupby(["collection_month", "source_category"], dropna=False).size().reset_index(
        name="record_count").to_csv(REPORTS / "all_months_dataset_summary.csv", index=False, encoding="utf-8-sig")


def clean_source_value(value):
    """Remove field labels and normalize whitespace only."""
    if pd.isna(value):
        return ""
    text = re.sub(r"(?i)^(manufacturer name|manufactured by|manufacturer details)\s*:\s*", "", str(value).strip())
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.upper() in {"", "N/A", "NA", "NAN", "NONE", "UNDER INVESTIGATION"} else text


def normalize_name(value):
    """Uppercase and standardize punctuation/spacing; addresses and legal suffixes are kept."""
    text = clean_source_value(value)
    if not text:
        return ""
    text = re.sub(r"[.,;:()]", " ", text.upper().replace("&", " AND "))
    return re.sub(r"\s+", " ", text).strip()


def normalize_manufacturers():
    df = pd.read_csv(PROCESSED / "all_months_analytical.csv", dtype=str, keep_default_na=False)

    def choose_source(row):
        for column in ["manufacturer_raw", "manufacturer_name_raw", "manufactured_by_raw"]:
            cleaned = clean_source_value(row.get(column, ""))
            if cleaned:
                return cleaned, column
        return "", "missing_or_unavailable"

    chosen = df.apply(choose_source, axis=1, result_type="expand")
    df["manufacturer_text_for_review"] = chosen[0]
    df["manufacturer_field_used"] = chosen[1]
    df["manufacturer_name_normalized"] = df["manufacturer_text_for_review"].map(normalize_name)
    df["manufacturer_identity_status"] = df["manufacturer_name_normalized"].map(
        lambda value: "needs_manual_review" if value else "unavailable_or_under_investigation")
    review_rows = []
    for normalized, group in df[df["manufacturer_name_normalized"] != ""].groupby("manufacturer_name_normalized"):
        raw_values = sorted(set(group["manufacturer_text_for_review"]))
        if len(raw_values) > 1:
            review_rows.append({"manufacturer_name_normalized": normalized, "distinct_raw_values": len(raw_values),
                                "raw_values": " || ".join(raw_values), "record_count": len(group),
                                "review_reason": "Different raw strings share a normalized form; verify company and manufacturing-unit identity."})
    df.to_csv(PROCESSED / "all_months_manufacturer_normalized.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(review_rows, columns=["manufacturer_name_normalized", "distinct_raw_values", "raw_values",
                                       "record_count", "review_reason"]).to_csv(
        REPORTS / "all_months_manufacturer_normalization_review.csv", index=False, encoding="utf-8-sig")


def classify_failure(row):
    category, raw = str(row.get("source_category", "")).strip(), str(row.get("failure_type", "")).strip()
    if category == "spurious":
        return "not_applicable_spurious", "not_applicable"
    if not raw:
        return "missing_failure_type", "missing"
    matched = [name for name, pattern in FAILURE_RULES if re.search(pattern, raw, flags=re.IGNORECASE)]
    return (";".join(matched), "keyword_mapped") if matched else ("other_or_unclassified", "manual_review_required")


def normalize_failure_types():
    df = pd.read_csv(PROCESSED / "all_months_analytical.csv", dtype=str, keep_default_na=False)
    results = df.apply(classify_failure, axis=1, result_type="expand")
    df["failure_categories"], df["failure_mapping_status"] = results[0], results[1]
    df.to_csv(PROCESSED / "all_months_failure_normalized.csv", index=False, encoding="utf-8-sig")
    review = df[df["failure_mapping_status"].isin(["manual_review_required", "missing"])]
    review[["build_record_id", "collection_month", "source_category", "product", "batch_no", "failure_type",
            "failure_categories", "failure_mapping_status"]].to_csv(
        REPORTS / "failure_type_manual_review.csv", index=False, encoding="utf-8-sig")


def validate_outputs(directory, months):
    frames = [pd.read_csv(directory / name, dtype=str, keep_default_na=False) for name in DATASETS[:3]]
    if len({len(df) for df in frames}) != 1 or frames[0].empty:
        raise ValueError("Analytical and derived outputs must be nonempty and have matching counts.")
    for frame in frames:
        if "build_record_id" not in frame or frame["build_record_id"].duplicated().any():
            raise ValueError("Missing or duplicated record IDs.")
        if set(frame["build_record_id"]) != set(frames[0]["build_record_id"]):
            raise ValueError("Derived output IDs differ from analytical IDs.")
    if set(frames[0]["collection_month"]) != set(months):
        raise ValueError("Output months do not match the workbook list.")
    provenance = pd.read_csv(directory / "all_months_provenance.csv", dtype=str, keep_default_na=False)
    if provenance["build_record_id"].duplicated().any() or not set(frames[0]["build_record_id"]).issubset(set(provenance["build_record_id"])):
        raise ValueError("Analytical records lack unique workbook-row provenance.")
    return {"analytical_records": len(frames[0]), "months": months,
            "categories": frames[0]["source_category"].value_counts().to_dict()}


@contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def build(raw_dir=DATA_RAW, out_dir=DATA_PROCESSED):
    """Build in a clean staging directory; replace out_dir only after every check passes."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    workbooks = sorted(raw_dir.glob("*_all.xlsx"))
    if not workbooks:
        raise FileNotFoundError(f"Place monthly YYYY-MM_all.xlsx workbooks in {raw_dir}.")
    for workbook in workbooks:
        if not re.fullmatch(r"\d{4}-\d{2}_all\.xlsx", workbook.name):
            raise ValueError(f"Invalid monthly filename: {workbook.name}")
        pd.Period(workbook.name[:7], freq="M")
    months = [path.name[:7] for path in workbooks]
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".build-", dir=out_dir.parent))
    try:
        (stage / "data" / "raw").mkdir(parents=True)
        for workbook in workbooks:
            shutil.copy2(workbook, stage / "data" / "raw" / workbook.name)
        with working_directory(stage):
            for month in months:
                process_month(month)
            build_dataset()
            normalize_manufacturers()
            normalize_failure_types()
        summary = validate_outputs(stage / PROCESSED, months)
        publish = stage / "publish"
        (publish / "review").mkdir(parents=True)
        for name in DATASETS:
            shutil.copy2(stage / PROCESSED / name, publish / name)
        for name in REVIEW_FILES:
            shutil.copy2(stage / REPORTS / name, publish / "review" / name)
        for kind in ("source_availability", "parse_review"):
            pd.concat([pd.read_csv(stage / REPORTS / f"{m}_{kind}.csv", dtype=str, keep_default_na=False) for m in months],
                      ignore_index=True).to_csv(publish / "review" / f"{kind}.csv", index=False, encoding="utf-8-sig")
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
                    "sources": {w.name: file_hash(w) for w in workbooks},
                    "builder_sha256": file_hash(Path(__file__)),
                    "outputs": {p.relative_to(publish).as_posix(): file_hash(p) for p in sorted(publish.rglob("*")) if p.is_file()},
                    "limits": ["Local workbook hashes, not verified download origins.",
                               "Manufacturer text is not verified legal identity.",
                               "Collection months stand in for publication dates."]}
        (publish / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        old = out_dir.with_name(f".{out_dir.name}-previous")
        if old.exists():
            shutil.rmtree(old)
        if out_dir.exists():
            out_dir.rename(old)
        publish.rename(out_dir)
        if old.exists():
            shutil.rmtree(old)
        return manifest
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    result = build()
    print(json.dumps(result["summary"], indent=2))
