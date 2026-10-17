
from pathlib import Path
import re
import pandas as pd

from src.schema import MASTER_COLUMNS

PROCESSED_DIR = Path("data/processed")
REPORT_DIR = Path("reports")

# Duplicate pairs verified against the original Excel workbooks.
# One copy of each pair will be excluded from the analytical dataset.
CONFIRMED_DUPLICATES = [
    {
        "month": "2025-07",
        "category": "central_nsq",
        "product": "Telmisartan Tablets IP 40 mg",
        "batch": "TLL-505",
    },
    {
        "month": "2025-10",
        "category": "state_nsq",
        "product": "Nitrazepam I.P. 10mg tablets(NITRVET 10)",
        "batch": "AXZ24003P",
    },
    {
        "month": "2025-10",
        "category": "state_nsq",
        "product": "Paracetamol I.P 500 mg (PARA 500)",
        "batch": "NBRT-018",
    },
]


def find_monthly_masters():
    """Load only YYYY-MM_master.csv files, never combined outputs."""
    pattern = re.compile(r"^\d{4}-\d{2}_master\.csv$")

    files = sorted(
        path
        for path in PROCESSED_DIR.glob("*_master.csv")
        if pattern.fullmatch(path.name)
    )

    if not files:
        raise FileNotFoundError(
            f"No monthly master CSV files found in {PROCESSED_DIR}"
        )

    frames = []
    months = []

    for path in files:
        month = path.name.removesuffix("_master.csv")

        try:
            pd.Period(month, freq="M")
        except ValueError:
            raise ValueError(
                f"Invalid month in master filename: {path.name}"
            )

        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
        )

        missing = set(MASTER_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"{path.name} is missing columns: {sorted(missing)}"
            )

        # Preserve the canonical schema and its original order.
        df = df[MASTER_COLUMNS].copy()

        # Stable within this build; used to trace exclusions.
        df.insert(
            0,
            "build_record_id",
            [f"{month}:{i + 1:04d}" for i in range(len(df))],
        )

        frames.append(df)
        months.append(month)

    combined = pd.concat(frames, ignore_index=True)

    # Prevent duplicate monthly inputs or duplicated collection months.
    if len(months) != len(set(months)):
        raise ValueError(
            "More than one master file was discovered for a month."
        )

    return months, combined


def select_confirmed_duplicates(combined):
    """Validate exact pairs before excluding one copy from analysis."""
    exclusions = []
    excluded_ids = set()

    for rule in CONFIRMED_DUPLICATES:
        if rule["month"] not in set(combined["collection_month"]):
            continue
        mask = (
            combined["collection_month"].eq(rule["month"])
            & combined["source_category"].eq(rule["category"])
            & combined["product"].str.strip().eq(rule["product"])
            & combined["batch_no"].str.strip().eq(rule["batch"])
        )

        candidates = combined.loc[mask].copy()

        if len(candidates) != 2:
            raise ValueError(
                "Duplicate verification failed for "
                f"{rule['month']} | {rule['product']} | "
                f"{rule['batch']}: expected 2 rows, found "
                f"{len(candidates)}. No dataset was written. "
                "Review the source records before proceeding."
            )

        # Compare all canonical columns, not the generated row IDs.
        first = candidates.iloc[0][MASTER_COLUMNS]
        second = candidates.iloc[1][MASTER_COLUMNS]

        if not first.equals(second):
            raise ValueError(
                "Candidate rows differ across canonical columns: "
                f"{rule['month']} | {rule['product']} | "
                f"{rule['batch']}. Review manually; no dataset "
                "was written."
            )

        retained_id = candidates.iloc[0]["build_record_id"]
        excluded_id = candidates.iloc[1]["build_record_id"]

        if excluded_id in excluded_ids:
            raise ValueError(
                f"Record {excluded_id} was selected for exclusion twice."
            )

        excluded_ids.add(excluded_id)

        exclusions.append({
            "collection_month": rule["month"],
            "source_category": rule["category"],
            "product": rule["product"],
            "batch_no": rule["batch"],
            "retained_record_id": retained_id,
            "excluded_record_id": excluded_id,
            "reason": (
                "Exact match across all canonical master columns; "
                "verified against original workbook"
            ),
        })

    analytical = combined[
        ~combined["build_record_id"].isin(excluded_ids)
    ].copy()

    audit = pd.DataFrame(
        exclusions,
        columns=[
            "collection_month",
            "source_category",
            "product",
            "batch_no",
            "retained_record_id",
            "excluded_record_id",
            "reason",
        ],
    )

    return analytical, audit


