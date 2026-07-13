# Historical election OCR pipeline

The historical OCR module processes all source documents associated with an election while preserving the engine's provenance-first publication rules.

## Safety model

OCR is a pre-fill, not a source of truth. The command:

1. inventories every supported PDF/image recursively;
2. hashes each source with SHA-256 and collapses exact duplicates;
3. mirrors the original source immutably under `data/public/elections/<election-id>/forms/uploaded/`;
4. processes every page, including multi-page PDFs;
5. classifies Form 35A, Form 35B and unrelated pages;
6. matches Form 35A pages to the certified stream register using polling-station code, station name and stream number;
7. extracts candidate votes and statutory control totals;
8. runs V01, V02, V03 and V07 where sufficient fields exist;
9. writes a human review queue; and
10. never writes `verified_results.json` or updates the public tally automatically.

A Form 35A is marked `READY_FOR_DOUBLE_REVIEW` only when all required fields are present, its stream is matched, and all four critical checks pass. Every other form is quarantined.

## Source folders scanned automatically

For election `<election-id>`:

- `data/elections/<election-id>/documents/`
- `data/elections/<election-id>/forms/`
- `data/uploads/<election-id>/`
- `data/public/elections/<election-id>/forms/`

Additional files or directories can be included with repeated `--include` arguments.

## Windows one-click use

Double-click:

```text
RUN_HISTORICAL_OCR.cmd
```

The script defaults to `banissa-2025`, installs the Python OCR dependencies, optionally installs Tesseract through `winget`, runs the OCR pipeline, rebuilds the archive payload and then offers to push the updated files to the existing repository `dansamuka/2_Elections_tallying_educational`.

## Command-line use

Inventory without OCR:

```bash
python -m olkalou_engine.cli --root . archive-documents banissa-2025
```

Local OCR using embedded PDF text first and Tesseract for scanned pages:

```bash
python -m olkalou_engine.cli --root . archive-ocr banissa-2025 --engine auto
```

Force reprocessing:

```bash
python -m olkalou_engine.cli --root . archive-ocr banissa-2025 --engine auto --rebuild
```

Include another folder:

```bash
python -m olkalou_engine.cli --root . archive-ocr banissa-2025 \
  --include "C:/Election documents/Banissa" --engine auto
```

Cloud handwriting pre-fill, when credentials are configured:

```bash
python -m olkalou_engine.cli --root . archive-ocr banissa-2025 --engine dual-cloud
```

Check local Tesseract availability:

```bash
python -m olkalou_engine.cli --root . ocr-doctor
```

## Outputs

The election folder gains:

```text
data/elections/<election-id>/ocr/
  document_inventory.json
  summary.json
  review_queue.csv
  form35b_review.json
  extractions/<sha>-p<page>.json
```

The website archive payload exposes document count, pages processed, detected forms, matched streams and review-queue depth. A matched stream is shown as `OCR_REVIEW` but remains excluded from candidate totals.

## Completing human review

Open `review_queue.csv`. Two reviewers independently verify every figure against the linked source form. After resolving all differences, retain the required columns and run:

```bash
python -m olkalou_engine.cli --root . archive-import banissa-2025 \
  data/elections/banissa-2025/ocr/review_queue.csv
python -m olkalou_engine.cli --root . archive-build banissa-2025
```

The importer still rejects V01, V02, V03 or V07 failures. OCR confidence cannot override a failed statutory check.

## Adding another historical election

Create the normal election profile and certified register, add a `documents/` folder, then run the same command with the new election ID. No election-specific Python code is required. Candidate labels and CSV columns are generated from `election.json`.
