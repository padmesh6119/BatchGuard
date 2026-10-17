# BatchGuard change log

Every change made to this repository, why it was made, and how it was verified. Newest first. Paths are relative to the repository root. "Verified" means a command was run and its output checked; anything unverified says so.

## 2026-10-17 — Flaw fixes, trained models, LinuxONE deployment path

Base commit: `1d84601 Import BatchGuard project from archive`. Verification environment: x86_64 laptop (i5-1240P), Python 3.12.3, clean venv with pandas 3.0.6, numpy 2.5.4, openpyxl 3.1.5, scikit-learn 1.9.1, streamlit 1.66.0, snapml 1.17.2.

### Fixed defects

| # | Defect (how it was found) | Fix | Verification |
|---|---|---|---|
| F1 | `requirements.txt` allowed `openpyxl>=3.1`; with pandas 3.x a fresh install could get openpyxl 3.1.2 and 4 refresh tests errored: *"Pandas requires version '3.1.5' or newer of 'openpyxl'"* (ran the suite with the system Python) | `BatchGuard/requirements-core.txt` (pandas>=2.1, openpyxl>=3.1.5, scikit-learn>=1.4) for headless/LinuxONE use; `BatchGuard/requirements.txt` = core + streamlit>=1.50 | Clean venv from `requirements.txt`: all tests pass |
| F2 | `replay.py demo` rerun into the same output reused `events.sqlite`: second run reported *accepted 0, retries 89*, so any benchmark from it measured only the duplicate path (reproduced) | `BatchGuard/replay.py`: refuses an existing event DB unless `--resume`; default `--output` anchored to the project root instead of the working directory | `tests/test_train_models.py::ReplayTests` (first run accepts events, second exits with an error) |
| F3 | Dead legacy code in `BatchGuard/batchguard_engine.py`: `make_simulated_scans`, `detect_scan_anomalies`, `build_inspection_queue` had no callers and carried audit items 27–37 (non-reproducible `datetime.now()` timestamps, mislabeled duplicate-token injection, per-event queue rows, fixed +40 fusion, unknown-batch anomaly bonus) | Deleted, with their unused imports | `git grep` found no callers; full suite passes |
| F4 | `use_container_width` (removal date 2025-12-31, already past) at 9 call sites in `BatchGuard/app.py`; warnings on every run | Replaced with `width="stretch"` | Streamlit AppTest: no warnings, exceptions or errors across capacity, category, earliest-month, June 2026 and K interactions |
| F5 | `BatchGuard/TEST_RESULTS.txt` described an 11-workbook, 1,898-record build that no longer exists (audit item 49) | Replaced with the current verified results | Contents match the commands in this log |
| F6 | A fresh clone could not reproduce training: `data/snapshots/` and `data/CURRENT` were gitignored, but the training bundle is bound to snapshot `6e881f22…` | `.gitignore` now tracks exactly that snapshot (6.8 MB) and `data/CURRENT`; ignores `data/review_actions.jsonl` | `git status` shows the snapshot tracked; `train_models.py` loads it by ID |
| F7 | Model card bug found by the new tests: candidate-grid validation scores were overwritten by baseline validation scores (same dict key) | `BatchGuard/train_models.py`: keys `candidate_validation_average_precision` and `validation_average_precision_vs_baselines` | `test_training_selects_on_validation_and_exports_verified_models` |
| F8 | `decision_core.build_decision_queue` duplicated rule thresholds, returned only the top N (no "selected / available" count possible), never surfaced spurious-report matches, and could not use a trained model | Rewritten `BatchGuard/decision_core.py`: `rank_candidates` returns every candidate ranked; `build_decision_queue` keeps the old capacity contract; shared `rule_scan_score`, `corroboration`, `fuse`; `SPURIOUS_REPORT_REFERENCE` and `NO_EARLIER_MANUFACTURER_HISTORY` reasons; state shown only from simulated scan coordinates; optional verified trained models | Existing queue test plus new model-backed test (clone outranks benign, signals stay separate) |

