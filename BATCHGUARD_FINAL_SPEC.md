# BatchGuard: final product specification and delivery status

Version: 1.0. Reviewed: 17 October 2026. Scope: IBM Z Datathon 2026 submission.

**Final idea:** BatchGuard helps medicine inspectors decide which batches to sample first within their weekly capacity. It combines real CDSCO quality-report history with clearly labeled simulated pack-verification scans, explains each priority, and runs the scoring and evidence workload on the assigned IBM LinuxONE environment.

This is the single product specification for further work. It supersedes conflicting historical-only and flooding-centered directions in earlier plans. Those documents remain audit records. Product scope is frozen here; correcting defects, measuring results, updating data coverage, and selecting validated model parameters are implementation work within this scope. A different product direction requires an explicit user decision.

## 1. Decision: are we on the right idea?

**Yes: proceed with this inspector decision product. The current implementation is not yet the finished submission.**

There was a partial deviation. The current dashboard became a retrospective review of published findings. The combined scan/history backend exists separately, but the dashboard does not yet deliver the original seven-part screen. Earlier flooding experiments also received more attention than the core inspector workflow needed.

The review improved important foundations: pack identity, retry handling, provenance, reproducibility, temporal splits, and unique capacity-limited candidates. It did not establish superior real-world detection, optimal fusion, or a winning submission. The next work is integration and proof, not another product pivot.

The competitive objective is a top-three submission. Our proposed strength is the complete chain from official evidence and current scan signals to a limited sampling decision, with transparent evaluation and actual IBM Z execution. Existing commercial systems already advertise explainable scan alerts; we must demonstrate our specific workflow rather than claim exclusive novelty.

## 2. Problem, user, and solution

**Problem:** inspectors have limited sampling and laboratory capacity. Published quality failures provide useful history, while newly emerging suspicious batches may have no history. Reviewing every report and scan manually does not produce a practical weekly sampling order.

**Primary user:** a drug inspector or inspection coordinator choosing which medicine batches warrant laboratory follow-up.

**Decision:** “Given capacity N, which unique batches should I review and sample first, and what evidence supports each choice?”

**Solution:** one screen with a ranked batch queue, separate historical/scan/evidence signals, a capacity control, and traceable evidence. Historical records are context; simulated scans demonstrate the live decision process. A human decides whether to sample. Laboratory and investigation outcomes determine medicine quality and authenticity.

BatchGuard does not automatically block medicine, issue legal orders, or declare counterfeiting. A scan anomaly is a review signal. No previous failure record means missing historical evidence, not safety.

## 3. Data reviewed and what it contributes

### 3.1 Existing active data

The validated active snapshot covers **July 2025–August 2026**, with 2,554 master records and **2,551 analytical records** after three confirmed duplicate exclusions: 686 central NSQ, 1,821 state NSQ, and 44 spurious-report records.

Workbook/sheet/row provenance is implemented. The previous foundation verification traced all 2,554 master records to source workbook rows. This is local traceability; individual workbook download origins and publication dates are not yet fully verified.

Manufacturer text signatures are not verified legal entities. Failure-category mapping remains provisional. Missing fields, disputed records, and unavailable sources remain visible rather than being silently guessed.

### 3.2 Newly supplied PDF folder

All **32 PDFs, totaling 250 pages**, were text-extracted and profiled for report coverage, source category, revision content, and data-quality issues. This is a document-level assessment, not a completed row-by-row extraction, reconciliation, or visual verification of every page. The six-page June 2025 central report was also examined in detail; its first page was visually checked.

| Report month | Central PDF | State PDF | Spurious PDF | Revision PDFs |
|---|---|---|---|---|
| September 2024 | Present | Present | Present | None in folder |
| October 2024 | Present | Present | Present | None in folder |
| November 2024 | Present | Present | Present | One |
| December 2024 | Present | Present | Not in folder | None in folder |
| January 2025 | Present | Present | No standalone file | Two |
| February 2025 | Present | Present | Present | None in folder |
| March 2025 | Present | Present | Present | None in folder |
| April 2025 | Present | Present | Present | None in folder |
| May 2025 | Present | Present | Present | One |
| June 2025 | Present | Present | Present | None in folder |

