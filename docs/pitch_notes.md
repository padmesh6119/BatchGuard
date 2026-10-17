# Pitch notes

## One line
Every week an inspector can sample only N batches. BatchGuard ranks which N to sample, explains each choice, and leaves the decision to the inspector.

## What is real and what is simulated
- Real: CDSCO NSQ and spurious-drug lists, Jul 2025 to Aug 2026, 2,551 records, every file hash-verified.
- Simulated: pack-verification scans. India has no public scan feed, so we generate one on real reference batches and label it **SIMULATED** on every screen.

## Numbers to say (held-out Jul to Aug 2026)
- History model AP 0.098 vs 0.067 for the best baseline (95% CI of the gain 0.005 to 0.068). At a budget of 25 manufacturers it captures 21 later reports vs 13.1.
- The scan rule reaches 80.8% recall and 100% precision on simulated episodes. Our trained model got 72.7% recall, so the rule drives alerts. We show the model rather than hide that result.
- At N=100 the fused queue captures 85% of clones and 79% of recurring batches. Scans alone capture 87% / 37%; history alone 62% / 100%.
- 9.1% of NSQ records from Feb to Aug 2026 carried manufacturer text seen through Jan 2026. This is one measured split. It is not a ceiling.

## Why LinuxONE
- The workload is a regulator's audit-grade queue: hash-checked data and models, deterministic seeds, and one test read per run. A platform built for regulated, always-on transaction processing fits that work.
- Snap ML ships s390x wheels, so the same training code runs on the laptop and on LinuxONE. We report both machines' timings from the same workload hash.
- We do **not** claim the on-chip AI accelerator sped anything up. We report only whether the CPU lists the NNPA facility, and we claim only what we measured.

## The hard question: "Would this have caught Coldrif?"
No, and we say so.
- Sresan's Coldrif batch SR-13 appears as "Adulterated" in the October 2025 state NSQ list (Drugs Testing Laboratory, Chennai).
- Sresan has no earlier record in our data, so history alone could not flag it in advance. The scan layer exists for exactly this cold-start gap. Its numbers are simulated.
- After October, Sresan appears in 10 more records under 8 different spellings of its name and address, one of them blank. Identity resolution is the real next problem, and BatchGuard surfaces it instead of silently merging the spellings.

## Honesty slide
- Layer A label: next-month report recurrence. It is not medicine safety.
- Layer B: simulated data. Real scan data could behave differently.
- Manufacturer text is not a verified legal identity. Source independence is asserted, not verified.
- Each test month has few recurring batches (7 to 8 in the fusion queue).
- Collection month stands in for publication date.
