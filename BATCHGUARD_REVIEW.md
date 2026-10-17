# BatchGuard understanding, loopholes, and scope decisions

Training-foundation update: real history and simulated clone scans remain the two product layers. Source-row provenance, strict headers, immutable training bundles, chronological splits, held-out scan families, shared scan features, and a three-signal decision backend are now implemented. See [MODEL_FOUNDATION.md](BatchGuard/MODEL_FOUNDATION.md). The audit below is historical; it does not mark all 50 issues resolved. Trained models, the complete combined dashboard, source identity verification, and actual LinuxONE runs remain pending. Flooding hardening is deferred; ordinary clone-scan detection is core scope.

Current build update: the audit below records the original prototype. The main app now prioritizes published medicine-quality findings, earlier-history context, source evidence, and chronological report-coverage checks. Refresh publishes validated versioned snapshots atomically and retains previous versions for recovery. The original data remains available. Hypothetical scan/flooding experiments are deferred. See [the implementation plan](BATCHGUARD_IMPLEMENTATION_PLAN.md) and [the current core runbook](BatchGuard/LINUXONE_RUNBOOK.md). Actual LinuxONE execution, verified manufacturer identity, and trained ML remain pending.

Reviewed: 17 October 2026. Scope: local project evidence; domain/platform research deferred. Official prompting documentation informed the implementation workflow added below.

## What the project is

BatchGuard aims to help drug inspectors choose which batches to sample within limited laboratory capacity. Historical CDSCO findings provide context; verification scans provide current signals; a combined queue explains inspection priorities. Humans decide and test samples. LinuxONE is intended to host the event-processing and scoring workload.

Today, it is a working Python/Streamlit prototype: workbook ingestion, conservative text normalization, a descriptive historical index, synthetic scans, four anomaly rules, and CSV exports. It has no trained model, continuous ingestion service, capacity allocation, or demonstrated LinuxONE deployment.

Important distinctions: NSQ means “Not of Standard Quality”; a spurious report is separate evidence. Neither an anomaly nor a missing reference match proves counterfeiting. A production batch can contain many legitimate packs, so batch identity cannot substitute for pack identity.

## Review coverage and verified baseline

- Reviewed all 10 project Python files, launcher, requirements, README, saved test report, both roadmap copies, both PDFs, DOCX plan, and text extracts.
- Parsed/profiled every worksheet across 14 workbooks and every row across 72 CSV files. Inventory covered 109 project files. Installed `.venv` dependencies, bytecode, and protected environment metadata are not project source and were excluded.
- Visually inspected all six concept-PDF pages and four abstract-PDF pages. Existing concept text/OCR extracts contain no substantive content.
- Rebuilt the pipeline in an isolated copy. Generated CSV contents matched existing files. Original application and datasets were not changed.
- Default Streamlit `AppTest` completed without exceptions. This checks runtime execution, not browser appearance or every interaction.
- Current snapshot: July 2025–August 2026; **2,554 master rows; 2,551 analytical rows** after three duplicate exclusions.
- Analytical categories: **686 central NSQ; 1,821 state NSQ; 44 spurious reports**.
- Manufacturer normalization: **1,941 usable text signatures**, including **295 repeated signatures**; all 2,507 usable records require identity review. All 44 spurious records lack usable manufacturer text.
- Failure mapping: **2,329 keyword-mapped; 177 unresolved; one missing; 44 not applicable**. There are 25 keyword rules.
- Default simulation, 60 events and seed 2026: **11 flagged events, seven missing references, two duplicate-token events, four multi-site events, zero spurious matches**. Rules overlap; these are demonstration counts, not accuracy metrics.

## Loopholes and required corrections

### A. Claims and evaluation

