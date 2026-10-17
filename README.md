# BatchGuard

One inspector screen: **which medicine batches to sample first within this week's capacity.**

- **Layer A, real data:** CDSCO NSQ and spurious-drug lists, July 2025 to August 2026 (2,551 analytical records).
- **Layer B, simulated data:** pack-verification scans on real reference batches. Packs, sources, locations and labels are synthetic.
- Humans decide. BatchGuard never blocks medicine or declares counterfeiting.

Product spec: [BATCHGUARD_FINAL_SPEC.md](BATCHGUARD_FINAL_SPEC.md).
Current flaw review: [docs/REVIEW_STATUS.md](docs/REVIEW_STATUS.md).
Synthetic scan audit and frozen challenge: [docs/SYNTHETIC_DATASET.md](docs/SYNTHETIC_DATASET.md).
Why extra scripted training does not fix the scan model: [docs/MODEL_DEPENDABILITY.md](docs/MODEL_DEPENDABILITY.md).
Adjudicated field training and scoring contract: [docs/FIELD_MODEL.md](docs/FIELD_MODEL.md).
IBM Z scale experiment and measured laptop baseline: [docs/IBM_Z_SCALE.md](docs/IBM_Z_SCALE.md).

## Run, in order

```bash
python3 -m venv .venv && . .venv/bin/activate   # fish: source .venv/bin/activate.fish
pip install -r requirements.txt snapml     # snapml optional; without it the Snap ML backend is skipped
python -m src.ingest                       # optional: rebuild data/processed from data/raw (identical CSVs; new manifest timestamp)
python -m src.fusion run                   # train + evaluate both layers -> outputs/
python -m src.fusion benchmark             # stream benchmark -> outputs/benchmark_<laptop|linuxone>.json
python -m src.synthetic_challenge           # separate scan stress set -> data/synthetic/
python -m src.scan_learning_curve            # fixed-test learning curve -> outputs/scan_learning_curve.json
python -m src.field_model --help              # template, train, and score commands; field data is not included
python -m src.scale_benchmark --events 5000 --profile routine --backend sklearn
python -m unittest discover -s tests       # 34 tests
python -m app.dashboard                    # dashboard -> outputs/dashboard.html (open in any browser)
```

`run` takes about 75 s on a laptop. It writes `outputs/results.json`, `outputs/inspector_queue.csv`, `outputs/charts/` and `outputs/models/<backend>/` (pickled models with hashes, a model card and test predictions).

**Dashboard.** `outputs/dashboard.html` is one self-contained file: no server, no network, no external assets. The builder replays the simulated scan feed through the live ranking code after every scan, for each trained backend, so the page plays back exactly what the queue decided.
- **Decision:** play the feed; set the week's capacity; compare the combined policy with scan-only and history-only capture at the nearest tested budget; see how many batches have no earlier manufacturer history; open a batch's evidence (scan timeline, map, packs and sources, real manufacturer history and source files); record an inspector decision (kept in the browser; export as CSV).
- **Other tabs:** Evaluation, Platform (laptop vs LinuxONE) and Data.

The demo feed includes two simulated scans on published spurious-list batches whose manufacturer text is unavailable. They make the missing-history case visible in the decision screen; they are not new real scan observations.

## Measured results (laptop, x86_64; held-out test months July and August 2026)

| | Result | Baselines |
|---|---|---|
| Layer A: next-month report recurrence, AP | **0.098** (Snap ML 0.099) | legacy index 0.067, most past records 0.055, last 3 months 0.046, random 0.018 |
| Layer A: AP gain vs strongest baseline | +0.032, bootstrap 95% CI 0.005 to 0.068 | |
| Layer A: later reports captured, top 25 manufacturers per month | **21** | best baseline 13.1, random 1.1 |
| Layer B: clone-pattern recall / precision (simulated) | declared rule **80.8% / 100%** | trained model 72.7% / 98.6% |
| Layer B: held-out `slow_copy` family alert rate | rule 42% | model 18% |
| Fusion at N=100 of 177 to 197 batches: simulated clones / real recurring batches | fused **85% / 79%** | rule only 87% / 37%, history only 62% / 100%, random 54% / 54% |
| Existing staged benchmark, per-scan decision p50 / p99 | 1.5 ms / 3.1 ms | 1,291 events/s across its staged workload; cached queue rebuild ≈27 ms |

