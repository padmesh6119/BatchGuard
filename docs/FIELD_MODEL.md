# Field scan model: usable path and evidence gate

The repository has **no adjudicated field scans yet**. The current dashboard's scan score comes from scripted data and remains diagnostic. `src.field_model` is a separate, runnable training and scoring path for cases with independently established physical-pack identities. It does not train on the frozen synthetic challenge, and it does not claim that a scan pattern proves a counterfeit medicine.

## Input contract

Supply newline-delimited JSON, one *six-hour, single-batch candidate* per line. Each training case has `case_id`, `site_id`, `split` (`train`, `validation`, or `test`), `observations`, `physical_pack_ids`, and `adjudication`. Each observation contains an `event` with the documented `ScanEvent` fields (`simulated: false`), plus `received_at` (server timestamp), `location_accuracy_m`, `clock_offset_seconds`, and `scanner_authenticated`. `clock_offset_seconds` is **scanner clock minus trusted synchronized time**; scan time is corrected by subtracting it before feature extraction. The four telemetry fields must come from the collection system, not an investigator's guess. `physical_pack_ids` maps each unique event ID to a separately verified physical-pack identity. The adjudication record contains `method` (`physical_inspection` or `independent_pack_authentication`), `evidence_ref`, `reviewer_id`, and `adjudicated_at`.

The label is derived: an observed pack ID is copied if its events are linked to more than one verified physical pack. Outcome evidence is **never** supplied to the model at scoring time. The input validator rejects simulated events, missing provenance, incomplete telemetry, conflicting event IDs, overlapping sites or pack identities across cases, and non-chronological train/validation/test periods. Chronology uses server receipt timestamps rather than scanner clocks. The validator checks that evidence references are present; it cannot independently authenticate a claimed inspection, scanner, or evidence file. A deployment must verify those upstream.

Unlabeled scoring JSONL contains only `case_id`, `site_id`, and `observations`. It has the same measured telemetry, but no split, provenance, or adjudication fields.

One training line has this shape (replace every placeholder with an audited value; two or more observations are required):

```json
{
  "case_id": "CASE-0001",
  "site_id": "SITE-07",
  "split": "train",
  "observations": [
    {
      "event": {
        "event_id": "EVENT-0001", "pack_id": "PRINTED-CODE-123",
        "product": "Product name", "batch_no": "Batch 123",
        "manufacturer_key": "MANUFACTURER TEXT",
        "event_time": "2026-02-01T10:00:00+00:00",
        "source_id": "AUTHENTICATED-READER-5",
        "latitude": 13.08, "longitude": 80.27, "simulated": false
      },
      "received_at": "2026-02-01T10:00:03+00:00",
      "location_accuracy_m": 12.0,
      "clock_offset_seconds": 1.5,
      "scanner_authenticated": true
    },
    {
      "event": {
        "event_id": "EVENT-0002", "pack_id": "PRINTED-CODE-123",
        "product": "Product name", "batch_no": "Batch 123",
        "manufacturer_key": "MANUFACTURER TEXT",
        "event_time": "2026-02-01T10:04:00+00:00",
        "source_id": "AUTHENTICATED-READER-9",
        "latitude": 28.61, "longitude": 77.21, "simulated": false
      },
      "received_at": "2026-02-01T10:04:03+00:00",
      "location_accuracy_m": 18.0,
      "clock_offset_seconds": 0.5,
      "scanner_authenticated": true
    }
  ],
  "physical_pack_ids": {"EVENT-0001": "INSPECTED-PACK-A", "EVENT-0002": "INSPECTED-PACK-B"},
  "adjudication": {
    "method": "physical_inspection",
    "evidence_ref": "PRIVATE-CASE-SYSTEM/CASE-42",
    "reviewer_id": "REVIEWER-8",
    "adjudicated_at": "2026-02-02T09:00:00+00:00"
  }
}
```

## Commands

```bash
python -m src.field_model train private/adjudicated_cases.jsonl --output outputs/field_model
python -m src.field_model score private/new_cases.jsonl --model outputs/field_model --output private/field_scores.json
python -m app.dashboard
```

Training also accepts `--backend snapml` when Snap ML is installed. The model card records the selected backend. Running it on IBM Z is still a measurement task; this command alone does not demonstrate use of an on-chip accelerator.

Keep case files and evidence outside the public repository. The model card records the source hash, feature-code hash, model selection, validation threshold, site counts, and untouched test results. The artifact is hash-checked before loading. A score file records the model-card hash and one score per case.

The threshold maximizes validation recall while allowing at most **5% empirical false alerts** on validation negatives. A case abstains from review if any scanner is unauthenticated, declared location accuracy exceeds 100 m, absolute clock offset exceeds 60 s, server receipt differs from corrected event time by more than six hours, or a corrected event time is more than 60 s *after* server receipt. These cutoffs are conservative project assumptions that need field validation. A model may produce review flags only when each split has at least two distinct sites, 50 positive cases, and 200 negative cases; at least 80% of validation and test cases must have review-quality telemetry; both splits must have an upper 95% false-alert bound at or below 5% and a lower 95% recall bound at or above 80%, **including abstentions as misses**. Each validation and test site must also have at least 20 positives and 100 negatives and pass those same confidence bounds. Otherwise the scorer still runs, but every case is marked `research_only` and `review_flag` is false. These are engineering gates, not a guarantee of field reliability. A gate that passes on one collection still needs provenance auditing, representative sites, monitoring, and independent prospective evaluation. The dashboard shows whether a field model card exists and which gate checks failed, but omits site-level metrics from the published HTML.

This separation follows the useful principles of [independent training and test data and representative inputs in FDA/IMDRF good machine learning practice](https://www.fda.gov/medical-devices/artificial-intelligence-enabled-medical-devices/good-machine-learning-practice-medical-device-development-guiding-principles); it is not a claim that BatchGuard is a regulated medical device or compliant with a particular framework.
