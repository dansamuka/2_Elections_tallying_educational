# OCR rehearsal and certification

OCR is implemented as an optional dual-cloud pre-fill, not as the source of truth.

## Configure the template

1. Save an exact blank or representative nine-candidate Form 35A as `data/reference/form35a-reference.png`.
2. Copy `form35a_roi.example.json` to `form35a_roi.json`.
3. Enter rectified-frame ROIs for every candidate numeral and words cell plus registered, rejected, total-valid and total-cast controls.
4. Keep `allow_resize_fallback=false` for production. Homography failure should quarantine, not stretch an unrelated scan into the template.
5. Set `status=VERIFIED` only after visual crop inspection over multiple real forms.

## Enable adapters

```env
OCR_MODE=dual-cloud
GCV_CREDENTIALS_JSON=/run/secrets/gcv.json
AWS_REGION=af-south-1
AUTO_PUBLISH_MACHINE_VERIFIED=false
```

The Google Vision adapter runs document text detection per ROI. The Textract adapter supports configured Queries on the rectified page and fills missing aliases with per-cell handwriting OCR. The merger requires exact numeric agreement and checks the strongest words extraction against the numeral.

## Measure rather than assume

Create an independently reviewed truth CSV:

```csv
stream_key,candidate_UDA,candidate_DCP,rejected,registered,total_valid,total_cast
091-...,182,103,4,612,285,289
```

Run:

```bash
python scripts/measure_ocr_accuracy.py rehearsal_truth.csv --db data/state/engine.sqlite3 --output accuracy_report.md
```

Do not enable machine auto-publication merely because aggregate totals happen to reconcile. Review per-field coverage, exact precision/recall, candidate totals and failure concentration by scan quality.

## Calibrate V05

After at least 30 independently reviewed comparable forms:

```bash
python scripts/calibrate_rejected_rate.py --db data/state/engine.sqlite3
```

Copy the recommended bounds into `REJECTED_RATE_LOW` and `REJECTED_RATE_HIGH`, document the corpus and preserve the generated report.
