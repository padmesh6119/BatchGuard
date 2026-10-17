
from pathlib import Path
import re
import pandas as pd


INPUT = Path(
    "data/processed/all_months_analytical.csv"
)
OUTPUT = Path(
    "data/processed/all_months_manufacturer_normalized.csv"
)
REVIEW_OUTPUT = Path(
    "reports/all_months_manufacturer_normalization_review.csv"
)


def clean_source_value(value):
    """Remove field labels and normalize whitespace only."""
    if pd.isna(value):
        return ""

    text = str(value).strip()

    text = re.sub(
        r"(?i)^(manufacturer name|manufactured by|manufacturer details)\s*:\s*",
        "",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()

    if text.upper() in {
        "", "N/A", "NA", "NAN", "NONE", "UNDER INVESTIGATION"
    }:
        return ""

    return text


def normalize_name(value):
    """
    Conservative normalization:
    uppercase and standardize punctuation/spacing.
    Do not remove addresses or legal suffixes automatically.
    """
    text = clean_source_value(value)

    if not text:
        return ""

    text = text.upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[.,;:()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def main():
    df = pd.read_csv(INPUT, dtype=str, keep_default_na=False)

    def choose_source(row):
        # Prefer the main source field when available.
        # For spurious records, fall back to the separate fields.
        for column in [
            "manufacturer_raw",
            "manufacturer_name_raw",
            "manufactured_by_raw",
        ]:
            cleaned = clean_source_value(row.get(column, ""))
            if cleaned:
                return cleaned, column

        return "", "missing_or_unavailable"

    chosen = df.apply(choose_source, axis=1, result_type="expand")
    df["manufacturer_text_for_review"] = chosen[0]
    df["manufacturer_field_used"] = chosen[1]
    df["manufacturer_name_normalized"] = (
        df["manufacturer_text_for_review"].map(normalize_name)
    )

    df["manufacturer_identity_status"] = df[
        "manufacturer_name_normalized"
    ].map(
        lambda value: (
            "needs_manual_review"
            if value
            else "unavailable_or_under_investigation"
        )
    )

    # Report normalized names that occur with multiple distinct raw strings.
    review_rows = []

    valid = df[df["manufacturer_name_normalized"] != ""]

    for normalized, group in valid.groupby(
        "manufacturer_name_normalized"
    ):
        raw_values = sorted(
            set(group["manufacturer_text_for_review"])
        )

        if len(raw_values) > 1:
            review_rows.append({
                "manufacturer_name_normalized": normalized,
                "distinct_raw_values": len(raw_values),
                "raw_values": " || ".join(raw_values),
                "record_count": len(group),
                "review_reason": (
                    "Different raw strings share a normalized form; "
                    "verify company and manufacturing-unit identity."
                ),
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        review_rows,
        columns=[
            "manufacturer_name_normalized",
            "distinct_raw_values",
            "raw_values",
            "record_count",
            "review_reason",
        ],
    ).to_csv(REVIEW_OUTPUT, index=False, encoding="utf-8-sig")

    print("=== Manufacturer Normalization ===")
    print(f"Input records: {len(df)}")
    print(
        "Records with usable manufacturer text: "
        f"{int(df['manufacturer_name_normalized'].ne('').sum())}"
    )
    print(
        "Records without usable manufacturer text: "
        f"{int(df['manufacturer_name_normalized'].eq('').sum())}"
    )
    print(
        "Distinct normalized manufacturer strings: "
        f"{df['manufacturer_name_normalized'].replace('', pd.NA).nunique()}"
    )
    print(f"\nNormalized dataset: {OUTPUT}")
    print(f"Review report: {REVIEW_OUTPUT}")
    print(
        "\nNo records were merged or deleted. "
        "Normalized strings are not verified legal identities."
    )


if __name__ == "__main__":
    main()
