
"""Canonical data schema for BatchGuard CDSCO records."""

# One row represents one reported drug/batch record.
MASTER_COLUMNS = [
    # Source traceability
    "collection_month",
    "source_category",
    "source_file",
    "revision_status",
    "release_date",

    # Drug and batch details
    "product",
    "batch_no",
    "manufacture_date_raw",
    "manufacture_date_normalized",
    "manufacture_month",
    "expiry_date_raw",
    "expiry_date_normalized",

    # Manufacturer details
    "manufacturer_raw",
    "manufacturer_name_raw",
    "manufactured_by_raw",
    "manufacturer_state",

    # Reporting details
    "reporting_source_raw",
    "reporting_state",
    "reporting_lab",
    "reporting_month",

    # Results and evidence
    "failure_type",
    "nsq_remark",
    "firm_reply",
    "other_remarks",
    "record_status",

    # Data quality
    "parse_status",
    "notes",
]

# Map the different column names used in CDSCO spreadsheets
# into the canonical schema. Preserve original source values
# in the corresponding *_raw fields where applicable.
COLUMN_MAP = {
    "S.No": "serial_no",
    "Name of Product": "product",
    "Batch No": "batch_no",
    "Manufacturing Date": "manufacture_date_raw",
    "Manufacturing Dates": "manufacture_date_raw",
    "Expiry Date": "expiry_date_raw",
    "Manufactured By": "manufacturer_raw",
    "Manufacturer Details": "manufacturer_details_raw",
    "NSQ Result": "failure_type",
    "Reporting Source": "reporting_source_raw",
    "Reporting by Lab/State": "reporting_lab",
    "Reporting Month & Year": "reporting_month",
}

CATEGORY_MAP = {
    "central": "central_nsq",
    "state": "state_nsq",
    "spurious": "spurious",
}


def ensure_master_columns(df):
    """Add missing canonical columns and return a consistent layout."""
    import pandas as pd

    result = df.copy()

    for column in MASTER_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA

    return result[MASTER_COLUMNS]
