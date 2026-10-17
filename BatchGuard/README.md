# BatchGuard

BatchGuard combines real CDSCO history and simulated verification scans into one explained inspector queue with separate history, scan, and evidence values. The product target is recorded in [AGENTS.md](../AGENTS.md).

The training foundation now includes source-row provenance, chronological/history examples, labeled normal/clone scan episodes, reserved test families, and shared training/inference features. See [MODEL_FOUNDATION.md](MODEL_FOUNDATION.md). No trained model exists yet. The current UI remains a historical-review view; integrating the full combined inspector screen is still required.

## Main workflow

1. Load CDSCO monthly workbooks from `data/raw/YYYY-MM_all.xlsx`.
2. Build and validate a versioned snapshot; publish only when every integrity check passes.
3. Choose a report month, NSQ findings or spurious reports, and a follow-up capacity.
4. Review unique product/batch/manufacturer-text candidates, their earlier NSQ history, and original evidence.
5. Compare the historical index with past-count ranking and random selection on subsequent reported records.

The queue reviews already published findings. It does not predict safety of untested market batches. Manufacturer text is not a verified legal identity; missing history does not establish safety. Spurious allegations remain separate from ordinary NSQ findings.

## Run

From this directory, with Python 3.11+ and the requirements installed:

```bash
python refresh_data.py
python primary_workflow.py --capacity 10
python -m streamlit run app.py
python -m unittest discover -s tests -v
```

Windows setup remains available through `powershell -ExecutionPolicy Bypass -File .\run_batchguard.ps1`.

## Data reliability

Refresh copies only current raw inputs into a clean staging directory, runs the existing parser/normalizers, checks row counts and IDs, records file hashes and builder hashes, then atomically switches `data/CURRENT`. Readers resolve one published snapshot and check its files. Failed refreshes retain the previous snapshot. A single-writer lock prevents concurrent refresh publication.

The original `data/processed/` and `reports/` files remain available. Readers use them when no `data/CURRENT` exists. Published snapshots live under `data/snapshots/`; old versions remain available for rollback. The manifest records local workbook hashes, not independently verified download origins.

Known duplicate/manual-review rules apply only when their historical month is present. Existing strict verification remains in force for those months.

## Results and platform

`primary_workflow.py` exports `followup_queue.csv`, `chronological_coverage.csv`, and `summary.json` to `reports/primary_workflow/`. The evaluation selects manufacturer signatures, whereas the queue selects product/batch candidates; these are different units. Collection-month ordering is not verified publication-time availability. No trained ML or prospective inspection yield is claimed.

See [LINUXONE_RUNBOOK.md](LINUXONE_RUNBOOK.md) for headless setup, exports, snapshot publication, and remaining IBM Z work. Actual LinuxONE execution remains unverified.

The flooding-centered replay experiment is deferred; its CLI and artifacts remain for later work. Core normal/clone-scan preparation is active through `model_foundation.py`. No per-scan LLM is used.