def create_manual_review_report(combined):
    """Keep both December Sorbitol records pending source verification."""
    if "2025-12" not in set(combined["collection_month"]):
        review = combined.iloc[:0].copy()
        review.insert(1, "review_reason", "")
        return review
    mask = (
        combined["collection_month"].eq("2025-12")
        & combined["source_category"].eq("central_nsq")
        & combined["product"].str.strip().eq(
            "Sorbitol Solution 70% IP (Non-Crystallizing)"
        )
        & combined["batch_no"].str.strip().eq("KA/017")
    )

    review = combined.loc[mask].copy()

    if len(review) != 2:
        raise ValueError(
            "Expected 2 December Sorbitol records for manual review; "
            f"found {len(review)}. Verify the December master."
        )

    review.insert(
        1,
        "review_reason",
        "Expiry dates differ; verify against authoritative source",
    )

    return review


def build_dataset():
    months, combined = find_monthly_masters()
    provenance_files = [PROCESSED_DIR / f"{month}_provenance.csv" for month in months]
    if all(path.exists() for path in provenance_files):
        provenance = pd.concat([pd.read_csv(path, dtype=str, keep_default_na=False) for path in provenance_files], ignore_index=True)
        if provenance["build_record_id"].duplicated().any() or set(provenance["build_record_id"]) != set(combined["build_record_id"]):
            raise ValueError("Source provenance does not match the combined master.")
        provenance.to_csv(PROCESSED_DIR / "all_months_provenance.csv", index=False, encoding="utf-8-sig")

    print("Monthly master files discovered:")
    for month in months:
        print(f"  {month}_master.csv")

    analytical, duplicate_audit = select_confirmed_duplicates(combined)
    december_review = create_manual_review_report(combined)

    # Check expected exclusions before writing any output.
    expected_exclusions = sum(rule["month"] in months for rule in CONFIRMED_DUPLICATES)
    if len(duplicate_audit) != expected_exclusions:
        raise ValueError(
            f"Expected {expected_exclusions} duplicate exclusions, got {len(duplicate_audit)}"
        )

    if len(analytical) != len(combined) - expected_exclusions:
        raise ValueError("Analytical record count validation failed.")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    combined_path = (
        PROCESSED_DIR / "all_months_combined_master.csv"
    )
    analytical_path = (
        PROCESSED_DIR / "all_months_analytical.csv"
    )
    duplicate_path = (
        REPORT_DIR / "confirmed_duplicate_exclusions.csv"
    )
    review_path = (
        REPORT_DIR / "december_sorbitol_manual_review.csv"
    )
    summary_path = (
        REPORT_DIR / "all_months_dataset_summary.csv"
    )

    # Keep generated IDs for traceability.
    # Canonical data columns remain unchanged.
    output_columns = ["build_record_id"] + MASTER_COLUMNS

    combined[output_columns].to_csv(
        combined_path,
        index=False,
        encoding="utf-8-sig",
    )

    analytical[output_columns].to_csv(
        analytical_path,
        index=False,
        encoding="utf-8-sig",
    )

    duplicate_audit.to_csv(
        duplicate_path,
        index=False,
        encoding="utf-8-sig",
    )

    december_review.to_csv(
        review_path,
        index=False,
        encoding="utf-8-sig",
    )

    summary = (
        analytical.groupby(
            ["collection_month", "source_category"],
            dropna=False,
        )
        .size()
        .reset_index(name="record_count")
    )

    summary.to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig",
    )

    print("\n=== BatchGuard Dataset Build ===")
    print(f"Months included: {len(months)}")
    print(f"Month range: {months[0]} to {months[-1]}")
    print(f"Combined master records: {len(combined)}")
    print(f"Analytical records: {len(analytical)}")
    print(f"Duplicate copies excluded: {len(duplicate_audit)}")
    print(f"December records retained for review: {len(december_review)}")

    print("\nAnalytical counts:")
    print(summary.to_string(index=False))

    print(f"\nCombined master: {combined_path}")
    print(f"Analytical dataset: {analytical_path}")
    print(f"Duplicate audit: {duplicate_path}")
    print(f"Manual review: {review_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    build_dataset()
