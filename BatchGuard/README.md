# BatchGuard

BatchGuard helps a drug inspector decide which medicine batches to sample first within this week's capacity. It combines **Layer A: real CDSCO quality reports (July 2025–August 2026, 2,551 records)** with **Layer B: clearly labeled simulated pack-verification scans**, keeps historical risk, scan anomaly and evidence quality as separate values, and explains every priority. Humans decide; a scan anomaly is not proof of counterfeiting and a missing report is not proof of safety. Product direction: [AGENTS.md](../AGENTS.md). Change log: [CHANGELOG.md](../CHANGELOG.md).

## Measured results (laptop, 17 October 2026)

**Layer A, real data.** Target: does a manufacturer-text signature already seen in earlier NSQ reports appear again in next month's reports? Trained on target months through May 2026, model chosen on June 2026, evaluated once on July–August 2026 (3,370 examples, 61 positives).

| Ranking of earlier manufacturers | Average precision | Later reports captured, top 10 / month | top 25 / month |
|---|---:|---:|---:|
| Trained logistic model (`models/baseline-v1`) | **0.098** | **11** | **21** |
| Legacy 60/25/15 index | 0.067 | 3 | 9.5 |
| Most past records | 0.055 | 1 | 12.0 |
| Most records in last 3 months | 0.046 | 8.9 | 13.1 |
| Random (exact expectation) | 0.018 | 0.45 | 1.1 |

Captures are summed over the two test months: 76 later reports came from previously seen manufacturers, out of 459 NSQ records in total; the other 383 came from manufacturers with no earlier report or no usable manufacturer text and cannot be ranked from history. Paired bootstrap of the AP gain over the legacy index: +0.032, 95% CI [+0.005, +0.068]. Snap ML (`models/snapml-v1`) gives AP 0.099.

**Layer B, simulated scans.** On held-out episodes the trained scan model does **not** beat the hand rule: recall 73% at 99% precision versus the rule's 81% at 100%. On the held-out `slow_copy` family it alerts on 18% versus the rule's 42%. All validation candidates scored a perfect AP because the seen families are separable by design, so validation could not identify the better model; the next bundle needs validation-only hard families.

**Combined queue.** Under the same budget each single layer captures the other layer's risk at about chance (N=50: history alone selects 22% of simulated clones, random 22%; the scan rule selects 21% of really-recurring manufacturers' batches, random 22%). At N=100 of 231 test candidates, the validation-selected tiered fusion captures 77% of simulated clones and 48% of candidates whose manufacturer was really reported that month, versus 83%/42% for the scan rule and 50%/35% for history alone. Fusion is not uniformly better; full curves are in the model card.

**Speed (x86_64 laptop, not IBM Z).** Per-scan decision (validate, re-derive pack features, score, fuse) p50 1.7 ms, p99 3.2 ms; end-to-end workload 434–611 events/s. Rebuilding the full queue takes ≈8.5 s because Layer A features are recomputed in a Python loop; this is the next optimization target. Raw files: `reports/benchmarks/`.

**LinuxONE: not run yet.** Follow [LINUXONE_RUNBOOK.md](LINUXONE_RUNBOOK.md); one script records tests, training, laptop parity and benchmarks on s390x.

## Run

Python 3.11+:

```bash
python -m pip install -r requirements.txt          # requirements-core.txt for headless/LinuxONE use
python refresh_data.py                              # rebuild and publish a validated snapshot
python train_models.py --output models/my-run       # add --backend snapml to use IBM Snap ML
python benchmark.py run --models models/baseline-v1
python primary_workflow.py --capacity 10
python -m streamlit run app.py
python -m unittest discover -s tests -v
```

With unchanged raw workbooks, refresh reproduces the committed snapshot `6e881f22…` (verified). Changed workbooks create a new snapshot; it then needs a new bundle and models, and its ID added to `.gitignore` before committing.

Training refuses to overwrite an existing model directory, checks that `scan_features.py` matches the bundle, selects models and thresholds on validation data only, and evaluates the reserved test split once. `decision_core.rank_candidates(..., models=load_models())` scores live scans with the same feature code used in training.

## Data reliability

Refresh copies only current raw inputs into a clean staging directory, runs the parser/normalizers, checks row counts and IDs, records file and builder hashes, then atomically switches `data/CURRENT`. Failed refreshes keep the previous snapshot; a single-writer lock prevents concurrent publication. The snapshot used by the training bundle and models is committed so a fresh clone reproduces it exactly. The manifest records local workbook hashes, not independently verified download origins. Manufacturer text is not a verified legal identity. Collection months stand in for publication dates.

## Current limits

- The dashboard (`app.py`) is still the historical-review view; the combined seven-part inspector screen with live simulated feed is not built yet.
- Ten earlier months extracted from PDFs remain staged in `../PDF_CLEANING_REVIEW/`, not integrated.
- No LinuxONE execution, accelerator use, real scan data, or inspection yield is claimed.
