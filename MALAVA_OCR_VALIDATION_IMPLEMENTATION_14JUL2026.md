# Malava OCR validation implementation · 14 July 2026

## Included

- Added `malava-2025` to the past-poll catalog and scheduled sync plan.
- Configured the official portal expectation of 198 Form 35A assignments.
- Added exact-count portal bootstrap: no stream skeleton is written unless all 198 individual assignments are discovered.
- Kept the initial stream register, wards and registered-voter fields explicitly uncertified.
- Added OCR benchmark mode with automatic publication disabled.
- Added incomplete-candidate-roster handling so the OCR reconciler cannot force a partial candidate subtotal to equal total valid.
- V01 is `NOT_RUN` for the benchmark; V02 and form control checks remain active.
- Added the green human-confirmed card workflow and benchmark tally wording.
- Benchmark top tally uses the human-reviewed PO-stated valid total and separately shows configured candidate-field subtotals.
- Benchmark CSV export includes only confirmed rows.
- Added `scripts/measure_historical_ocr_accuracy.py` for coverage, exact precision, exact recall, MAE and aggregate-field validation.
- Added Python and browser execution tests for exact-count bootstrap, incomplete-roster reconciliation and benchmark review behaviour.

## First deployment run

After pushing the repository, manually run **Sync historical IEBC forms** or wait for the scheduled workflow. The first successful Malava run should:

1. discover exactly 198 individual Form 35A assignments;
2. create the 198-row review-only matching skeleton;
3. archive the documents;
4. run the layout-aware handwriting OCR only on new/changed documents; and
5. rebuild the public Malava benchmark dashboard.

The local packaging environment could not reach the IEBC host due DNS resolution restrictions, so the 198 PDFs are not bundled in this ZIP. The workflow and retry logic are included and tested with fixtures; the live GitHub Actions runner must perform the first portal fetch.

## Promotion gate

Do not convert Malava from `benchmark_only` until the complete candidate list, ballot order, certified atomic register and official Form 35B totals are source-verified. Until then, green rows are OCR truth labels only and cannot be imported as verified election results.
