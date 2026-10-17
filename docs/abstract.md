# BatchGuard: abstract

**Team:** _<team name>_ · IBM Z Datathon 2026

Drug inspectors in India can sample only a handful of batches each week. CDSCO publishes monthly lists of medicine batches that were reported Not of Standard Quality (NSQ) or spurious, but an inspector cannot act on these lists directly. BatchGuard turns them into one ranked, explained answer: *which batches to sample first within this week's capacity.*

BatchGuard combines two clearly separated layers:

- **Real history (Layer A).** This layer covers 2,551 records from 14 monthly CDSCO workbooks, July 2025 to August 2026. A model predicts whether a manufacturer seen earlier will be reported again next month. On the held-out months July and August 2026 it reaches an average precision of 0.098, against 0.067 for the strongest baseline (bootstrap 95% CI of the gain: 0.005 to 0.068). At a budget of 25 manufacturers it captures 21 later reports, against 13.1 for the best baseline.
- **Simulated verification scans (Layer B).** Pack scans are generated on real reference batches. A declared rule flags impossible travel and repeated-pack bursts: 80.8% recall and 100% precision on simulated test episodes. The rule beats our trained model on families the model never saw, so the rule drives alerts and the model is shown beside it.

The queue shows historical risk, scan anomaly and evidence quality as separate columns, with reason codes and source documents. At a budget of 100 out of about 190 batches per month, the fused queue captures 85% of simulated clones and 79% of real recurring-manufacturer batches. Ranking on scans alone captures 87% and 37%; ranking on history alone captures 62% and 100%.

The pipeline has a reproducible workload for comparison on an IBM LinuxONE (s390x) host with scikit-learn and IBM Snap ML. No LinuxONE result has been recorded yet; current timing results are from an x86 laptop only. The synthetic scale test reaches about 600 to 730 events per second on that laptop, depending on the workload profile and backend.

The reported laptop results were measured. Layer B data and traffic volumes are simulated. The real label is report recurrence, not medicine safety. Humans make every sampling decision.
