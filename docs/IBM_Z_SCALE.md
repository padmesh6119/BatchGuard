# IBM Z / LinuxONE: what the synthetic scale test can prove

BatchGuard needs a reason to run on IBM Z beyond the fact that it can. The question is whether its **actual decision path** meets a target scan rate, latency, and operating cost better on LinuxONE than a credible alternative. No LinuxONE measurement exists in this repository yet. IBM describes [Snap ML and the Integrated Accelerator for AI](https://www.ibm.com/products/linuxone/ai-processor), including acceleration for random forest, extra trees, and gradient boosting. BatchGuard's currently selected Snap ML scan model is **logistic regression**; these project measurements do not establish use of that accelerator.

## Two separate synthetic datasets

- [`data/synthetic/challenge_v1.jsonl`](../data/synthetic/challenge_v1.jsonl) tests detection failure mechanisms. It has hidden physical-pack truth and intentionally indistinguishable positive/benign pairs. Its artificial class mix cannot estimate field precision.
- `src/scale_benchmark.py` generates scan traffic **without accuracy labels** and replays every event through `rank_candidates`, maintaining a six-hour active window and periodically sorting the capacity queue. It records an event-stream SHA-256 so the exact workload can be checked across hosts. The traffic profiles are assumptions for capacity testing, not observed pharmacy behavior.

The routine profile's 100-case cycle is 94 one-scan candidates, four three-scan repeats, one 12-scan burst, and one two-scan location conflict. The repeat-heavy profile is 40, 40, 10, and 10 respectively. Source IDs are asserted, not authenticated. The synthetic product and batch IDs are unique per candidate; 80% of manufacturer text values cycle through earlier CDSCO signatures and 20% are synthetic unseen signatures. No synthetic scan is treated as a real inspection observation.

## Measured x86 baseline

One Python process on the recorded x86 laptop, with the existing model artifacts and a queue snapshot every 500 scans:

| Profile, events, repeats | scikit-learn | IBM Snap ML on x86 |
|---|---:|---:|
| Routine, 5,000, 2 | 666 events/s | 713 events/s |
| Repeat-heavy, 5,000, 2 | 611 events/s | 671 events/s |
| Routine, 100,000, 1 | 607 events/s | not run |

The 100,000-event run spanned about 23 hours of **synthetic event timestamps** but took 165 seconds to replay. It ended with about 21,600 active candidates after six-hour eviction and peaked at about 199 MiB process RSS. Building its monthly history context took 4.6 seconds before stream timing. Its per-event decision p99 was about 2.6 ms, while periodic full queue snapshots reached about 76 ms at p99. The measured stream rate includes synthetic event generation, hashing, validation, feature extraction, model scoring, decision logic, and periodic in-memory queue snapshots. It excludes network intake, durable storage, concurrent clients, fault recovery, and a sustained full-day run. The backend comparison on one laptop is not an IBM Z speedup.

Daily-volume requirements are simple arithmetic: 1 million scans/day averages 11.6/s, 10 million averages 115.7/s, and 100 million averages 1,157.4/s. A 10× busy-hour assumption multiplies those rates by ten. The current single-process laptop run clears the first two **averages**, but not a 100-million/day average or a 10-million/day 10× peak. Parallel x86 processes could also change that result; no platform necessity follows from this one-process test. Actual peak shape, alert burden, reliability, deployment proximity, cost, energy, and privacy requirements remain unknown.

## Run the same test on LinuxONE

Use the project environment and model artifacts on the LinuxONE host, then run:

```bash
python -m src.scale_benchmark --events 5000 --repeats 2 --profile routine --backend sklearn
python -m src.scale_benchmark --events 5000 --repeats 2 --profile repeat_heavy --backend sklearn
python -m src.scale_benchmark --events 5000 --repeats 2 --profile routine --backend snapml
python -m src.scale_benchmark --events 5000 --repeats 2 --profile repeat_heavy --backend snapml
python -m src.scale_benchmark --events 100000 --repeats 1 --profile routine --backend sklearn --output outputs/scale_linuxone_sklearn_routine_100k.json
```

The JSON reports record host architecture, package versions, model choice and threshold, source-data manifest, workload hash, latency percentiles, throughput, active candidates, and process RSS. To compare a matched pair after copying the LinuxONE result into this checkout:

```bash
python -m src.scale_compare outputs/scale_laptop_sklearn_routine.json outputs/scale_linuxone_sklearn_routine.json
```

The comparator rejects mismatched profiles, workload hashes, **decision hashes**, model choice, threshold, and source manifest. It reports an **observed ratio**, not proof of accelerator use. A serious platform decision also needs sustained concurrent testing, hardware utilization evidence, and a tuned x86 baseline under the same service-level and cost constraints.