These add **ten earlier months**. Once validated and integrated, the combined history can cover **September 2024–August 2026: 24 months**. They are not currently part of the active snapshot or prepared model bundle. Missing files do not prove that no incidents occurred.

The June 2025 central PDF contains 55 numbered records, with product, batch, manufacturing/expiry dates, manufacturer/address, failure details, and reporting laboratory. Some entries contain multiple batches. Other PDFs include manufacturer replies, investigation remarks, and state reporting gaps.

### 3.3 Important findings from the raw PDFs

| Finding | Required treatment |
|---|---|
| November revision names Tofacitinib batch `4F30009`; January revisions identify TELMA AM `5240367` and Dmex `4D077301` | Link revisions to their original records. Preserve status changes and investigation wording; do not append them as unrelated new failures. |
| `2025-05_revised.pdf` says May in its heading but January in its subtitle | Mark the report-month conflict for review against official publication context. Do not choose a month silently. |
| September 2024 state report has an August reference in its non-reporting footer | Preserve the conflicting source text; do not turn it into an assumed September availability fact. |
| State reports list authorities that did not submit data | Treat reporting availability as coverage information. Raw failure counts cannot establish which state is safest or riskiest. |
| Manufacturer spelling/address variants occur, including “Private Limitated” | Use reviewed company-and-unit aliases with original text retained. Avoid blind name-only merging. |
| Batch identifiers and records wrap across lines/pages; multiple batches can share one entry | Preserve PDF page/record provenance and review ambiguous segmentation before creating sampling candidates. Simple line counts are not record counts. |
| “Under Investigation,” manufacturer denial, and “purported spurious” wording occur | Keep allegation, investigation, and confirmed outcome distinct. Do not assign a manufacturer's legal responsibility from an unverified label. |
| Devices, cosmetics, and medicines appear together | Classify product scope. The primary queue targets medicines; retain other records separately. Do not exclude a medicated shampoo merely because it is called shampoo. |

### 3.4 How more data helps, and what remains missing

Earlier history can improve recurrence features, reviewed manufacturer matching, and the number of chronological evaluation periods. Improvement must be measured; adding records does not guarantee better predictions.

The highest-value additional sources, if obtainable, are:

1. **All sampled batches and their pass/fail outcomes:** a denominator for learning quality risk beyond recurrence in failure lists.
2. **Real verification events with confirmed normal/clone outcomes:** external validation for Layer B.
3. **Current batch availability and inspector sampling/outcome records:** a real candidate universe and measured inspection yield.

These sources are not assumed available and do not block the explicitly limited hackathon demonstration. The supplied PDFs do not contain live verification scans or a representative population of safe medicines.

## 4. Fixed end-to-end workflow

1. Obtain official reports and record URL, release date, revision identity, retrieval time, and file hash.
2. Extract and reconcile records, retain raw text/page references, review ambiguous identities, and publish one validated historical snapshot.
3. Replay labeled simulated verification events in real time, with separate event IDs, pack IDs, batch identity, source IDs, timestamps, and coarse locations.
4. Validate and persist events. Identical delivery retries count once; conflicting event-ID reuse is rejected.
5. Build observable pack-level features within one declared window. Current training/inference foundation uses **six hours**.
6. Attach only historical evidence available before the decision, produce the three separate signals, and aggregate into unique batch candidates.
7. Rank candidates, apply the inspector's capacity N, and expose reasons and evidence.
8. Let the inspector record a review/selection status and export the selected evidence. A sample is not marked collected or tested without a recorded action/outcome.
9. Save evaluation and platform artifacts using the same snapshot, model/policy, workload, and environment identifiers.

The active demonstration queue is built from batches observed in the scan workload. It is not a complete list of every marketed batch. Published-finding follow-up remains available as supporting evidence, clearly distinguished from prospective sampling recommendations.

Candidate identity is product + batch + reviewed manufacturer/unit identity, with an explicit unresolved-identity fallback. One batch contains many legitimate packs. Scans of different packs from one batch in different districts are normal distribution, not by themselves a clone pattern. Deduplication must not merge unrelated manufacturers' coincident batch numbers.

## 5. Three signals, model targets, and priority