The trained scan model does not beat the rule, so **the rule drives alerts** and the model's synthetic score is shown for diagnosis only. Each test month has only 7 to 8 real recurring-manufacturer batches in the fusion queue, so the recurrence shares move in large steps. With history through January 2026, 9.1% (122 of 1,341) of later NSQ records carried manufacturer text seen earlier. This is one measured split, not a prediction ceiling.

**Synthetic-data challenge:** The original scan test has 42.9% generated positives and no benign GPS/clock-error cases. On a separate fixed challenge of 1,100 synthetic cases, the rule flags 200/400 copied IDs and 300/700 benign cases; the frozen trained model flags 300/400 and 400/700 respectively. Four copied-ID mechanisms have benign counterparts with identical scan features. These are diagnostic stress results, not field accuracy estimates; see [the dataset audit](docs/SYNTHETIC_DATASET.md).

**Training sufficiency:** Increasing the scripted training set from 150 to 4,500 episodes left fixed-test average precision near 0.83 and still produced 300–400 benign alerts on the stress cases. The trained score is now diagnostic only and cannot add an inspector alert. See [the learning-curve audit](docs/MODEL_DEPENDABILITY.md).

**Field model path:** A separate train/score command now accepts independently adjudicated physical-pack cases with server receipt times and scan-quality telemetry. It enforces disjoint sites, chronological splits, a false-alert budget, and a held-out readiness gate. No such cases exist in this repository, so **no field model is currently ready**; see [the input contract and gate](docs/FIELD_MODEL.md).

**Scale experiment:** A separate label-free stream exercises the current per-scan decision path. On one x86 laptop process, 5,000-event routine and repeat-heavy profiles measured about 666 and 611 events/s with scikit-learn, and 713 and 671 events/s with Snap ML. A 100,000-event routine replay measured about 607 events/s, with bounded six-hour active state. These are in-memory synthetic workloads, not a LinuxONE result or proof that IBM Z is required. The [scale report](docs/IBM_Z_SCALE.md) gives workload assumptions and comparison commands.

Building that monthly history context still takes about 4.8 seconds on the measured laptop. The ≈27 ms rebuild assumes it is already cached; the benchmark lists both stages separately. Its staged-workload throughput and the new per-event scale replay use different work definitions and should not be compared as if they measured the same pipeline.

At N=10 in the held-out fusion queues, the combined policy captures 0% of the recurring-manufacturer batches versus 33% for history-only ranking. The dashboard makes this capacity trade-off visible; it is not evidence of better real inspection yield.

## IBM LinuxONE

The commands are prepared for s390x, but this repository has no recorded LinuxONE run. Depending on the host image, install scientific Python dependencies from the OS or a preinstalled environment:

```bash
git clone https://github.com/padmesh6119/BatchGuard.git && cd BatchGuard
python3 -m pip install "openpyxl>=3.1.5" && python3 -m pip install --no-deps snapml
python3 -m unittest discover -s tests
python3 -m src.fusion run
python3 -m src.fusion benchmark            # writes outputs/benchmark_linuxone.json
python3 -m src.scale_benchmark --events 5000 --repeats 2 --profile routine --backend sklearn
```

Commit `outputs/benchmark_linuxone.json`, then run `python -m app.dashboard` again. The Platform tab then shows the LinuxONE numbers next to the laptop numbers. Compare scale reports with `python -m src.scale_compare <laptop.json> <linuxone.json>` only when their workload and model fields match. `nnpa_facility_listed` only reports that the CPU advertises the accelerator facility. Claim acceleration only from measured hardware use.

## Layout

```
data/raw/         original CDSCO workbooks          src/common.py     paths, seeds, labels, model grids
data/processed/   cleaned CSVs + hash manifest      src/ingest.py     workbooks -> processed data
outputs/          results, queue, models, charts    src/layer_a.py    M1 history features, baselines, evaluation
evidence/         environment and version lists     src/simulator.py  M2 simulated scan events
data/synthetic/   frozen diagnostic scan cases      src/synthetic_challenge.py  stress generator and report
docs/             abstract, pitch notes, script     src/detector.py   M2 rule, model, corroboration
app/              dashboard builder + template      src/fusion.py     M3 signals, capacity queue, run, benchmark
```

## Limits

- The Layer A label is next-month report recurrence of earlier manufacturer text. It is not medicine safety.
- Manufacturer text is not a verified legal identity. Source independence is asserted, not verified.
- Layer B labels come from the simulator. Real scan data could behave differently.