### New capabilities

- **Shared Layer A features** — `BatchGuard/model_foundation.py`: extracted `history_features(df, cutoff)`; `history_examples` now calls it, and live scoring uses the same function. Verified: regenerating the bundle with the new code reproduces **every file** of `data/training/foundation-ready-v1` byte for byte; `ParityTests` checks live features equal the bundle's validation features.
- **Training and evaluation** — `BatchGuard/train_models.py` (new). Backends: scikit-learn and IBM Snap ML. Fixed small grids; selection on validation AP only (ties keep the simpler model); Layer B threshold by validation F1; fusion policy (`weighted` vs `tiered`) chosen on the validation month; test split read once. Baselines: legacy 60/25/15 index, most past records, most recent 3 months, exact random expectation (tie-aware), scan rule. Paired bootstrap CI for the AP gain. Exports pickled models, test predictions and a model card with SHA-256 hashes; refuses to overwrite.
- **Trained models** — `BatchGuard/models/baseline-v1/` (scikit-learn, `layer-ab-sklearn-dd7cc2b52ba5`) and `BatchGuard/models/snapml-v1/` (Snap ML, `layer-ab-snapml-aa606f75e73a`). Deterministic: a repeat run reproduced the same version and metrics; rehearsal parity comparison gave max prediction difference 0.0.
- **Model loading safety** — `decision_core.TrainedModels` verifies artifact hashes before unpickling and refuses to load if `scan_features.py` changed since training.
- **Benchmark** — `BatchGuard/benchmark.py` (new). `run`: stage-separated timings (event validation, feature extraction, single/batch inference, Layer A scoring, per-scan decision, full queue rebuild), 5 repeats after warmup, workload hashes, CPU facts including whether the s390x NNPA facility is listed (availability only). `compare`: prediction difference and Spearman correlation between two hosts' models. Laptop results in `BatchGuard/reports/benchmarks/`.
- **LinuxONE runner** — `BatchGuard/linuxone_run.sh` (new): refuses non-s390x hosts unless `ALLOW_NON_S390X=1`; records host facts, packages, tests, both training backends, laptop parity and benchmarks under `reports/linuxone/<UTC>-<machine>/`. Rehearsed end to end on the laptop (rehearsal output deleted, not committed).
- **Runbook** — `BatchGuard/LINUXONE_RUNBOOK.md` rewritten for deployment: PyPI check (17 Oct 2026) found **no s390x wheels for numpy, scipy, pandas, scikit-learn, pyarrow**; Snap ML 1.17.2 has s390x wheels (cp311/cp312). Install path: OS numeric packages + `venv --system-site-packages` + pip openpyxl + `pip install --no-deps snapml`. Screenshot checklist and claim limits included.
- **Environment record** — `replay.environment()` now also records numpy and scikit-learn versions.
- **Tests** — `BatchGuard/tests/test_train_models.py` (new, 8 tests): tie-aware selection, threshold rule, fusion policies, end-to-end training/export/tamper rejection, model-backed queue, Snap ML backend (skips if absent), live/bundle feature parity, replay rerun refusal. Suite: **39 tests OK** (was 31).
- **Docs** — `BatchGuard/README.md` leads with measured results; `BatchGuard/MODEL_FOUNDATION.md` training section replaces the stale "no model fitted" text.

### Measured results (laptop; from `models/*/model_card.json`, `reports/benchmarks/*.json`)