| Signal | Meaning | Boundary |
|---|---|---|
| Historical risk | Earlier reported recurrence and relevant manufacturer/product evidence | Display as a historical priority index, not medicine-defect probability. |
| Scan anomaly | Observable copied-pack patterns, unusual travel/timing, or repeated-pack bursts | Simulated behavior; not chemical-quality testing or proof of counterfeiting. |
| Evidence quality | Corroboration, provenance, completeness, and identity limitations shown separately | Current numeric implementation measures asserted source diversity only; authenticated independence is not implemented. |

### Layer A: historical model

The prepared target is **next-month NSQ report recurrence among previously observed manufacturer text signatures**. A zero label means no next-month report, not a safe medicine. New manufacturers are outside this conditional model's historical candidate universe; show that limitation explicitly.

Seven prepared features cover prior records, months, products, recent reporting, time since last report, and unresolved failure records. Features must use information available before the target decision. Publication dates and version availability must replace collection-month proxies where verified; later revisions cannot be backdated into earlier predictions.

### Layer B: scan model

The target is **simulated clone behavior within a batch observation episode**. Nine prepared features cover unique events/packs, per-pack counts and source counts, distance, speed, burst counts, observation span, and delivery retries. Identifiers, scenario names, labels, and known failure outcomes are excluded from model inputs.

Benign cases include repeat scans, different-pack distribution, and plausible travel. Clone cases include copied serials and bursts. Delayed synchronization and slow copies are reserved scenario families. Some legitimate and copied-code behavior is observationally indistinguishable; record misses and false alerts.

### Training and fusion decisions

Fit a small, bounded comparison of a linear baseline and a compact tree model, against existing rules/indices. Choose parameters and thresholds on validation data. Prefer the simplest model that demonstrates useful held-out performance and runs reliably on the assigned platform. No large language model is needed for event scoring or reason generation.

The current untrained fusion is:

`priority = 0.50 × history + 0.35 × scan + 0.15 × corroboration × has_scan_signal`

History currently uses the legacy 60/25/15 descriptive index. Scan scores are 100 for the travel heuristic, 70 for the burst heuristic, otherwise zero. Corroboration is 0/50/100 for one/two/at least three asserted sources. These are baseline choices, not validated probabilities or optimal weights.

Evaluate fusion against history-only and scan-only under identical candidate budgets. If fusion adds no demonstrated lift, retain the strongest validated ranking and show both layers as evidence. Do not force a misleading combined-model benefit. Do not suppress credible clone signals solely because a manufacturer has no history.

The final implementation must reconcile the older 30-minute persistent replay policy with the six-hour shared training/inference contract. Old benchmark results do not validate the newer policy.

## 6. Final dashboard: one inspector screen

The queue occupies most of the screen. Controls and evidence support that decision; no separate page should be necessary to understand why a batch is selected.

```text
BatchGuard                       Real data / simulated scans banner
Weekly sampling capacity [ N ]   Selected N / available candidates
------------------------------------------------------------------
RANKED BATCH QUEUE                         LIVE SIMULATED SCAN FEED
Batch | Product | Manufacturer | State     Normal repeat: no escalation
History | Scan | Evidence | Priority       Copied pack: evidence updates
Reasons | Review status                    Queue priority changes
------------------------------------------------------------------
HISTORY COVERAGE / CAPTURE AT N             PLATFORM MEASUREMENTS
Baselines, split and limitations           Laptop | assigned LinuxONE
------------------------------------------------------------------
Select a row: evidence drawer with timeline, map and source records
```

