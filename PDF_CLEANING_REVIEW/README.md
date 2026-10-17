# BatchGuard PDF Cleaning Review (September 2024 – June 2025)

## 1. Overview and Status
This directory contains review-ready staged Excel workbooks and audit evidence converted from 32 historical CDSCO quality alert PDFs covering September 2024 through June 2025 (10 central reports, 10 state reports, 8 standalone spurious reports, and 4 revision documents).

> **IMPORTANT NOTICE:** These staged Excel workbooks and evidence outputs are strictly staged for human review. They are **NOT** integrated into the live active dataset (`BatchGuard/data/raw/` or `data/processed/`), have **NOT** been run through `refresh_data.py`, and are **NOT** model-ready.

---

## 2. Directory Structure

```
PDF_CLEANING_REVIEW/
├── workbooks/
│   ├── 2024-09_all.xlsx
│   ├── 2024-10_all.xlsx
│   ├── 2024-11_all.xlsx
│   ├── 2024-12_all.xlsx
│   ├── 2025-01_all.xlsx
│   ├── 2025-02_all.xlsx
│   ├── 2025-03_all.xlsx
│   ├── 2025-04_all.xlsx
│   ├── 2025-05_all.xlsx
│   └── 2025-06_all.xlsx
├── evidence/
│   ├── record_provenance.jsonl
│   └── revision_records.xlsx
├── reports/
│   ├── source_manifest.csv
│   ├── extraction_summary.csv
│   ├── manual_review.csv
│   ├── duplicate_candidates.csv
│   ├── source_availability.csv
│   └── revision_links.csv
├── tools/
│   ├── extract_all.py
│   ├── generate_reports.py
│   └── validate_outputs.py
└── README.md
```

---

## 3. Extraction Methodology and Tools Used

- **Extraction Engine:** Deterministic extraction using `pdfplumber` and `openpyxl`.
- **Text & Bounding Analysis:** Table boundary analysis with row and multi-column reconstruction.
- **Record Stitching:** Reconstructed wrapped cells and multi-page records across page boundaries without splitting logical entries.
- **Exact Formats & Headers:**
  - `central` sheet: `S.No`, `Name of Product`, `Batch No`, `Manufacturing Date`, `Expiry Date`, `Manufactured By`, `NSQ Result`, `Reporting Source` (`CDSCO Labs`), `Reporting by Lab/State`, `Reporting Month & Year` (`YYYY-MM`).
  - `state` sheet: `S.No`, `Name of Product`, `Batch No`, `Manufacturing Date`, `Expiry Date`, `Manufactured By`, `NSQ Result`, `Reporting Source` (`State Lab`), `Reporting by Lab/State`, `Reporting Month & Year` (`YYYY-MM`).
  - `spurious` sheet: Present only when standalone spurious PDF exists (8 months: Sep 2024–Nov 2024, Feb 2025–Jun 2025; absent in Dec 2024 and Jan 2025). Formatted using the parser-compatible two-row logical record structure with `Manufacturing Date:`, `Expiry Date:`, `Manufactured By:`, `NSQ Remark:`, and `Firm Reply:` prefixes.
- **Data Types:** All batch numbers stored with explicit string type (`@`) to prevent scientific notation or date conversion.

---

## 4. Record Counts by Month and Category

| Month | Central NSQ Records | State NSQ Records | Spurious Logical Records | Spurious Workbook Rows | Total Workbook Rows |
|---|---:|---:|---:|---:|---:|
| **2024-09** | 49 | 18 | 4 | 8 | 75 |
| **2024-10** | 56 | 34 | 3 | 6 | 96 |
| **2024-11** | 41 | 70 | 2 | 4 | 115 |
| **2024-12** | 51 | 84 | 0 (none in folder) | 0 | 135 |
| **2025-01** | 52 | 93 | 0 (none in folder) | 0 | 145 |
| **2025-02** | 47 | 56 | 1 | 2 | 105 |
| **2025-03** | 70 | 61 | 1 | 2 | 133 |
| **2025-04** | 60 | 136 | 1 | 2 | 198 |
| **2025-05** | 58 | 128 | 2 | 4 | 190 |
| **2025-06** | 55 | 130 | 4 | 8 | 193 |
| **Total** | **539** | **810** | **18** | **36** | **1,385** |

