# Safe rollout: selective Google Vision crop OCR

## What this upgrade changes

The upgrade adds a bounded Google Vision second reader for handwritten numeric cells that the local layout-aware OCR has already located. It does **not** publish results automatically and does not modify source PDFs, official Form 35B totals, gazetted totals or verified-result imports.

The recommended engine is:

```text
tesseract-gcv-crop
```

This keeps full-page form recognition local and sends only weak or disputed number crops to Google Vision.

## Safety controls included

- The Windows launcher works in an isolated Git worktree created from the latest `origin/main`.
- The user's normal repository folder is never stashed, switched, reset, cleaned or edited.
- The launcher checks reviewed Git blob versions before installing complete replacement files; upstream drift stops safely.
- The pull request contains source, tests, documentation and workflow files only—no historical data.
- Python tests, Ruff and compilation must pass before the feature branch is pushed.
- Pilot mode processes a deterministic page sample into `/tmp/ocr-pilot`; it does not modify repository election data.
- The workflow processes one election at a time; there is no `all` option.
- Google requests are capped per run.
- One Vision client is reused for the run, with bounded retries and timeouts.
- Google receives the exact deskewed crop used by the local extractor.
- Publish mode creates a rollback tag before rebuilding.
- Official declarations, candidate totals, source assignments, PDF hashes, registered-voter references, stream counts and PDF-link coverage are protected.
- Stream-key or ward/polling-centre changes are blocked unless hierarchy remapping is separately and explicitly approved.
- Publish mode stages only the selected election and reloads final `main` before assembling GitHub Pages.

## Before applying the source-code pull request

Export any browser-local reviewed CSVs from Banissa and Malava. Keep the exports outside the repository as reviewer backups.

No cleanup of an earlier failed launcher is required. The v3 launcher ignores the dirty working folder and uses an isolated worktree.

Run:

```text
APPLY_SAFE_PATCH_IN_ISOLATED_WORKTREE.cmd
```

The launcher will:

1. locate `C:\Users\dansa\Downloads\2_Elections_tallying_educational` automatically where available;
2. fetch the latest `origin/main` without changing the selected working folder;
3. create a temporary isolated worktree and feature branch;
4. verify every target file against reviewed Git blob versions;
5. install complete replacement files rather than relying on fragile patch hunks;
6. run the complete test suite, Ruff and Python compilation;
7. remove test-generated runtime data;
8. verify that no `data/` file is included;
9. push only the feature branch; and
10. open a pull request.

Review the pull request and merge only after CI passes.

## Configure Google Vision

Create this GitHub Actions repository secret:

```text
GCV_SERVICE_ACCOUNT_JSON
```

The value must be the complete Google service-account JSON document. The workflow writes it to a temporary runner file and exposes only the file path through `GCV_CREDENTIALS_JSON` during the job.

Use a service account limited to the OCR project and monitor its Vision quota and billing.

## Stage 1 — bounded Banissa pilot

Open:

```text
Actions → Safe OCR Crop Pilot and Publish → Run workflow
```

Choose:

```text
Election: banissa-2025
Rollout mode: pilot
Engine: tesseract-gcv-crop
Pilot sample size: 20
Cloud request limit: 100
Reprocess existing OCR records: true
Allow hierarchy remap: false
Publish confirmation: leave blank
```

Pilot mode spreads the selected pages across the complete inventory, writes only to `/tmp/ocr-pilot`, uploads the pilot summary/review queue, and proves that repository `data/` remains unchanged. It does not commit or deploy anything.

### Pilot acceptance checks

Manually compare all 20 sampled forms and record:

- exact candidate-field accuracy;
- control-field accuracy;
- fields newly filled;
- wrong values surfaced with high confidence;
- values containing 0, 1, 2, 7 and 8;
- one-, two- and three-digit values;
- skewed and low-contrast scans; and
- Google requests, failures and rejected-above-register values.

Proceed only if candidate and control accuracy improve without increasing dangerous high-confidence errors.

## Stage 2 — publish Banissa

After accepting the pilot, run:

```text
Election: banissa-2025
Rollout mode: publish
Engine: tesseract-gcv-crop
Cloud request limit: 500
Reprocess existing OCR records: true
Allow hierarchy remap: false
Publish confirmation: PUBLISH_SELECTED_ELECTION
```

The workflow creates a rollback tag and blocks the commit if historical structure, reference values or source-form integrity changes.

## Stage 3 — bounded Malava pilot

Run Malava in pilot mode first:

```text
Election: malava-2025
Rollout mode: pilot
Engine: tesseract-gcv-crop
Pilot sample size: 20 or 40
Cloud request limit: 100 or 250
Allow hierarchy remap: false
```

Malava remains an OCR benchmark until its complete candidate roster and ballot order are certified. The pilot cannot publish a constituency result.

If printed Form 35A headers indicate that stream keys or ward/polling-centre mapping should change, inspect the pilot evidence and export browser reviews before any remap. A publish run that permits this requires both:

```text
Allow hierarchy remap: true
Publish confirmation: PUBLISH_SELECTED_ELECTION_WITH_HIERARCHY_REMAP
```

Do not enable this merely to make a safety check pass.

## Stage 4 — Ol Kalou

Do not run a full OCR rebuild while no Ol Kalou Form 35As are present. Keep portal discovery and pending-box publication on the fast path. Activate crop OCR only for newly downloaded forms and retain human confirmation as the tally gate.

## Rollback

Every publish run creates a pre-publish tag. Restore only the affected election paths on a reviewed rollback branch; do not force-reset `main`.

Example:

```bash
git fetch --tags origin
git switch -c rollback-banissa-ocr origin/main
git restore --source ocr-backup-banissa-2025-<run-id> -- \
  data/elections/banissa-2025/ocr \
  data/elections/banissa-2025/streams.json \
  data/elections/banissa-2025/forms_manifest.json \
  data/public/elections/banissa-2025.json \
  data/public/elections/catalog.json
git commit -m "Rollback Banissa OCR rebuild"
git push -u origin rollback-banissa-ocr
```

Open a pull request and deploy through the normal reviewed process.

## Final publication rule

Google Vision output remains machine prefill evidence. A polling stream enters the trusted tally only after the existing human review, arithmetic validation, independent verification and statutory reconciliation gates are satisfied.