| Required element | Final visible behavior and acceptance |
|---|---|
| 1. Persistent banner | Initially: **“Layer A: REAL CDSCO data (Jul 2025 to Aug 2026). Layer B: SIMULATED scans.”** Also: **“Scan anomalies are not proof of counterfeit.”** When earlier PDFs are actually integrated, update the date range from the active manifest; never announce unintegrated coverage. |
| 2. Ranked queue | One row per unique candidate. Show batch, product, manufacturer, state, history, scan anomaly, evidence quality, priority, reasons, and review status. Unknown state is visible. “State” means the sampling/scan jurisdiction; manufacturer address state is separate evidence. |
| 3. Capacity slider | N is the maximum number of unique batches selected this week, not event count and not an obligation to fill every slot. Show selected/available counts. A coverage readout refers to a named held-out evaluation at N; live expected failures remain “Not estimated” without supporting outcomes. |
| 4. Live feed | Replay arrives visibly. A retry does not create another event or candidate; a benign repeat creates no clone escalation. The same pack in distant districts within an implausible interval gains a reason and rises in a controlled demo. Legitimate different-pack distribution remains quiet. |
| 5. Evidence drawer | Scan timeline, coarse district map, number of asserted sources and verification status, manufacturer history, original evidence links/page or workbook rows, score/model version, and data-quality limitations. Map locations from replay remain labeled simulated. |
| 6. Evidence charts | Exact recurrence finding with split and definition; capture-versus-baseline chart at equal N; false alerts and missed scenarios. Keep historical manufacturer coverage distinct from batch-level simulated capture. |
| 7. Platform panel | Measured throughput and p99, plus workload, measurement boundary, host architecture, backend/model and software versions. Laptop and LinuxONE columns show measured values or “Not measured.” Never fill absent measurements with estimates. |

Reason codes include clone travel pattern, repeated-pack burst, manufacturer history, batch report reference, reference coverage unknown, and sample status unknown. **“No sample yet” is allowed only when a recorded sample lifecycle supports it.** Source count must not be described as independently verified organizations without verification.

## 7. IBM Z / LinuxONE architecture and efficiency

**IBM LinuxONE hosts the actual decision workload:** validated data loading, event persistence, shared feature extraction, trained inference where available, candidate ranking, evidence outputs, and benchmark collection. A locally rendered dashboard may consume those outputs, but its connection and execution boundary must be explicit. A LinuxONE logo or architecture check alone is not deployment proof.

Use the existing Python engine and Streamlit rather than a new application stack. Start with the existing SQLite durability component adapted to the shared scoring contract. A separate authenticated API is needed only if the chosen deployment exposes an ingestion boundary; an isolated in-process demo does not require a new microservice system.

Efficiency requirements within this scope:

- Load/cache validated historical context by snapshot, rather than rebuilding it per scan.
- Maintain bounded time-window state and incremental per-pack summaries where practical; profile pairwise distance calculations rather than assuming they scale.
- Update affected batch candidates instead of reranking/reloading the full historical dataset for every delivery.
- Separate event acceptance, feature extraction, model inference, queue materialization, and UI rendering in measurements.
- Use compact models and deterministic reason codes. No per-scan LLM calls, blockchain, Kafka, or distributed cluster requirement.
- Record queue-update cost, memory/CPU, persistence behavior, retry handling, and restart recovery under a declared workload.

IBM documents Snap ML availability for LinuxONE/Linux on Z and s390x. Verify the actual Python/package combination on the assigned host. Prefer an IBM-supported environment/container if available. Train and evaluate the portable baseline, then test Snap ML execution of a supported model on LinuxONE. Record the actual backend; a fallback CPU implementation remains clearly identified.

Telum or other accelerator usage is conditional on actual hardware access, supported model configuration, and measured execution. Snap ML installation or an s390x machine does not prove accelerator use. LinuxONE execution does not imply a z/OS deployment.

### Required platform proof

1. Verify assigned host identity, architecture, OS, CPU allocation, memory, Python and dependency versions.
2. Run ingestion, tests, the selected model/policy, and queue production on that host; retain commands and logs.
3. Replay the **same hashed input**, snapshot, model/policy, event order and seed on laptop and LinuxONE.
4. Report warm-up policy, concurrency, repetitions, duration, event counts, errors, throughput and p50/p95/p99. Distinguish processing time from queue-refresh and end-to-end latency; include resource allocations.
5. Use sufficiently long repeated runs and a workload sweep for stability. Repeating synthetic events can test throughput, but does not create new detection evidence.
6. Validate retries and restart recovery. Save raw measurements, predictions, queue outputs and environment manifests.
7. Report speedups only when supported by comparable measurements. Different machines/resources remain disclosed; do not manufacture a LinuxONE performance advantage.

IBM's platform role is reliable execution of a measurable decision workload. Efficiency and accelerator claims are results to establish, not prerequisites to invent.

## 8. Current implementation: verified status