1. **Proposed capabilities exceed implementation.** Snap ML, cold-start priors, per-state queues, evidence quality, and continuous streaming appear in proposals but are absent. Label each capability implemented, planned, or measured.
2. **Roadmap numbers lack experimental support.** Winning odds, predicted lift, 2.4× capture, and LinuxONE throughput/latency examples are not measured results. Remove them from factual claims.
3. **Historical coverage is overstated.** Proposal diagrams show 2023–2026; files start July 2025. Correct coverage everywhere.
4. **Original split provides only two training months.** Training through August 2025 is technically possible, but cannot provide the implied long history. Use an explicitly justified chronological or rolling evaluation.
5. **The later plan also contains stale figures.** Its 1,942 signatures, 296 repeated signatures, and 9.8% recurrence do not reproduce from the current snapshot.
6. **Recurrence is not a universal prediction ceiling.** July 2025–January 2026 training versus February–August 2026 testing gives 122 previously seen manufacturer-signature records: 9.02% of 1,352 total test records, or 9.10% of 1,341 NSQ test records. This measures exact text recurrence, not a bound on every possible model.
7. **No complete sampling denominator or candidate universe.** Failure-report lists do not enumerate every marketed or tested batch. A defect probability or meaningful “failures per 100 inspections” requires a defined selection population and outcomes; failure-only data cannot establish these alone.
8. **No predictive evaluation exists.** There are no trained models, temporal feature generation, baselines, held-out metrics, or calibration. Keep the current index descriptive.
9. **Temporal leakage remains a design risk.** The current index uses the whole snapshot. Future backtests must use only evidence available before each decision; publication/revision dates are currently empty.
10. **Coldrif claims are narrative, not demonstrated prevention.** No retrospective exists. Clone detection cannot establish chemical contamination, and no scan evidence demonstrates it would have detected that incident.

### B. Data, identity, and provenance

11. **Local provenance stops at filenames.** There is no download manifest with authoritative URLs, retrieval times, hashes, revisions, or publication dates. Local processing does not independently verify workbook authenticity or completeness.
12. **Schema presence masks missing implementation.** All current normalized date fields, manufacture month, manufacturer/reporting states, revision/release fields, record status, parse status, notes, and other remarks are empty. Do not present them as populated features.
13. **Manufacturer text is not legal identity.** Addresses and spelling variants split entities. Conversely, punctuation normalization can collapse distinct strings. Add reviewed aliases with unit-level identity and provenance; do not blindly strip addresses.
14. **Missing manufacturer evidence limits attribution.** All 44 spurious rows lack usable manufacturer text. Do not attribute alleged products to a verified manufacturer through unsupported inference.
15. **Missing values affect matching.** One spurious record lacks a batch number; five records lack manufacturing dates and seven lack expiry dates. Count, expose, and handle them explicitly.
16. **Missing source is not zero incidents.** June 2026 has no spurious sheet. An availability report records this, but dashboard category totals do not explain the gap.
17. **Parser accepts a canonical shape without validating source completeness.** Unmapped fields are dropped; absent fields become empty. Add required-header checks, rejected-row counts, and source-to-output reconciliation.
18. **Spurious parsing depends on exact structure.** `S.No` starts records; exact prefixes identify dates, manufacturers, and replies. Orphan continuations are printed and skipped; repeated recognized fields overwrite earlier values. Add explicit rejects and evidence-preserving handling.
19. **Source-row traceability is partial.** `source_rows_json` survives in spurious intermediate files but is dropped from master datasets. Original central/state serial numbers are dropped. Preserve workbook/sheet/row references independently of presentation columns.
20. **Duplicate handling is hardcoded.** Three known pairs are checked carefully, but new duplicate patterns are not automatically reviewed. The build also requires those historical pairs and the December Sorbitol pair, preventing arbitrary smaller datasets.
21. **Unresolved records remain unresolved.** Two December Sorbitol entries differ in expiry and failure wording; both remain. The manufacturer review contains 126 groups, and failure review contains 178 rows. No decision workflow persists their resolution.
22. **Failure taxonomy is provisional.** Broad overlapping regexes can misclassify text; unbounded `BET` can match substrings, and any match marks the row mapped even if other text is unexplained. No severity model or validation set exists.
23. **Scope is broader than medicine packs alone.** Records include products such as cotton wool and lipstick. Define which product categories belong in the inspection use case before building dosage-form priors.

