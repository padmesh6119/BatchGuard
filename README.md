# BatchGuard

One inspector screen: **which medicine batches to sample first within this week's capacity.**

- **Layer A, real data:** CDSCO NSQ and spurious-drug lists, July 2025 to August 2026 (2,551 analytical records).
- **Layer B, simulated data:** pack-verification scans on real reference batches. Packs, sources, locations and labels are synthetic.
- Humans decide. BatchGuard never blocks medicine or declares counterfeiting.

Product spec: [BATCHGUARD_FINAL_SPEC.md](BATCHGUARD_FINAL_SPEC.md).
Current flaw review: [docs/REVIEW_STATUS.md](docs/REVIEW_STATUS.md).

## Run, in order

```bash
python3 -m venv .venv && . .venv/bin/activate   # fish: source .venv/bin/activate.fish
pip install -r requirements.txt snapml     # snapml optional; without it the Snap ML backend is skipped
python -m src.ingest                       # optional: rebuild data/processed from data/raw (identical CSVs; new manifest timestamp)
python -m src.fusion run                   # train + evaluate both layers -> outputs/
python -m src.fusion benchmark             # stream benchmark -> outputs/benchmark_<laptop|linuxone>.json
python -m unittest discover -s tests       # 20 tests
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
| Per-scan decision latency, p50 / p99 | 1.9 ms / 5.3 ms | 778 events/s; queue rebuild ≈29 ms with a cached monthly context |

The trained scan model does not beat the rule, so **the rule drives alerts** and the model's probability is shown alongside it. Each test month has only 7 to 8 real recurring-manufacturer batches in the fusion queue, so the recurrence shares move in large steps. With history through January 2026, 9.1% (122 of 1,341) of later NSQ records carried manufacturer text seen earlier. This is one measured split, not a prediction ceiling.

Building that monthly history context still takes about 4.8 seconds on the measured laptop. The ≈29 ms rebuild assumes it is already cached; the benchmark lists both stages separately.

At N=10 in the held-out fusion queues, the combined policy captures 0% of the recurring-manufacturer batches versus 33% for history-only ranking. The dashboard makes this capacity trade-off visible; it is not evidence of better real inspection yield.

## IBM LinuxONE

The same commands run on s390x. PyPI has no s390x wheels for numpy, scipy, pandas or scikit-learn, so use the OS or preinstalled environment for those:

```bash
git clone https://github.com/padmesh6119/BatchGuard.git && cd BatchGuard
python3 -m pip install "openpyxl>=3.1.5" && python3 -m pip install --no-deps snapml
python3 -m unittest discover -s tests
python3 -m src.fusion run
python3 -m src.fusion benchmark            # writes outputs/benchmark_linuxone.json
```

Commit `outputs/benchmark_linuxone.json`, then run `python -m app.dashboard` again. The Platform tab then shows the LinuxONE numbers next to the laptop numbers. `git diff outputs/results.json` shows whether the metrics match the laptop run. Timestamps, environment and fit times always differ. `nnpa_facility_listed` only reports that the CPU advertises the accelerator facility. Claim acceleration only from a measured run.

## Layout

```
data/raw/         original CDSCO workbooks          src/common.py     paths, seeds, labels, model grids
data/processed/   cleaned CSVs + hash manifest      src/ingest.py     workbooks -> processed data
outputs/          results, queue, models, charts    src/layer_a.py    M1 history features, baselines, evaluation
evidence/         environment and version lists     src/simulator.py  M2 simulated scan events
docs/             abstract, pitch notes, script     src/detector.py   M2 rule, model, corroboration
app/              dashboard builder + template      src/fusion.py     M3 signals, capacity queue, run, benchmark
```

## Limits

- The Layer A label is next-month report recurrence of earlier manufacturer text. It is not medicine safety.
- Manufacturer text is not a verified legal identity. Source independence is asserted, not verified.
- Layer B labels come from the simulator. Real scan data could behave differently.