| Component | Built now | Remaining |
|---|---|---|
| Historical ingestion | Fourteen workbooks; parsers, conservative normalization, duplicate checks and review reports | Earlier PDF extraction/reconciliation; full official URL/release/revision manifest; reviewed aliases and product scope |
| Snapshot reliability | Clean staging, hashes, validation, atomic publication, single-writer lock, pinned readers and rollback | Extend provenance to PDFs and verified publication-time availability |
| Historical analysis | Descriptive index, retrospective unique follow-up queue and chronological manufacturer-coverage baselines | Fit recurrence model; repeat evaluation after data corrections |
| Scan events | Pack/event/source separation, validation, deterministic scenarios; durable retry handling in experimental SQLite engine | Connect durability to shared six-hour features and production dashboard path |
| Training foundation | Immutable feature/label/metadata files; chronological splits; disjoint pack IDs; held-out scenario families; hashes | Training script, installed backend, fitting, validation selection, export and model loading |
| Combined backend | `decision_core.py`: three signals, reasons and unique capacity-limited queue | Model integration, validated ranking, source/identity quality detail, lifecycle and UI integration |
| Dashboard | Historical review tabs, capacity control, evidence downloads, coverage and data-quality displays | Complete all seven combined-screen elements; feed, map/drawer and platform panel |
| Tests | 31 existing tests; previous full run passed | Integration checks for final screen, shared persistence/model path and assigned platform |
| Platform | Headless replay commands, environment recording and LinuxONE runbook | Actual assigned-host execution, compatibility verification and matched benchmarks |
| Submission | Existing concept/abstract and review documents | Final results, recording, pitch, honesty slide and submission-rule checks |

**No model has been fitted.** The prepared manifest explicitly says `training_performed: false`. Neither scikit-learn nor Snap ML is installed in the current application environment, and no fitted model artifact was found during this review. No actual LinuxONE run has been verified.

The current prepared bundle is `BatchGuard/data/training/foundation-ready-v1/`:

| Task | Training | Validation | Test |
|---|---:|---:|---:|
| Historical recurrence examples | 6,760 | 1,438 | 3,370 |
| Simulated scan episodes | 500 | 165 | 231 |

Historical targets train through May 2026, validate on June, and reserve July–August for testing. These counts are examples, not independent manufacturers or real counterfeit cases. The current snapshot ID is `6e881f22c3016444c02b49d2fc852b2b81975aaa57d24879da0453ee404698f5`.

Earlier PDFs, revised labels, aliases or publication-aware features require a **new versioned bundle**, not editing this one. Retain the latest calendar test period and do not tune against its outcomes. Existing report outputs can refer to older snapshots; regenerate final artifacts from the selected snapshot before submission.

## 9. What has actually been measured

**Historical finding:** history through January 2026 versus February–August 2026 contains 122 previously seen manufacturer-text NSQ records among 1,341 later NSQ records: **9.10%**. This is exact-text recurrence under that split. It is neither a universal predictive ceiling nor proof that live scans work. Recompute after adding earlier data and reviewed aliases.

**Earlier simulated replay:** 1,780 deliveries, 1,760 accepted events and 20 retries; 120 active candidates. At N=10, fused and scan-only each captured ten of 60 simulated clone candidates; history-only captured four and volume ranking zero. **Historical fusion demonstrated no lift over scan-only.** Twenty slow-clone candidates were missed by the older detector. This is a hand-designed, older 30-minute experiment, not evaluation of the prepared trained models or final six-hour policy.

**Earlier local benchmark:** approximately 620 deliveries/second and 3.55 ms p99 on x86_64, from a roughly 2.87-second sequential run. Scope includes local validation, SQLite transaction, features and audit persistence per delivery; excludes reference loading, network and UI. Queue computation is separate. This is a preliminary local measurement, not a sustained-load result or an IBM Z result.

No measured real-world counterfeit accuracy, prospective inspection yield, commercial superiority, accelerator speedup, or trained-model uplift exists yet.

## 10. Evaluation required for the final output