- Total Logical Records: **1,367** (539 Central + 810 State + 18 Spurious)
- Total Excel Data Rows in Workbooks: **1,385** (539 Central + 810 State + 36 Spurious across 2-row pattern)
- Total Revision Records Staged in Evidence: **4**
- Provenance Entries in `evidence/record_provenance.jsonl`: **1,385** (exact 1-to-1 parity)

---

## 5. Revision Links Summary

Four standalone revision documents were extracted into `evidence/revision_records.xlsx` and linked in `reports/revision_links.csv`:

1. **`2024-11_revised.pdf`**:
   - Product: *Tofacitinib Tablets IP 5 mg (TOFAJAK TABLETS)*, Batch: `4F30009`, S.No: `40.`
   - Proposed Link: `2024-11_all.xlsx`, sheet `central`, S.No `40`.
   - Update: Originally attributed to *M/s.CIPLA LTD*. Reclassified to *Under Investigation* following Cipla denial; declared purported spurious.
2. **`2025-01_revised.pdf`**:
   - Product: *TELMA AM*, Batch: `5240367`, S.No: `79.`
   - Proposed Link: `2025-01_all.xlsx`, sheet `state`, S.No `79`.
   - Update: Originally attributed to *M/s. Glenmark Pharmaceuticals Ltd*. Reclassified to *Under Investigation* following Glenmark denial; declared purported spurious.
3. **`2025-01_revised-1.pdf`**:
   - Product: *Dmex Colecalciferol (Vitamin D3) Tablets B.P.*, Batch: `4D077301`, S.No: `23.`
   - Proposed Link: `2025-01_all.xlsx`, sheet `central`, S.No `23`.
   - Update: Originally attributed to *M/s. 4Care Lifescience Pvt. Ltd*. Reclassified to *Under Investigation* / *M/s Aeron Lifesciences* per investigation report; declared purported spurious.
4. **`2025-05_revised.pdf`**:
   - Product: *Tranexamic Acid Tablets IP (Trenaxa 500)*, Batch: `18242021A`, S.No: `19.`
   - Proposed Link: `2025-05_all.xlsx`, sheet `central`, S.No `19`.
   - Update: Heading specifies May 2025 (Revised) but subtitle specifies January 2025 (Revised). Original record confirmed in `2025-05_central` S.No 19. Reclassified to *Under Investigation* following Macleods denial.

---

## 6. Known Unresolved Issues and Flags (from `reports/manual_review.csv`)

- **Multi-Batch Cells**:
  - `2025-06_central.pdf`, S.No 25 (`workbooks/2025-06_all.xlsx#central!C26`): `B.no: IEW1480C, IEW-1480B`
  - `2025-06_central.pdf`, S.No 26 (`workbooks/2025-06_all.xlsx#central!C27`): `B.no: IEW-1487C, IEW-1487B`
  - `2025-06_state.pdf`, S.No 42 (`workbooks/2025-06_all.xlsx#state!C43`): `270524-BKN13,` (trailing comma)
- **Header & Subtitle Conflict**:
  - `2025-05_revised.pdf`: Heading says May 2025 (Revised), subtitle says January 2025 (Revised). Both preserved in evidence; flagged for reviewer verification.
- **Footer Date Mismatch**:
  - `2024-09_state.pdf`, Page 5: State non-reporting notes cite *"Month of August, 2024"* despite being published in the September alert. Preserved verbatim in `reports/source_availability.csv`.