### C. Historical score, scans, and fusion

24. **Historical weights are unvalidated choices.** Score = 60×normalized record count + 25×normalized months + 15×normalized distinct products. It ignores recency, denominators, and verified severity. Retain it as an explicit baseline.
25. **Scores depend on the current comparison population.** Min-max scaling changes when data changes; identical features normalize to zero. A score of zero does not imply safety, and scores are not directly comparable across snapshots.
26. **The simulator samples reported problem records.** It has no representative genuine-market population, explicit benign scenario labels, attack truth labels, or held-out attack families. Detection precision/recall cannot be inferred from its flags.
27. **The seed does not reproduce exact timestamps.** `datetime.now()` changes event times. Add a fixed start time and scenario/version identifiers for repeatable evaluation.
28. **Injected-pattern code is misleading.** One block claims to duplicate a token but keeps event 1's original token. Actual duplication comes from copying event 2 into event 3. Give each scenario a clear specification and assertion.
29. **The demo does not guarantee a spurious match.** Default seed on current data produces none, despite the old verification report. Add an explicit scenario when demonstrating that rule.
30. **Batch-level multi-site detection generates weak evidence.** Legitimate distribution puts the same batch in many places. Add pack/serial identity and benign distribution scenarios before calling this clone detection.
31. **Event IDs and package IDs are conflated.** A duplicate `scan_id` may be delivery replay, not a cloned pack. Separate event identity, package identity, and source identity; deduplicate transport retries.
32. **No actual travel or velocity calculation.** The detector counts sites across the entire supplied frame. There are no coordinates, windows, distance, burst rate, or impossible-travel checks.
33. **Unknown-reference flags are inherently weak.** A failure-report database is not an authenticity registry. Many genuine batches will be absent. Treat absence as coverage information, not an automatic suspiciousness boost.
34. **Reference matching is fragile.** Matching uses trimmed, case-folded product and batch strings only. Formatting variants miss; coincident names/batch numbers can collide across manufacturers. Introduce reviewed identifiers without inventing identity certainty.
35. **Fusion is a fixed bonus.** Queue priority = min(100, historical index + 40 if any anomaly). Different signals receive the same bonus; multiple independent signals add nothing; clipping loses distinctions.
36. **No evidence-quality or flood-resistance layer.** Source diversity, corroboration, rate limits, alert decay, authentication, and independent-source checks are missing. Repeated events can fill the queue.
37. **The queue is per event, not per sampling action.** Default simulation produces 60 queue rows for 58 distinct product/batch pairs. Aggregate evidence into unique, reviewable inspection candidates.
38. **Capacity awareness is absent.** Historical “Rows to display” only truncates a table. It does not allocate weekly samples, enforce per-state budgets, consider testing costs, or estimate marginal coverage.
39. **Historical evidence is attached only after a reference match.** Unknown batches receive zero history even when their supplied manufacturer text resembles a known manufacturer. Resolve identity explicitly before using manufacturer-level priors.

### D. Refresh, UI, and operational reliability