| Question | Fair comparison and output |
|---|---|
| Does earlier history help? | Chronological recurrence ranking against legacy index, past-report count and random expectation. Show candidate universe, reporting coverage and unseen-manufacturer share. |
| Does the trained scan model help? | Same observable inputs/window as the rule baseline. Report precision, recall, PR-AUC where supported, false positives and negatives, and held-out-family results. State the episode-level unit. |
| Does the queue use capacity better? | Same batch candidates, decision time and N for history-only, scan-only, fused, volume and random baselines. Report capture at N and selected false alerts. Use episode/run-level uncertainty where feasible. |
| Does it operate in real time? | Detection delay, accepted/error/retry counts, queue-update latency, sustained throughput and processing p99 under a declared load. |
| Does IBM Z actually run it? | Saved assigned-host execution and matched benchmark artifacts, including model/backend versions and resource allocations. |

For simulated candidate capture, `capture@N = labeled clone candidates selected / all labeled clone candidates eligible at that decision`. Also show `precision@N = labeled clone candidates selected / selected labeled candidates`. Neither means real medicine failures caught per laboratory test.

Do not report false positives per 1,000 genuine scans by reusing episode-level counts; calculate a separate event-level metric if needed. Freeze policy/model selection before final testing. Preserve hard cases and failed runs instead of replacing them with easier test scenarios. If observed results do not beat a baseline, report that result and retain the stronger validated method.

## 11. Remaining work in dependency order

| Order | Work package | Completion evidence |
|---|---|---|
| 1 | Validate and integrate earlier PDFs; reconcile revisions, product scope, aliases and source availability | Source manifest; row/page reconciliation; reviewed exceptions; new immutable snapshot; truthful coverage banner |
| 2 | Regenerate publication-aware training data where source dates allow; preserve held-out periods | New hashes, feature contract, split manifest and explicitly documented residual timing uncertainty |
| 3 | Fit/evaluate compact historical and scan baselines; export selected artifacts | Reproducible training command, validation choices, final comparison, model/input hashes and inference checks |
| 4 | Join persistence, shared features, inference and candidate selection; add minimal persisted review/sample status | Retry/restart checks; one candidate per sampling action; reproducible three-signal output and status evidence |
| 5 | Integrate the seven-part single-screen dashboard | Benign/clone demonstration; N changes selection; evidence drawer/map; measured charts; no invented state or sample status |
| 6 | Execute and benchmark on assigned LinuxONE | Actual platform logs, working backend/model, raw repeated measurements and laptop comparison |
| 7 | Freeze and package the demonstration | Clean rerun, backup recording, result artifacts, honesty slide, pitch/video and verified submission requirements |

Platform access and compatibility checking should begin as soon as access arrives, alongside these packages. LinuxONE execution must not be left as a last-minute logo addition. This document authorizes no implementation by itself; the current requested deliverable is this specification.

## 12. Scope boundaries and unresolved risks

Core delivery includes normal/clone simulation, basic durable ingestion, minimal human review status, and honest evaluation. It does not require a national deployment or solving every production-security issue in the original audit.

| Audit concern | Final disposition |
|---|---|
| Unsupported claims, stale metrics and conflicting roadmaps | This specification controls direction; final results must come from versioned artifacts. |
| Provenance, revisions, missing data, duplicates and identity | Snapshot/row tracing exists; PDF/release/alias reconciliation is required. Unresolved evidence remains explicit. |
| Unvalidated taxonomy and severity | Keep raw failure text; do not introduce an unsupported clinical severity score. |
| Simulator leakage, pack confusion, retries and unknown-reference penalties | Preserve shared features and separate labels; test pack identity/retries; absence is coverage information. |
| Fusion, capacity and different evaluation units | Validate equal-budget candidate ranking; expose signal meanings and units. |
| Temporal/snapshot consistency and refresh recovery | Reuse implemented immutable snapshots; add publication-time availability and policy/model binding. |
| Operational boundaries and action audit | Reuse durable state; persist minimal human actions. Secure any exposed ingestion interface; do not claim production readiness. |
| Source independence and adversarial flooding | Disclose asserted sources. Authentication at an exposed boundary is basic hygiene; sophisticated flooding/Sybil research is deferred. |
| Platform compatibility, reproducibility and testing | Verify actual s390x environment, pin the proven dependency set, and retain commands/artifacts. |

Deferred: flooding as the headline, blockchain, a new medicine-authentication registry, nationwide rollout, hospital signals, graph/deep models, autonomous enforcement, complete laboratory case management, and LLM-generated per-scan explanations. Maps are included because the user explicitly requires district evidence; decorative animation is unnecessary.

