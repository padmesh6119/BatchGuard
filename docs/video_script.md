# Demo video script (under 3 minutes)

| Time | Screen | Say |
|---|---|---|
| 0:00 to 0:15 | Title, banner | "An inspector can sample ten batches this week. Which ten? BatchGuard answers that. Real CDSCO history, simulated scans, and a human decides." |
| 0:15 to 0:35 | Press **⏮**, then **▶ Play**. Watch the scan feed and map | "Simulated pharmacy scans arrive on real batches. A retried delivery is ignored. A new pack is just a new pack." |
| 0:35 to 1:05 | Let it play to the end (or press **⏭**). Queue rank 1 and rank 2, the red travel line on the map | "The same pack of Lorazepam, batch T240628, is scanned in Chennai and then in Delhi four minutes later. That is impossible travel. It ranks first. A burst of twelve scans of one pack in Bengaluru ranks second. Historical risk, scan anomaly and evidence quality stay in separate columns, and each row has its reasons." |
| 1:05 to 1:35 | Batch evidence for rank 1: timeline, map, manufacturer history | "Here is the evidence: the scan timeline, the synthetic locations, and the real earlier CDSCO records for this manufacturer with their source files. The inspector records a decision; nothing is blocked automatically." |
| 1:35 to 2:10 | Evaluation tab | "We measured on held-out July and August 2026. The history model beats every baseline: average precision 0.098 against 0.067. Our trained scan model lost to the simple rule on unseen attack families, so the rule drives alerts. At a hundred batches, the fused queue catches 85% of simulated clones and 79% of real recurring batches." |
| 2:10 to 2:35 | Platform tab | "The same workload runs on IBM LinuxONE with Snap ML. These are measured timings from both machines. We claim no acceleration we did not measure." |
| 2:35 to 2:55 | Honesty slide | "Limits: the real label is report recurrence, not safety. Scans are simulated. Coldrif's maker had no history before October 2025, so history alone could not have caught it. That gap is why scan verification matters." |
