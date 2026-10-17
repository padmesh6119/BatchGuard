
from pathlib import Path
import json
import pandas as pd


def clean_spurious_sheet(input_path, month, sheet_name="spurious"):
    input_path = Path(input_path)

    df = pd.read_excel(input_path, sheet_name=sheet_name)
    required = {"S.No", "Name of Product", "Batch No", "Manufacturing Dates", "Manufacturer Details", "Remarks"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Spurious sheet missing required headers: {sorted(missing)}")
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    df = df.dropna(how="all")

    records = []
    current = None
    source_rows = []
    excel_rows = []

    def finish_record():
        nonlocal current, source_rows, excel_rows

        if current is None:
            return

        current["source_rows_json"] = json.dumps(
            source_rows,
            ensure_ascii=False,
            default=str,
        )
        records.append(current)
        current["source_excel_rows_json"] = json.dumps(excel_rows)
        current = None
        source_rows = []
        excel_rows = []

    for row_index, row in df.iterrows():
        serial = row.get("S.No")

        # A new serial number begins a new logical record.
        if pd.notna(serial):
            finish_record()

            current = row.to_dict()
            current["nsq_remark"] = pd.NA
            current["firm_reply"] = pd.NA
            current["manufacture_date_raw"] = pd.NA
            current["expiry_date_raw"] = pd.NA
            current["manufacturer_name_raw"] = pd.NA
            current["manufactured_by_raw"] = pd.NA
            current["other_remarks"] = pd.NA

        elif current is None:
            # Orphan continuation row: do not silently attach it.
            raise ValueError(f"Orphan continuation row {row_index + 2} in {input_path.name}; source requires review.")

        # Keep each original source row for traceability.
        source_rows.append({
            str(column): (
                None if pd.isna(value) else str(value)
            )
            for column, value in row.to_dict().items()
        })
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
                current["other_remarks"] = (
                    text if pd.isna(existing)
                    else f"{existing} | {text}"
                )

    finish_record()

    clean = pd.DataFrame(records)

    clean = clean.drop(
        columns=[
            "Remarks",
            "Manufacturing Dates",
            "Manufacturer Details",
        ],
        errors="ignore",
    )

    clean["source_category"] = "spurious"
    clean["source_file"] = input_path.name
    clean["collection_month"] = month

    output = Path("data/processed") / f"{month}_spurious_clean.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(output, index=False, encoding="utf-8-sig")

    print(f"Month: {month}")
    print(f"Input rows: {len(df)}")
    print(f"Consolidated records: {len(clean)}")
    print(f"Saved: {output}")

    return clean


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m src.clean_spurious YYYY-MM"
        )

    month = sys.argv[1]
    clean_spurious_sheet(
        f"data/raw/{month}_all.xlsx",
        month,
    )