## 13. What judges should see and receive

The main demonstration follows one decision:

1. Set weekly capacity and show the real/simulated banner.
2. Show a normal repeat and different-pack distribution without clone escalation.
3. Replay the same simulated pack from distant districts in an implausible interval. Show its scan signal, reasons and queue movement.
4. Open its evidence drawer: timeline/map, asserted source count, history and original records.
5. Change N and show unique selected batches plus the named evaluation result at that budget.
6. Show honest baseline results, difficult misses, and actual LinuxONE measurements.
7. Record the human review decision and export evidence. Do not imply that this establishes counterfeiting.

The delivery package contains the working combined dashboard, portable source and training/evaluation commands, versioned data/model manifests, baseline results, actual laptop/LinuxONE artifacts, a concise honesty slide, and the demo video/YouTube link if required by the verified submission rules. Confirm organizer eligibility, pre-event-work policy, judging criteria, deadline, and artifact requirements; they are not established by this specification.

**Completion means:** the complete seven-part flow works, model claims have evaluation evidence, the backend actually executes on assigned LinuxONE, and every displayed result can be traced to an artifact. A stronger pitch cannot substitute for these conditions.

## 14. References and implementation map

Official sources checked for this review:

- [CDSCO NSQ entry page](https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/) and [public NSQ/spurious portal](https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug).
- [CDSCO legacy alerts archive](https://www.cdsco.gov.in/opencms/opencms/en/Notifications/Alerts/): publication dates, older alerts and revisions. For example, June 2025 central/state alerts are listed with an 18 July 2025 release date.
- [IBM Snap ML on IBM Z/LinuxONE](https://ibm.github.io/ai-on-z-101/snapml/): documented platform availability and conditional accelerator support; local compatibility remains to be measured.
- [IBM Z Datathon 2026 organizer](https://www.starhacks.org/ibm-z-datathon-2026): Real-Time AI for Critical Decisions theme and LinuxONE preparation. This is theme alignment, not a verified scoring rubric.
- [PharmaSecure AI](https://pharmasecure.com/AI/): existing explainable scan-alert capabilities; no independent head-to-head benchmark was performed.

Local implementation and evidence:

- Raw added reports: [`PDF/`](PDF/), including [June central](PDF/2025-06_central.pdf), [November revision](PDF/2024-11_revised.pdf), [January revisions](PDF/2025-01_revised.pdf), [second January revision](PDF/2025-01_revised-1.pdf), and [May revision with conflicting subtitle](PDF/2025-05_revised.pdf).
- Data publication: [`refresh_data.py`](BatchGuard/refresh_data.py), [`snapshot_store.py`](BatchGuard/snapshot_store.py), and [`src/`](BatchGuard/src/).
- Historical baseline: [`batchguard_engine.py`](BatchGuard/batchguard_engine.py), [`primary_workflow.py`](BatchGuard/primary_workflow.py).
- Combined backend and features: [`decision_core.py`](BatchGuard/decision_core.py), [`scan_features.py`](BatchGuard/scan_features.py).
- Persistent experimental replay: [`inspection_stream.py`](BatchGuard/inspection_stream.py), [`replay.py`](BatchGuard/replay.py).
- Training contract: [`model_foundation.py`](BatchGuard/model_foundation.py), [`MODEL_FOUNDATION.md`](BatchGuard/MODEL_FOUNDATION.md), and [prepared manifest](BatchGuard/data/training/foundation-ready-v1/manifest.json).
- Current historical-only UI: [`app.py`](BatchGuard/app.py). Platform instructions: [`LINUXONE_RUNBOOK.md`](BatchGuard/LINUXONE_RUNBOOK.md).
- Existing tests: [`tests/`](BatchGuard/tests/). Earlier measurements: [experimental replay report](BatchGuard/reports/inspection_benchmark/report.json).
- Historical audit: [`BATCHGUARD_REVIEW.md`](BATCHGUARD_REVIEW.md). Prior alternatives/research: [`BATCHGUARD_IMPLEMENTATION_PLAN.md`](BATCHGUARD_IMPLEMENTATION_PLAN.md). Their intermediate scope statements do not override this specification.

Only this Markdown document was created for this request. Application code, datasets, training bundles and model state were not changed.