- **Layer A (real CDSCO, held-out Jul–Aug 2026, 3,370 examples, 61 positives):** AP 0.098 (Snap ML 0.099) vs legacy index 0.067, most past records 0.055, last-3-months 0.046, random 0.018. ROC-AUC 0.718 vs 0.677. Bootstrap AP gain vs legacy index +0.032, 95% CI [+0.005, +0.068], 99.1% of 1,000 rounds above zero. Top 25 manufacturers per month capture 21 of 76 reachable later reports vs 9.5 / 12.0 / 13.1 / 1.1. 383 of 459 later NSQ records come from manufacturers with no earlier report or no usable text and are unreachable by history.
- **Layer B (simulated):** model recall 72.7% at precision 98.6%; rule recall 80.8% at precision 100%. Held-out `slow_copy`: model 18% vs rule 42% alerts. All candidates had validation AP 1.0 (seen families separable), so validation could not separate them. **The trained scan model does not beat the rule.**
- **Fusion (equal budget, 231 test candidates/month):** tiered selected on validation (0.582 vs 0.543 balanced capture). N≤50 is saturated by scan alerts (fused = scan-only). N=100: tiered 77% clones / 48% real recurrence; scan rule 83% / 42%; history 50% / 35%; random 43% / 43%. Fusion is not uniformly better.
- **Speed (x86_64, not IBM Z):** per-scan decision p50 1.69 ms / p99 3.18 ms; scan inference single row p50 1.28 ms; workload 434–611 events/s; full queue rebuild p50 8.5 s (Layer A features recomputed in a Python loop — known bottleneck).

### Process notes (for honesty slide and judges)

- The test split was first evaluated in a scratch run with the same code and seed; the canonical run reproduced it exactly. After seeing it, queue budgets 100 and 150 were **added** to the report (to show the regime where capacity exceeds the number of alerts); no model, threshold, grid or selection rule was changed.
- The Layer B shortfall is kept as measured. Re-tuning against these test results would leak; the fix is a new bundle with validation-only hard families.
- Not changed: `scan_features.py` (its hash binds the bundle and models), `inspection_stream.py`, `src/*`, raw data, the training bundle, `PDF_CLEANING_REVIEW/`, and the historical audit/spec documents (`BATCHGUARD_REVIEW.md`, `BATCHGUARD_FINAL_SPEC.md`, roadmaps), which still describe the pre-training state.
- The bundled `BatchGuard/.venv/` (gitignored) is a non-executable copy of a Python 3.14 environment from another machine; create a new venv instead.

### Judge-verdict status

| Criticism | Status |
|---|---|
| No model fitted; no ML library | **Fixed**: both layers trained, scikit-learn and Snap ML, evaluated against named baselines |
| 9.10% recurrence says nothing about prioritisation value | **Fixed**: capture-at-budget on real held-out months (21 vs 9.5 at K=25) with CI |
| Fusion lift unproven | **Measured, mixed**: no lift at N≤50; trade-off at N≥100; reported as is |
| Models trained on own simulator | **Partly**: Layer A is real data; Layer B remains simulated and does not beat its rule |
| No LinuxONE run, no "why LinuxONE" | **Prepared, not done**: s390x install path, one-command evidence run, parity check. Needs your LinuxONE session |
| No containerisation | **Open**: deliberately skipped; numeric stack has no s390x PyPI wheels, so an image needs a distro/conda base chosen on the real host |
| Dashboard missing live feed, drawer, map, platform panel | **Open**: next work item |
| No demo video / 3-minute script | **Open**: needs the combined dashboard first |
| Originality rule ("code created during the event") | **Needs you**: confirm with organizers; code cannot answer it |
| Mandatory IBM labs | **Needs you** |

### Next steps, in order

1. Run `BatchGuard/linuxone_run.sh` on the assigned LinuxONE; commit `reports/linuxone/` and `reports/benchmarks/`.
2. Vectorize `history_features` (removes the 8.5 s queue rebuild) and re-benchmark on both hosts.
3. Build the combined inspector screen (banner, capacity, ranked queue, live simulated feed, evidence drawer with map, evaluation charts, platform panel) on `decision_core.rank_candidates` + `load_models()`.
4. Bundle v2 with validation-only hard scan families; retrain without touching v1 results.
5. Three-minute demo script and video.
