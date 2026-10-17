# Is the scan model undertrained?

We tested this rather than assuming that more examples would help. `src/scan_learning_curve.py` trains the same scikit-learn model-selection pipeline on 30, 100, 300, and 900 episodes **per seen scenario**, then evaluates each selected model on one fixed 700-episode scripted test set and the fixed 1,100-case nuisance challenge. The training generator, validation threshold rule, test seed, and challenge are recorded in [`outputs/scan_learning_curve.json`](../outputs/scan_learning_curve.json). The challenge was created after inspecting the original model, so this is a diagnostic stress test, not blinded validation.

| Training episodes | Fixed scripted test AP | Benign challenge alerts / 700 | Missed copied-ID cases / 400 |
|---:|---:|---:|---:|
| 150 | 0.828 | 300 | 200 |
| 500 | 0.831 | 400 | 100 |
| 1,500 | 0.827 | 300 | 200 |
| 4,500 | 0.827 | 300 | 200 |

The scripted AP is flat while the stress failures persist. More draws from the same narrow generator are **not** evidence of a more dependable copied-ID detector. The selected thresholds also move substantially as the synthetic sample changes. Four copied-ID/benign mechanism pairs in the challenge have identical values for every current scan-model feature, so no amount of training on those nine fields can distinguish their causes.

The operational change is deliberately conservative: `rank_candidates` still shows the trained score for research, but it no longer adds `SCAN_MODEL_ALERT` to inspector reasons. The declared travel/burst rule alone creates scan review flags, and flagged rows now include `SCAN_CAUSE_UNVERIFIED`. The interface calls the trained output a **synthetic model score**, not a counterfeit probability. This improves how the current evidence is used; it does not make the rule's synthetic precision a field estimate.

To improve the model itself, the next dataset needs independently verified physical-pack outcomes and richer observations: trusted server receipt time, scanner clock status, location accuracy, authenticated scanner identity, reasons for rescan, and ideally a pack-bound identifier that cannot simply be copied from a printed code. These fields must be collected in the intended workflow and tested on independent sites and times before a model can claim field dependability. IBM Z can process more scans, but it cannot recover information the events never contain.

The separate [field model path](FIELD_MODEL.md) now accepts adjudicated physical-pack cases with scan-quality telemetry, checks site and time separation, trains a new model, and keeps review flags off unless the recorded evidence passes a conservative gate. There are no such cases in this public repository, so this path has no measured field performance yet.

Reproduce the diagnostic experiment with `python -m src.scan_learning_curve`. Do not select a new model or threshold using challenge v1 and then describe its result on v1 as held out.