- **Table Cell Overflow Stitched**:
  - `2024-10_state.pdf`, S.No 13: corrected to `Vitamin B Complex Tablets N.F.I`. The overflow `Co` belongs immediately before `mplex`, not before `Vitamin B`. Original PDF table fragments remain in provenance; issue REV-003 records the verified repair.
- **Cosmetics & Devices Retained**:
  - Henna cone (*Dulhan Special Kharachi Mehandi Cone*, 2024-10 state S.No 7) and cosmetic items retained with original serials and flagged.
- **Excel Serial Dates in Source**:
  - `2025-01_state.pdf`, S.No 79: Dates printed as raw Excel serial integers `45352` and `46419`; preserved verbatim.

---

## 7. Validation Execution

To re-run validation, execute:
```bash
./BatchGuard/.venv/bin/python PDF_CLEANING_REVIEW/tools/validate_outputs.py
```
The strengthened validator checks:
- Exact source/workbook sets, headers and reference counts.
- Unique workbook-row/provenance identities, not only equal row counts.
- Fresh PDF-table extraction against workbook cells, original fields and raw evidence.
- Source hashes, contributing pages, text batch types, formulas and merged cells.
- Review links, unresolved status, corrected product descriptions and revision targets.

The PDF-table comparison reuses the extraction engine. Passing it does not mean every source cell has been independently visually verified or every source contradiction resolved. Reference counts are not detection/model metrics. Unmeasured boilerplate-row counts are blank rather than invented.

## 8. Reproduce the staged correction and regression checks

From the project root:

```bash
PYTHONDONTWRITEBYTECODE=1 ./BatchGuard/.venv/bin/python PDF_CLEANING_REVIEW/tools/extract_all.py
PYTHONDONTWRITEBYTECODE=1 ./BatchGuard/.venv/bin/python PDF_CLEANING_REVIEW/tools/generate_reports.py
PYTHONDONTWRITEBYTECODE=1 ./BatchGuard/.venv/bin/python PDF_CLEANING_REVIEW/tools/validate_outputs.py
PYTHONDONTWRITEBYTECODE=1 ./BatchGuard/.venv/bin/python -m unittest discover -s PDF_CLEANING_REVIEW/tools -p 'test_*.py' -v
```

The first two commands regenerate staged outputs only. Report generation attaches record issues, document-wide coverage issues, and linked-revision issues to provenance. A resolved repair is distinguished from an unresolved source issue. Run both commands before validation when rebuilding.

The review report now identifies June central records 25–26 as Eldervit injections, matching the source and workbooks. All 13 issue IDs are retained; REV-003 is resolved, while the other 12 remain pending integration/source review. Their existence is not a validation failure when correctly preserved and linked.

No revision reclassification, date normalization, multi-batch splitting, manufacturer alias merging, or active-data integration is performed by these corrections. Original source values remain available. Staged for review; not integrated or model-ready.

## 9. Correction verification results

- The strengthened validator failed on the original defects before regeneration, then passed on the corrected outputs.
- Eight regression tests passed, including rejection of the broken product repair, incorrect report descriptions, duplicate provenance mappings, missing review links, altered hashes/raw evidence, and falsely clean unresolved records.
- Only one workbook cell changed in value/type/format: `2024-10_all.xlsx`, `state!B14`, corrected to `Vitamin B Complex Tablets N.F.I`.
- All 13 issue IDs now link to their affected provenance records (28 rows, including document-wide reporting coverage and linked revisions). REV-003 is resolved; 12 issues remain pending.
- All ten corrected workbooks passed the existing application parser in an isolated temporary directory: 1,367 logical records (539 central, 810 state, 18 spurious).
- Hash comparison confirmed all 590 protected files outside this staging folder remained unchanged, including original PDFs, active workbooks, code and training artifacts.

Saved evidence: `reports/validation.log`, `reports/regression_tests.log`, and `reports/correction_verification.json`. These results concern staged extraction integrity and compatibility, not model quality or full visual verification of every PDF cell. Active integration has not been performed.
