# BatchGuard core workflow on LinuxONE

The product combines real CDSCO history and simulated clone-code scans. The current training foundation covers both layers; flooding hardening is deferred. Actual LinuxONE execution and trained ML remain unverified.

Training preparation: follow [MODEL_FOUNDATION.md](MODEL_FOUNDATION.md). Reuse the same source snapshot, feature contracts, seeds, and held-out splits across laptop and LinuxONE. Models must use only the declared feature columns. Do not regenerate an easier final test set after seeing results.

## Setup

Transfer the `BatchGuard` directory, including raw monthly workbooks and the original processed datasets, to the organizer-assigned LinuxONE environment. From that directory, with Python 3.11+:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python replay.py platform --require-s390x
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python refresh_data.py
.venv/bin/python primary_workflow.py --capacity 10
```

The platform command only reports environment metadata and enforces the architecture check; it does not run attack scenarios. Confirm host allocation separately. A package version or s390x architecture does not demonstrate accelerated AI.

The same primary commands run locally. Retain software versions, the snapshot manifest, and exported results. Record actual compatibility failures. Current dependency files have lower bounds rather than a fully pinned cross-platform environment.

## Application

```bash
.venv/bin/python -m streamlit run app.py
```

- **Inspection priorities:** choose month, evidence category, and unique follow-up capacity; inspect and download case evidence and source workbooks.
- **Historical evidence:** view snapshot-wide descriptive context and monthly NSQ counts.
- **History evaluation:** compare earlier-history selection with count and random baselines on later reports.
- **Data quality:** inspect missing fields, manufacturer uncertainty, failure mapping, and unavailable source sheets.

The application does not automatically declare medicines counterfeit or safe. It provides review signals and preserves the need for human/laboratory verification.

## Publication and recovery

Refresh builds from the current raw-workbook list in a fresh staging directory. It validates all three derived datasets, hashes outputs and copied source workbooks, and publishes one immutable snapshot. `data/CURRENT` is the reader pointer; original processed files remain unchanged.

If refresh fails, investigate the error; the last published snapshot remains active. A single-writer lock protects refresh. After a process crash, verify that no refresh is running before removing a stale `data/.refresh.lock`.

Earlier snapshots remain under `data/snapshots/<snapshot_id>/`. A verified earlier snapshot can be restored through `snapshot_store.publish_pointer(ROOT, previous_snapshot_id)`. This validates its files before replacing the pointer. Without a pointer, readers retain compatibility with original `data/processed/` files.

## Primary outputs

`reports/primary_workflow/` contains:

- `followup_queue.csv`: ranked unique published product/batch/manufacturer-text cases, earlier history, reason codes, source filenames, and record IDs.
- `chronological_coverage.csv`: month-ordered report coverage for the descriptive index, most-past-records baseline, and exact random expectation.
- `summary.json`: active snapshot, chosen month/category, capacity, interpretation, and limitations.

The history check ranks manufacturer signatures. The follow-up queue ranks product/batch cases. It is invalid to describe the former as measured failures caught per inspection. No complete market/test denominator is available.

## Remaining core work

- Verify source URLs, publication dates, and revisions for individual workbook inputs; local hashes alone do not establish official provenance.
- Review manufacturer aliases and unresolved records without inventing legal identity.
- Fit/evaluate the prepared next-report-recurrence and simulated-clone tasks against their baselines; failure-list absence is not a safe-medicine label.
- Execute and measure the actual assigned IBM Z workload and prepare a reproducible demonstration.

## Deferred scan experiment

`inspection_stream.py`, `replay.py`, and `tests/test_inspection_stream.py` remain available, together with previous replay reports. They describe synthetic behavior, including hypothetical flooding. They are not the primary workflow or evidence of real-world counterfeit detection. Revisit only after the core work above.
