
from pathlib import Path
import re
import pandas as pd

INPUT = Path("data/processed/all_months_analytical.csv")
OUTPUT = Path("data/processed/all_months_failure_normalized.csv")
REVIEW = Path("reports/failure_type_manual_review.csv")

# Broad, explainable keyword rules. These are not clinical classifications.
RULES = [
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


def classify(row):
    category = str(row.get("source_category", "")).strip()
    raw = str(row.get("failure_type", "")).strip()

    if category == "spurious":
        return "not_applicable_spurious", "not_applicable"

    if not raw:
        return "missing_failure_type", "missing"

    matched = [
        name for name, pattern in RULES
        if re.search(pattern, raw, flags=re.IGNORECASE)
    ]

    if matched:
        return ";".join(matched), "keyword_mapped"

    return "other_or_unclassified", "manual_review_required"


def main():
    df = pd.read_csv(INPUT, dtype=str, keep_default_na=False)

    results = df.apply(classify, axis=1, result_type="expand")
    df["failure_categories"] = results[0]
    df["failure_mapping_status"] = results[1]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    review = df[
        df["failure_mapping_status"].isin(
            ["manual_review_required", "missing"]
        )
    ]

    review_cols = [
        "build_record_id", "collection_month", "source_category",
        "product", "batch_no", "failure_type",
        "failure_categories", "failure_mapping_status",
    ]
    review[review_cols].to_csv(
        REVIEW, index=False, encoding="utf-8-sig"
    )

    print("=== Failure Type Normalization ===")
    print(f"Input records: {len(df)}")
    print("\nMapping status:")
    print(df["failure_mapping_status"].value_counts().to_string())
    print("\nNormalized categories (multi-label rows included):")
    print(
        df["failure_categories"].str.split(";").explode()
        .value_counts().to_string()
    )
    print(f"\nNormalized dataset: {OUTPUT}")
    print(f"Manual review report: {REVIEW}")
    print("Original failure_type values were preserved.")
    print("Keyword matches are provisional, not verified classifications.")


if __name__ == "__main__":
    main()
