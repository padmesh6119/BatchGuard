# BatchGuard on LinuxONE

LinuxONE runs the decision workload: validated data loading, Layer A/B training and evaluation, per-scan scoring, queue ranking, and benchmarks. The Streamlit dashboard displays those artifacts. A laptop rehearsal of every step below passed on 17 October 2026 (x86_64). **No LinuxONE run has been recorded yet.**

## 1. Get the code

```bash
git clone https://github.com/padmesh6119/BatchGuard.git
cd BatchGuard/BatchGuard
```

The clone includes the raw CDSCO workbooks, the validated snapshot `6e881f22…` (`data/CURRENT`), the prepared training bundle `data/training/foundation-ready-v1/`, and the laptop reference models `models/baseline-v1/` (scikit-learn) and `models/snapml-v1/` (Snap ML). LinuxONE training reuses that exact snapshot, bundle, seed and code.

## 2. Python environment on s390x

Checked against PyPI on 17 October 2026: **numpy, scipy, pandas, scikit-learn and pyarrow publish no s390x wheels; Snap ML 1.17.2 does (CPython 3.11 and 3.12); openpyxl and streamlit are pure Python.** So install the numeric stack from the OS, then add the rest with pip.

Ubuntu/Debian (Ubuntu 24.04 ships pandas 2.1, scikit-learn 1.4, both supported):

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-numpy python3-scipy python3-pandas python3-sklearn
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install "openpyxl>=3.1.5"
.venv/bin/python -m pip install --no-deps snapml     # --no-deps keeps pip from rebuilding numpy/scipy/sklearn
.venv/bin/python -c "import numpy, scipy, pandas, sklearn, openpyxl, snapml; print('ok')"
```

RHEL/SLES or no OS packages: use an IBM-provided Python/AI environment or conda for s390x if the event offers one; otherwise `pip install -r requirements-core.txt` builds from source and needs `gcc gcc-gfortran openblas-devel cmake ninja-build` and considerable time. Record whichever route works, including failures, in the run log.

`requirements-core.txt` is the headless set (pandas, openpyxl, scikit-learn). `requirements.txt` adds Streamlit for the dashboard.

## 3. Run the matched workload

```bash
PYTHON=.venv/bin/python ./linuxone_run.sh
```

The script refuses to run unless `uname -m` is `s390x` (rehearse elsewhere with `ALLOW_NON_S390X=1`). It writes everything to `reports/linuxone/<UTC>-s390x/`:

| Step | Command inside the script | Evidence file |
|---|---|---|
| Host facts | `uname -a`, `lscpu`, `free -m`, `/etc/os-release`, `replay.py platform --require-s390x` | `run.log`, `platform.json`, `packages.txt` |
| Tests | `python -m unittest discover -s tests -v` (39 tests; the Snap ML test skips if Snap ML is absent) | `run.log` |
| Train + evaluate | `train_models.py --backend sklearn`, then `--backend snapml` | `models-sklearn/`, `models-snapml/` (model cards with validation choices and one final test evaluation) |
| Parity with laptop | `benchmark.py compare --reference models/baseline-v1 …` | `compare-sklearn.json`, `compare-snapml.json` |
| Benchmark | `benchmark.py run --require-s390x` per backend, 5 repeats after warmup | `benchmarks/s390x-<backend>-<UTC>.json` |

Laptop rehearsal timings (i5-1240P): tests 33 s, each training run ≈25 s including evaluation, each benchmark ≈3 min. Expect different times on LinuxONE; do not extrapolate.

Then commit the evidence so the dashboard platform panel shows it:

```bash
git add reports/linuxone reports/benchmarks
git commit -m "LinuxONE run: <host>, <date>"
git push
```

## 4. Screenshots for the submission

1. `uname -m` → `s390x`, plus `lscpu` showing the allocation.
2. Test summary `Ran 39 tests … OK`.
3. `train_models.py` JSON summary for each backend.
4. `compare-*.json`: maximum prediction difference and Spearman correlation against the laptop models.
5. `benchmark.py run` summary: per-scan decision p50/p99 and events per second.
6. The dashboard platform panel with the laptop and LinuxONE columns filled from those files.

## 5. Dashboard

Streamlit needs pyarrow, which has no s390x wheel. Run the dashboard on a laptop against the committed LinuxONE artifacts, or on LinuxONE only if pyarrow is available from the OS/conda:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
ssh -L 8501:127.0.0.1:8501 <user>@<linuxone-host>     # from the laptop, then open http://localhost:8501
```

Do not expose the port publicly; the app has no authentication.

## 6. What the results can and cannot claim

- `benchmark.py` measures single-process, in-memory stages with data preloaded. It excludes network, UI and persistence.
- `cpu.nnpa_facility_listed` records whether the CPU advertises the on-chip AI accelerator facility. It does not show that any model used it. Claim acceleration only from a separately configured and measured run.
- Laptop and LinuxONE allocations differ; report both with their CPU/memory facts and no speedup claim unless the comparison is like for like.
- Layer A labels are real next-month report recurrence, not medicine safety. Layer B labels are simulated.

## Publication and recovery

`refresh_data.py` rebuilds from `data/raw/*_all.xlsx` in a clean staging directory, validates all derived datasets, hashes sources/outputs/builder code, and atomically switches `data/CURRENT`. A failed refresh keeps the previous snapshot. A single-writer lock protects refresh; after a crash, confirm no refresh is running before deleting `data/.refresh.lock`. Restore an earlier verified snapshot with `snapshot_store.publish_pointer(ROOT, snapshot_id)`. A new snapshot needs a new training bundle (`model_foundation.py`) and new models; the committed models are bound to snapshot `6e881f22…`.

## Deferred replay experiment

`inspection_stream.py`, `replay.py`, and `tests/test_inspection_stream.py` hold the earlier 30-minute persistent replay, including hypothetical flooding. `replay.py demo` now refuses to reuse an existing event database (pass `--resume` deliberately). It is not the primary workflow.