40. **Refresh is not atomic.** Monthly and derived outputs are written sequentially. A later failure can leave a mixed snapshot. Build into staging, validate, then publish the complete version atomically.
41. **Deleted workbooks can leave stale months active.** The combined builder discovers all existing monthly master CSVs, independently of the current raw-workbook list. Use an explicit input manifest or a clean staging directory.
42. **Record IDs are row-position based.** Reordering source rows changes identity. Equal ID sets do not prove equal source versions or consistent content. Add stable provenance keys and snapshot hashes.
43. **Refresh failure does not fully stop consumption.** The UI reports failure but continues execution; cached data or partially written outputs may still be used. Retain an explicitly identified last-good snapshot or block reads.
44. **Scan state can outlive its reference snapshot.** Refresh clears the data cache, not `session_state['scan_events']`. Scan controls also require generation to apply. Tie events to a snapshot and make regeneration behavior explicit.
45. **No concurrency control.** Multiple sessions can refresh shared files while another reads them. Add a single-writer lock and immutable published snapshots.
46. **Runtime paths are inconsistent.** Refresh anchors itself to the app directory; the engine uses working-directory-relative paths. Centralize path configuration for CLI, UI, tests, and LinuxONE.
47. **No persistent inspection lifecycle.** There is no assignment, acknowledgement, review decision, lab outcome, feedback, or immutable action audit. CSV export is not case management.
48. **No service boundary or deployment protection.** No ingestion API, request schema, authentication, authorization, bounded payloads, durable event state, recovery policy, or health endpoints exist. These are needed before shared deployment.
49. **Tests and dependencies are insufficiently reproducible.** `TEST_RESULTS.txt` describes 11 workbooks and 1,898 analytical rows. No maintained automated test suite or dependency lock exists. Current Streamlit also emits deprecated-width warnings.
50. **LinuxONE remains unverified.** There are no s390x setup instructions, compatibility results, running service evidence, workload replay, or benchmark artifacts. The engine already avoids Streamlit imports, so reuse it rather than rewrite it.

Code-derived risks above are not all reproduced failures. The verified baseline covers successful ingestion, output equivalence, default engine execution, and default UI execution.

## Remove, replace, or defer

- Remove unsupported winning probabilities, performance figures, predictive claims, and historical coverage claims from pitch material.
- Replace “unknown batch = anomaly bonus” with a separate coverage status. Preserve raw absence evidence.
- Replace batch-only clone language and per-event inspection rows with pack-level detection and aggregated sampling candidates.
- Replace the fixed `+40` fusion when an evaluated alternative exists; keep it as a comparison baseline.
- Archive obsolete two-month datasets and stale test reports outside the active data path. Preserve audit evidence and raw workbooks.
- Consolidate duplicate roadmaps into one status document; distinguish measured results from targets.
- Defer maps, decorative streaming animations, hospital signals, graph models, second product domains, and PDF dossiers until the core service works.
- Remove “sampling warrant” language from proposed exports. An evidence summary does not grant legal authority.
- Do not add an LLM to event scoring or reason generation. Existing structured rules can produce explanations without token cost.
- Never add automatic medicine blocking or counterfeit verdicts from a score.

## Add in this order

### P0 — Trustworthy foundation

1. A source manifest, explicit availability flags, durable record provenance, and an agreed product scope.
2. Atomic versioned builds, single-writer refresh, integrity checks, last-good rollback, and snapshot-aware UI state.
3. Tests covering missing sheets/fields, parser continuations, known/new duplicates, taxonomy boundaries, stale masters, and mismatched snapshots.
4. Corrected documentation with the verified counts and clear implemented/planned/measured labels.

### P1 — Small LinuxONE vertical slice

1. Parameterize the existing engine for CLI/service use. Keep Streamlit as a thin client.
2. Define events with event ID, pack ID, batch/product identity, timestamp, coarse location, and pseudonymous source ID.
3. Add validated ingestion, retry deduplication, bounded time windows, persisted state, and health/status reporting.
4. Process a deterministic replay on LinuxONE; emit an explained, deduplicated top-N inspection queue.
5. Record OS/architecture, Python/dependency versions, startup commands, logs, restart behavior, and exact compatibility failures.
6. Benchmark the same workload on laptop and LinuxONE: event count, duration, throughput, p50/p95/p99 latency, resource use, and measurement boundary. Separate ingestion, scoring, and end-to-end latency.
7. Test Snap ML installation on the actual s390x environment. Add it only for a defined, measurable modeling task. Report a failed compatibility check honestly.

### P2 — Defensible detection and evaluation

1. Build labeled benign scenarios: repeat buyers, legitimate distribution, pharmacist bulk scans, travel, and delayed sync.
2. Build labeled attacks: copied serials, bursts, slow adaptive behavior, and flooding. Hold out whole scenarios; avoid merely teaching and testing the same rules.
3. Compare rules against any model using precision, recall, PR-AUC, false alarms per 1,000 genuine scans, and detection delay.
4. Evaluate chronological historical baselines with a defined candidate universe; report cold-start share and entity-resolution uncertainty.
5. Expose historical priority, scan evidence, and evidence quality separately. Compare fused selection against each layer alone under the same inspection budget.
6. Add a human review lifecycle and feedback only after candidate identity and provenance are reliable.

