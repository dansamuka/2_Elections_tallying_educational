# Automated IEBC form synchronization

## Purpose

This module checks the IEBC by-election forms portal:

`https://forms.iebc.or.ke/index.php?r=site%2Findex&p=2&l=2`

It is configured for Banissa 2025 and the live/pre-poll Ol Kalou 2026 contest, and remains reusable for future profiles under `data/elections/<election-id>/`.

## Scheduled operation

`.github/workflows/sync-historical-forms.yml` runs at `2/5 * * * *`, the shortest GitHub Actions scheduling interval. The workflow:

1. checks out the existing `dansamuka/2_Elections_tallying_educational` repository;
2. installs Tesseract and the Python OCR dependencies;
3. runs `archive-sync --all` using `data/elections/sync.json`;
4. follows the target constituency row, detail page and all pagination links;
5. downloads every new Form 35A/35B file discovered for that constituency;
6. preserves new versions by SHA-256 rather than overwriting old scans;
7. runs PDF embedded-text extraction or Tesseract OCR;
8. regenerates the review queue, public archive payload and catalog;
9. commits only meaningful changes; and
10. deploys the updated GitHub Pages site in the same workflow.

GitHub schedules are not a real-time SLA. Runs may be delayed under GitHub Actions load. The dashboard therefore shows the last completed and last changed synchronization states separately.

## Manual update

### From the public archive

Click **Update now**. The button opens the secured GitHub Actions workflow page. Sign in as a repository owner, select **Run workflow**, choose the election or `all`, then run it.

A static GitHub Pages site cannot securely dispatch a write-capable workflow by itself without exposing a GitHub token. The two-step authenticated GitHub screen is therefore intentional.

### One-click Windows trigger

Double-click:

```text
UPDATE_IEBC_FORMS_NOW.cmd
```

The script uses the authenticated GitHub CLI session to run the workflow and opens the workflow page.

### Command line

```bash
python -m olkalou_engine.cli --root . archive-sync banissa-2025 --engine auto
python -m olkalou_engine.cli --root . archive-sync ol-kalou-2026 --engine auto
python -m olkalou_engine.cli --root . archive-sync --all --engine auto
```

## Configuring elections

`data/elections/sync.json` controls scheduled elections:

```json
{
  "enabled": true,
  "interval_minutes": 5,
  "elections": ["banissa-2025", "ol-kalou-2026"],
  "engine": "auto",
  "repository": "dansamuka/2_Elections_tallying_educational",
  "workflow_file": "sync-historical-forms.yml"
}
```

Each election profile must provide:

- `portal.index_url`;
- `portal.constituency` exactly as shown on the IEBC portal;
- `portal.expected_forms`;
- the certified stream register for publication, or an explicitly incomplete live reference for archive/OCR-only operation; and
- the candidate list used for OCR field extraction, with an explicit ballot-order verification flag.


## Configured hierarchy routes

- Banissa: `KENYA → MANDERA → BANISSA → ward → polling centre → stream`.
- Ol Kalou: `KENYA → NYANDARUA → OL KALOU → ward → polling centre → stream`.

Both routes ignore bulk Download All controls and eye/preview links. Only individual cloud-download actions at polling-stream leaves are accepted.

## Discovery safeguards

The portal adapter supports:

- normal links;
- Yii `data-url` and `data-href` attributes;
- JavaScript `onclick` locations;
- form actions and embedded viewers;
- PDF, image and ZIP responses; and
- pagination links.

It compares the constituency's `reported of expected` portal count against the number of discovered Form 35A links. If the portal reports forms but the parser discovers fewer links, the sync fails loudly and saves the index HTML under `data/elections/<id>/portal_debug/` rather than silently publishing incomplete coverage.

## OCR and publication safety

Automated OCR produces:

- `ocr/document_inventory.json`;
- per-page extraction JSON;
- `ocr/review_queue.csv`;
- `ocr/form35b_review.json`; and
- `ocr/summary.json`.

OCR records are displayed as `OCR_REVIEW`. They do not update candidate totals. Publication still requires independent review and V01, V02, V03 and V07 to pass through `archive-import`.

## Cloud OCR

The default workflow uses local Tesseract. Optional workflow secrets are supported:

- `GCV_SERVICE_ACCOUNT_JSON` for Google Cloud Vision;
- `AWS_ACCESS_KEY_ID`;
- `AWS_SECRET_ACCESS_KEY`; and
- optional `AWS_SESSION_TOKEN` for Textract.

Choose `gcv`, `textract` or `dual-cloud` only after adding the corresponding repository secrets.

## Storage guard

GitHub rejects individual files larger than 100 MB. The workflow stops at 95 MB and instructs the operator to configure object storage instead of attempting an unsafe Git commit. For larger election archives, use R2/S3 and keep only manifests, OCR records and public URLs in Git.
