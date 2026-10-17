# BatchGuard

Helps a drug inspector choose which medicine batches to sample first within weekly capacity.

- **Layer A — real data:** CDSCO NSQ/spurious reports, July 2025–August 2026 (2,551 records). A model ranks manufacturers by chance of being reported again next month.
- **Layer B — simulated scans:** pack-verification scans; a rule flags copied packs (impossible travel, bursts).
- One ranked queue keeps history, scan and evidence values separate, with reasons. Humans decide; an anomaly is not proof of counterfeiting.

## Results (held-out data)

| Layer A, Jul–Aug 2026 | Average precision | Reports captured, top 25/month |
|---|---:|---:|
| Trained model | **0.098** | **21** |
| Legacy index | 0.067 | 9.5 |
| Most past records | 0.055 | 12.0 |
| Random | 0.018 | 1.1 |

Layer B: the trained scan model (recall 73%) does not beat the rule (81%), so the rule drives alerts and the model is shown alongside. Model cards: `models/*/model_card.json`.

## Run

```bash
python -m pip install -r requirements.txt
python train_models.py --output models/my-run            # --backend snapml for IBM Snap ML
python benchmark.py run --models models/baseline-v1
python -m streamlit run app.py
python -m unittest discover -s tests
```

## LinuxONE

PyPI has no s390x wheels for numpy/scipy/pandas/scikit-learn; use the host's preinstalled stack, then:

```bash
git clone https://github.com/padmesh6119/BatchGuard.git && cd BatchGuard/BatchGuard
python -m pip install "openpyxl>=3.1.5" && python -m pip install --no-deps snapml
PYTHON=python ./linuxone_run.sh
```

`linuxone_run.sh` runs tests, trains both backends, compares predictions with the laptop models, benchmarks, and saves everything in `reports/linuxone/`.

## Built with

[pandas](https://pandas.pydata.org) · [scikit-learn](https://scikit-learn.org) · [IBM Snap ML](https://www.zurich.ibm.com/snapml/) · [Streamlit](https://streamlit.io) · [openpyxl](https://openpyxl.readthedocs.io)
