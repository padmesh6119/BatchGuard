# BatchGuard training foundation

The target remains one inspector queue combining real CDSCO history, simulated scans, and separately displayed evidence quality. This foundation prepares training; it does not replace the product with a historical-only dashboard.

## Ready now

- Validated, versioned data snapshots and rollback; original files preserved.
- Workbook, sheet, and Excel-row provenance for every master record. Analytical IDs are checked against that provenance.
- Required input headers, explicit handling of orphan continuation rows, missing-identity review reports, and corrected endotoxin abbreviation matching.
- Separate training features, labels, and metadata, with input/code hashes and deterministic seeds.
- Chronological Layer A splits; disjoint pack identities and held-out scenario families for Layer B.
- Shared Layer B feature extraction for training and inference.
- A combined decision backend with historical risk, scan anomaly, evidence quality, priority, reasons, and a unique-candidate capacity limit.

## Training targets

| Layer | Target | What a negative label means |
|---|---|---|
| A: real CDSCO history | Whether an already-observed manufacturer text signature appears in next month's NSQ reports | No next-month report; it does not mean the manufacturer's medicines are safe |
| B: simulated scans | Whether a simulated batch observation episode contains a copied-code scenario | Generated benign behavior; it does not establish chemical medicine quality |

Layer A uses seven prior-history features. Features stop before the target month. Manufacturer identity itself is excluded from feature columns. The current split trains on target months through May 2026, validates on June, and reserves July–August for final testing. Collection months are proxies because verified publication timestamps remain unavailable. New manufacturer signatures remain outside this conditional model's candidate universe; the recurrence chart reports that limitation.

Layer B uses nine observable features over a six-hour window, including per-pack scan counts, distance, speed, source counts, timing, and retries. IDs, scenario names, labels, historical failure status, and rule predictions are excluded from feature files. Delayed-sync and slow-copy families occur only in the final test split. Normal and copied-code observations can overlap; labels do not guarantee separability.

No flooding scenarios are required by this foundation.

## Reproduce preparation

From `BatchGuard/`, using installed application requirements:

```bash
python refresh_data.py
python model_foundation.py --output data/training/my-fresh-foundation --episodes-per-scenario 100 --seed 2026
python -m unittest discover -s tests -v
```

The prepared workspace bundle is `data/training/foundation-ready-v1/`. Use a fresh directory when regenerating. The preparation command refuses to overwrite existing artifacts.

Verified preparation: 31 tests pass; all 2,554 master records resolve to workbook rows. Layer A has 6,760 training, 1,438 validation, and 3,370 test examples. Layer B has 500 training, 165 validation, and 231 test episodes. These counts are examples/episodes, not unique manufacturers or real-market outcomes. Original workbooks and legacy outputs are preserved.

Each task has `train`, `validation`, and `test` CSVs, separated into `_X`, `_y`, and `_metadata`. `manifest.json` lists exact feature columns, splits, hashes, source snapshot, environment, and limitations. `scan_episodes.jsonl` retains labeled synthetic events and coarse synthetic district/state metadata for reproducibility.

```python
from model_foundation import load_model_inputs, HISTORY_TASK, SCAN_TASK
X, y, metadata = load_model_inputs("data/training/foundation-ready-v1", HISTORY_TASK, "train")
```

Use validation data for model and threshold selection. Test access requires `final_evaluation=True`; that guard prevents accidental use during development, not intentional access. Preserve the selected parameters and code before final test evaluation. Never train on `_metadata` or `scan_episodes.jsonl` directly without respecting the explicit feature contract.

## Baselines and evaluation

- Layer A: compare rankings with the existing 60/25/15 index, most past records, and random selection under the same manufacturer budget. Report next-report capture and cold-start share. Accuracy alone is misleading because positive recurrence labels are rare.
- Layer B: compare with `scan_rule_baseline`, which receives the same features and observation window as a future model. Report precision, recall, false-positive counts, and held-out-family results. Select thresholds using validation only.
- Fusion: `decision_core.build_decision_queue` returns separate historical, scan, and evidence values. Its declared untrained baseline is 50% history + 35% scan + 15% corroboration when a scan signal exists. The source-count index is not authenticated independence. Evaluate these weights rather than presenting them as optimal.
- Sample status stays unknown unless observed; the backend does not invent “no sample yet.” Manufacturer state also stays unknown unless supported by source data. Synthetic district metadata must remain labeled synthetic.

## Next stage

Install and verify the chosen training backend, fit the two baselines, select parameters on validation data, then evaluate/export final model artifacts. Snap ML compatibility must be checked on the assigned LinuxONE environment. Neither sklearn nor Snap ML is installed in the current workspace environment.

No model has been fitted by preparation. Seven-point dashboard integration, actual LinuxONE execution, manufacturer identity verification, complete official download provenance, and prospective real-world validation remain separate work. No medicine-safety probability or real counterfeit-detection accuracy is established by these inputs.