## Implementation flow with lower-cost models

### Competitive target

Fixing the core gaps could make BatchGuard substantially stronger. It does not establish winning odds. Prioritize a defensible result: a real LinuxONE workload, reproducible evaluation, useful capacity-limited decisions, and a clear demonstration. Closing all 50 issues before demonstrating value is unnecessary; unsupported claims and broken data contracts need attention first.

“Astra-like output” should mean meeting the same task-specific acceptance checks, not assuming equal reasoning ability. Clear scope and executable checks can make work easier for a lower-cost model. They cannot guarantee equivalence on ambiguous architecture or scientific validity.

### Working method

Use the following as a project-specific workflow, not a claim about any model's benchmark performance. OpenAI's archived GPT-5 guide supports explicit exploration limits, clear stopping criteria, and separating distinct tasks; it does not promise parity with stronger models. [Official GPT-5 prompting guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide).

1. **Keep one shared specification.** Use this review as the starting point. Maintain a short status note containing accepted decisions, completed task IDs, current checks, and the next task. Do not repeat the full audit each session.
2. **Define contracts before implementation.** Specify snapshot identity, event fields, candidate identity, score meaning, and CLI/service inputs and outputs. Resolve pack-versus-batch identity before building detection.
3. **Assign one bounded task per turn.** Provide the relevant loophole IDs, exact files, expected behavior, preserved behavior, and acceptance checks. Include necessary dependencies; do not impose an arbitrary file limit that hides required context.
4. **Implement the smallest complete change.** Reuse existing code. Avoid unrelated refactors, new frameworks, or speculative features.
5. **Verify with executable evidence.** Run the relevant tests and inspect the diff. Require actual commands and results; “looks correct” is not acceptance. Test expectations come from the contract, not merely the new implementation.
6. **Review at integration boundaries.** Review identity, temporal leakage, snapshot publication, detector evaluation, and LinuxONE measurements. A stronger model is optional here; an informed human can review the same evidence.
7. **Escalate selectively.** After two unsuccessful focused repair attempts, stop repeating prompts. Package the contract, smallest failing example, diff, and error for a stronger model or human. Escalate earlier if the specification is ambiguous.
8. **Record the outcome and stop.** Save the changed files, checks, remaining limitation, and next dependency. Start the next task without re-reading every source document.

### Build order and completion gates

Run the LinuxONE access/compatibility check early, alongside foundation work, so deployment blockers surface before substantial modeling effort.

| Stage | Work package | Required proof before advancing |
|---|---|---|
| 0 | Confirm event rules, LinuxONE access, Python and dependency compatibility | Actual platform/version output and either successful minimal execution or a recorded blocker |
| 1 | Freeze scope, contracts, and benchmark definitions | One event schema, one sampling-candidate definition, one agreed evaluation population |
| 2 | Repair provenance and snapshot publication | Rebuild reproduces counts; injected refresh failure preserves the previous usable snapshot; removed inputs do not survive silently |
| 3 | Build deterministic labeled scenarios | Same seed/start time reproduces events; benign and attack labels are separate from detector outputs |
| 4 | Implement baseline detection and unique top-N queue | Retries do not consume extra inspection slots; legitimate batch distribution alone does not imply cloning; reasons link to evidence |
| 5 | Run replay through the LinuxONE service | Events reach persisted results; restart/retry checks pass; workload and software versions are recorded |
| 6 | Evaluate and optionally add Snap ML | Held-out scenarios, honest false-positive counts, and matched baseline comparisons; retain the baseline if modeling adds no demonstrated value |
| 7 | Integrate Streamlit and freeze the demo | Budget control changes unique sampling candidates; snapshot/version labels are visible; clean rerun and backup demonstration succeed |

### Model allocation and cost controls

