# Malava 2025 OCR validation benchmark

## Purpose

Malava is included as a past-election **OCR benchmark**, not as a publishable parallel tally. The IEBC result-form portal reports 198 Form 35A assignments for the 27 November 2025 Malava parliamentary by-election. That is large enough to test the layout-aware handwriting pipeline across different pens, scan angles, contrast levels and polling-station handwriting styles.

## Safety posture

The Malava profile deliberately starts with:

- `benchmark_only: true`;
- `candidate_list_complete: false`;
- an unverified, empty atomic stream register;
- no official constituency candidate totals; and
- automatic publication disabled.

The first portal sync must discover exactly all 198 individual Form 35A assignments before creating a stream skeleton. A partial response writes nothing. Bootstrap rows have unresolved wards, synthetic matching identities and no certified registered-voter value, so V07 cannot pass and `archive-import` cannot publish them.

Only three publicly reported candidate names are configured initially to provide handwriting anchors. Their subtotal is not forced to equal total valid. V01 is therefore `NOT_RUN`; V02 and the form control checks remain active.

## Review workflow

1. Run `archive-sync malava-2025 --engine auto` or the scheduled workflow.
2. Select **Malava · 27 Nov 2025** on the past-polls page.
3. Open a polling-stream card and compare each OCR prefill to the embedded Form 35A.
4. Correct every configured candidate/control value and enter the reviewer name.
5. Click **Save OCR benchmark review**.
6. The stream cell turns green and the top panel adds the PO-stated valid total plus the configured-field subtotal.
7. Download the confirmed benchmark truth CSV.

The benchmark export contains only explicitly confirmed rows. Unconfirmed drafts are omitted.

## Accuracy report

```bash
python scripts/measure_historical_ocr_accuracy.py \
  malava-2025 \
  path/to/malava-2025-ocr-benchmark-truth.csv
```

Outputs:

- `data/elections/malava-2025/ocr/accuracy_report.md`
- `data/elections/malava-2025/ocr/accuracy_report.json`

The report measures:

- truth-stream matching;
- field coverage;
- exact precision;
- exact recall;
- mean absolute error; and
- candidate-field aggregate reproduction.

Coverage and accuracy are intentionally separate: an OCR engine that leaves difficult cells blank can have high precision but poor recall.

## Promotion requirements

Malava must remain a benchmark until all of the following are loaded and verified:

1. the complete legal candidate list;
2. ballot/Form 35A row order;
3. the certified 198-row polling-stream register;
4. registered voters for every stream;
5. official Form 35B totals; and
6. independent reviewed Form 35A truth rows.

Only after those gates pass should V01, V07, verified import and constituency tallying be enabled.
