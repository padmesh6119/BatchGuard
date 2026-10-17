# BatchGuard previous design and implementation alternative

Latest direction: preserve the original combined inspector decision screen, with real CDSCO history and simulated clone-code scans. The training-data foundation and combined decision backend are ready for baseline model work; refer to [MODEL_FOUNDATION.md](BatchGuard/MODEL_FOUNDATION.md) for targets, splits, commands, and limits. Earlier historical-only and flooding-centered scope notes below describe intermediate stages and do not override [the product direction](AGENTS.md).

Current scope: prioritize the real historical-data workflow. Flooding and hypothetical attack scenarios are deferred; their earlier implementation and results below remain historical records.

Research date: 17 October 2026. Builds on [the repository review](BATCHGUARD_REVIEW.md). Winning is the target; measured delivery and a clear operational advantage guide scope.

## What existing projects already do

These are published capabilities, not independently benchmarked results. Missing details on a public page do not prove that a competitor lacks a feature.

| Project | Published capabilities | Implication for BatchGuard |
|---|---|---|
| [PharmaSecure AI](https://pharmasecure.com/AI/) | Explainable prioritized scan alerts, geographic analysis, batch insights, audit evidence | Explainable scan intelligence alone is not novel |
| [Sproxil Verify](https://sproxil.com/products/verify) | Serialized authentication, multiple verification channels, fraud/anomaly alerts, product movement | QR verification and hotspot detection are established capabilities; the fetched page rendered incompletely, so this comparison also uses its indexed first-party excerpt |
| [TraceLink SPI](https://www.tracelink.com/resources/resource-center/serialized-product-intelligence-proactive-monitoring) | Visibility into serialized events and proactive lot/serial monitoring | Traceability dashboards alone offer little differentiation |
| [mPedigree Goldkeys](https://goldkeys.org/how-it-works/) | Scratch/SMS verification, supply-chain management, government surveillance tools | Regulator-facing functionality already exists; do not claim to invent it |
| [Pharma Track System](https://devpost.com/software/pharma-track-system) | Hackathon prototype recording supply-chain transfers on Stacks/Clarity; QR and analytics listed as future work | A blockchain ledger is a familiar prototype direction, not the priority for this build |

## Primary objective now

Make the original medicine-quality workflow complete and understandable: reliable official-workbook ingestion, a queue of published findings for follow-up, direct evidence access, honest chronological checks, and an executable IBM Z path.

Implemented in the current core:

- Clean staging, a source/output hash manifest, validated versioned snapshots, atomic publication, a single-writer lock, and rollback support. Original datasets remain available.
- A unique product/batch/manufacturer-text follow-up queue with a chosen report month, separate NSQ/spurious categories, a capacity limit, and earlier-month history only.
- Candidate evidence and original workbook downloads; missing evidence and unavailable source sheets are visible.
- Month-ordered comparison of the historical index, most-past-records baseline, and random expectation. This measures later report coverage, not market defect probability or inspection yield.
- A primary headless export command and a main app focused on medicine-quality evidence. The attack replay remains a separate deferred experiment.

Still required: independently verified source provenance/publication timing, reviewed manufacturer identity, justified trained-model targets, actual LinuxONE execution, and a reproducible final demonstration. No new attack-detection capability is a primary requirement.

Core validation: 21 tests pass, including failure recovery, removal of stale months, rollback, and readers pinned to an earlier snapshot. The full 14-month rebuild preserves 2,551 analytical records. Primary exports include a ten-candidate latest-month queue and 13 chronological coverage checks. Main UI checks cover capacity, NSQ/spurious selection, an unavailable-source month, and the earliest month. Original workbooks and legacy outputs remain unchanged.

## Earlier experimental alternative (deferred)

The earlier proposed angle was protecting a fixed inspection budget against repeated/adversarial scans. That was a hypothetical robustness exercise, not an observed attack in the CDSCO records. It is no longer the selected main workflow. Published competitor capabilities above remain background research rather than proof of a unique market advantage.

## Previous behavior versus experimental alternative

| Previous prototype | Alternative being implemented | Proof |
|---|---|---|
| Different sites for one batch imply anomaly | Track an individual pack; legitimate distribution of different packs is normal | Benign distribution regression |
| Reused scan ID is suspicious | Same event ID/payload is an idempotent retry; conflicting reuse is rejected | Retry and conflicting-ID tests |
| Missing from failure lists earns anomaly bonus | Reference absence is coverage information | Unknown genuine-scenario test |
| Any anomaly adds 40 points | Explicit corroboration tiers, with historical context as a tiebreaker | Three separate displayed signals and documented ordering |
| One row per scan consumes queue space | One product/batch/manufacturer-signature candidate aggregates pack evidence | Replays do not expand candidate count |
| Unlimited table rows | Inspector chooses a maximum number of sampling candidates | Top-N selection test and control |
| Sixty events with no truth labels | Seeded events with fixed UTC start time and separate scenario truth | Repeatable event digest and evaluation |
| No persistent stream state | SQLite-backed local replay and durable idempotency | Restart/replay test |
| Windows-first launch | Headless Python replay/benchmark plus optional Streamlit view | Same commands on local Linux and actual LinuxONE |
| Assumed IBM performance | Architecture/version/workload hashes plus measured latency and throughput | Machine-generated benchmark artifact |
| No comparative results | History-only, raw-volume, scan-only, and fused queues under one budget | Scenario-specific capture and false-alarm report |

The first slice retains the historical heuristic as descriptive context. No trained model or predictive defect probability is claimed. A full snapshot-publication migration, authenticated production ingestion, temporal model training, and inspection case management remain separate work.

## IBM Z fit and verified constraints

The [organizer page](https://www.starhacks.org/ibm-z-datathon-2026) describes the Real-Time AI for Critical Decisions theme as streaming risk detection and decision support. It also lists LinuxONE setup. Our workload fits that operational direction, but a Python rules prototype alone does not demonstrate trained AI.

The linked [official-rules page](https://www.starhacks.org/ibmzdatathon-official-rule) exposed no substantive rule text to the reader. Judging weights, pre-event-code policy, and submission requirements remain unverified; do not use an unrelated Datathon rubric found online.

[IBM's Snap ML overview](https://ibm.github.io/ai-on-z-101/snapml/) describes LinuxONE/Linux on Z availability and an s390x package. Actual Python/package/hardware compatibility must be tested on the assigned machine. Accelerator use must be configured and evidenced; neither the machine architecture nor a package import proves acceleration.

Use the assigned event environment. [IBM Cloud's s390x VPC page](https://cloud.ibm.com/docs/vpc?topic=vpc-vsabout-images) reports that this particular product is deprecated; it must not be confused with event-provided LinuxONE access.

## Data boundary

Existing local workbooks remain the reference dataset: 2,551 analytical findings across 14 months. Public [CDSCO alerts](https://www.cdsco.gov.in/opencms/opencms/en/Alerts/) and the [public NSQ/spurious view](https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug) establish relevant official source locations. Research did not establish complete provenance for every existing workbook or download a new market-wide negative population.

Synthetic pack IDs, sources, locations, benign behavior, and attacks must be labeled simulated. Benign scan behavior does not establish that a referenced medicine is chemically safe. Failure-list absence does not establish authenticity. Manufacturer signatures remain unverified identities.

[GS1 EPCIS](https://www.gs1.org/standards/epcis) provides an established event-sharing model. Our event schema is a small internal contract; no EPCIS conformance is claimed. An adapter is deferred.

## Earlier experimental delivery sequence (deferred)

1. **Current build:** deterministic scenario generator, persistent pack-level detector, distinct evidence signals, unique top-N queue, comparative evaluation, CLI benchmark, and Streamlit controls.
2. **Platform proof:** copy the same code and workload to assigned LinuxONE, run checks, replay, and retain raw artifacts. No access credentials are configured in this workspace.
3. **AI decision gate:** compare a trained detector against the rule baseline on held-out scenario families only after defining labels and features. Test Snap ML on the actual environment; retain a baseline and disclose limitations if no improvement is measured.
4. **Reliability work:** stage and atomically publish historical snapshots; complete provenance and source authentication; connect a bounded authenticated ingestion service.
5. **Demo freeze:** show benign distribution, a retry, a single-source flood, then a corroborated pack clone. Change N and show unique selected cases, evidence, measured platform results, and unresolved failure modes.

## Earlier experimental build completed in this workspace

The first local slice is implemented in [inspection_stream.py](BatchGuard/inspection_stream.py), [replay.py](BatchGuard/replay.py), and the Streamlit **Inspection budget replay** tab. Deployment commands and input/policy details are in [LINUXONE_RUNBOOK.md](BatchGuard/LINUXONE_RUNBOOK.md).

- Thirteen focused tests pass, including durable retry handling, conflicting IDs, distinct-pack distribution, reference absence, source corroboration, expired evidence, and snapshot isolation.
- Streamlit runtime and inspection-capacity interaction pass. Browser appearance was not visually verified.
- [The small replay](BatchGuard/reports/inspection_replay/report.json): 89 deliveries, 88 accepted events, one retry, six active candidates. Budget two captures two simulated clone cases under fused/scan-only selection, one under volume, zero under history-only.
- [The larger replay](BatchGuard/reports/inspection_benchmark/report.json): 1,780 deliveries, 1,760 accepted events, 20 retries, 120 active candidates. Budget ten captures ten simulated clone cases under fused and scan-only selection, zero under volume, four under history-only. There are 60 simulated clone candidates total, including 20 slow-clone misses.
- The larger local run recorded about 620 deliveries/second and 3.55 ms p99 per-delivery latency on x86_64. This is one short sequential application run, excludes loading/network/UI, and is not a LinuxONE measurement or a sustained-load claim. See raw artifacts for exact boundaries and versions.
- **No historical-fusion uplift was shown over scan-only selection.** Labels and rules are hand-designed. Repeated scenario copies increase workload size, not scenario diversity or statistical independence.

No authenticated network service, trained AI model, LinuxONE deployment, accelerator configuration, or complete refresh migration was delivered in this slice. Actual platform access remains the next external dependency. The original historical dataset was preserved.

## Acceptance and limits

- The same event payload is counted once across restarts. Conflicting event IDs fail explicitly.
- Different packs in one batch do not trigger pack-clone rules.
- Reference absence alone does not create scan evidence.
- Repeated claims from one source cannot meet a two-source corroboration gate.
- Source IDs are asserted in the synthetic replay. This is not Sybil resistance: authenticated, independently governed source enrollment is required for production.
- Time windows and travel thresholds are explicit heuristics. Coarse locations, delayed delivery, out-of-order events, and fast travel require limitations and tests.
- Slow attacks outside the rule window are included as known failures, not hidden from evaluation.
- Comparative metrics describe the chosen simulation. No claim of real counterfeit accuracy, regulator adoption, or superiority over commercial products follows.
- Report laptop results as laptop results. LinuxONE deployment and acceleration stay unverified until actual runs exist.

## Cost discipline

Use deterministic scripts for processing and metrics; no per-scan LLM calls. Give a lower-cost model one contract, relevant files, and explicit checks per task. Use a stronger reviewer only for unresolved identity, evaluation, or integration decisions. Follow the reusable task prompt in the review. Measure cost per accepted change, including retries.

## Research method

First-party vendor, organizer, IBM, CDSCO, GS1, and project-author pages were inspected. Search was bounded to the design decision; this is not an exhaustive market or patent review. Firecrawl could not resolve its API host, so research used the available web tool. No private competitor service was accessed or benchmarked.