- Use an available lower-cost coding model, including a suitable GPT-5 option, for bounded patches, tests, documentation, and narrow source research. Verify actual access and cost before choosing; this document makes no pricing assumptions.
- Use stronger reasoning selectively for unresolved data identity, evaluation design, cross-module failures, and final evidence review. Do not pay for repeated full-repository audits.
- First try three representative tasks: one parser correction, one detector edge case, and one service integration change. Compare accepted results, retries, time, and total cost against existing reviewed work. Expand usage only when checks pass.
- Optimize **cost per accepted task**, including retries and review. Short visible replies do not establish low total token use.
- Send relevant excerpts and file paths, not entire CSVs, PDFs, logs, or chat history. Use scripts for counts and comparisons. Retain essential constraints even when compressing context.
- Request concise outcome summaries rather than long reasoning transcripts. Set scope and stopping conditions; never save tokens by skipping required validation.
- Work sequentially by default. Parallelize only independent, well-defined tasks when the latency benefit justifies duplicated context and integration effort.
- Keep LLMs in development/research assistance. The BatchGuard event-processing path should use deterministic code or evaluated local models, with no per-scan LLM token spend.

### Reusable implementation prompt

```text
Task: Implement [one behavior], addressing review items [IDs].
Read: [relevant review section, source files, direct dependencies].
Current behavior: [concrete failing example].
Required behavior: [input and expected output].
Preserve: [data contracts and existing behavior].
Out of scope: [explicit exclusions].
Acceptance: [normal case, edge case, failure case, exact checks].

Inspect the relevant code, make the smallest complete change, and run checks.
Do not invent measurements, alter unrelated code, or weaken checks to pass.
If evidence contradicts the contract, report the conflict before changing it.
Finish with changed files, executed checks/results, and remaining risks.
Keep the report brief. Stop when acceptance checks pass.
```

Example first coding task: “Make refresh publish a complete versioned snapshot. Preserve the old snapshot on failure. Verify that deleting a raw workbook removes its month from the next build, subject to explicitly handled historical-review requirements.” Split this into smaller tasks if the contract spans too many unresolved components.

## Deferred research tasks

Use small, bounded tasks with cheaper models where available. Supply this file plus only relevant source files; require primary-source links and explicit uncertainty.

- Verify official CDSCO provenance, publication timing, usable denominators, identifiers, and revisions.
- Verify LinuxONE access, s390x dependency availability, Snap ML support, and event rules from current official sources.
- Define practical inspection candidates, capacity units, and available outcome labels with domain stakeholders.
- Verify pack serialization, benign scan patterns, and what independent corroboration can actually establish.
- Verify Coldrif facts separately; do not infer preventability from the narrative.

No domain/platform research or model delegation was performed for this review. A later documentation-only update consulted official OpenAI prompting guidance. No LinuxONE integration or application fixes were made.

## Main source map

- [Application and UI](BatchGuard/app.py)
- [Ranking, simulator, anomaly rules, and fusion](BatchGuard/batchguard_engine.py)
- [Refresh orchestration](BatchGuard/refresh_data.py)
- [Schema](BatchGuard/src/schema.py), [monthly ingestion](BatchGuard/src/process_month.py), [spurious parsing](BatchGuard/src/clean_spurious.py)
- [Dataset build and duplicate rules](BatchGuard/src/build_dataset.py)
- [Manufacturer normalization](BatchGuard/src/normalize_manufacturers.py), [failure taxonomy](BatchGuard/src/normalize_failure_types.py)
- [README](BatchGuard/README.md), [saved historical verification](BatchGuard/TEST_RESULTS.txt)
- [Original six-page concept](BatchGuard.pdf), [four-page abstract](BatchGuard_Final_Abstract_Submission.pdf)
- [Roadmap](batchguard_ibmz_evaluation_and_roadmap.md), [later data findings and plan](<BatchGuard Data Findings and Hackathon Build Plan.docx>)
- [Processed evidence](BatchGuard/data/processed/), [audit reports](BatchGuard/reports/), [source workbooks](BatchGuard/data/raw/)
