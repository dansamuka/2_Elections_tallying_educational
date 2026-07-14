# OCR and Human Review Upgrade — 14 July 2026

## What the current Banissa evidence actually shows

The portal run discovered and downloaded 81 of 81 Form 35A assignments. The apparent `72 / 81` shortfall is not nine unfetched portal downloads: the inventory collapsed nine duplicate-content assignments, leaving 72 unique document binaries. At the portal matching stage, 78 assignments matched a registered stream and three did not; the later archive/OCR matching recovered part of that gap, leaving 79 archived stream assignments and two awaiting.

The old numerical OCR was nevertheless unsuitable for unattended use. It applied full-page Tesseract and searched for a number near each printed label. On the supplied scans this repeatedly selected ballot row numbers (`1`, `2`) instead of handwritten values (`208`, `8`, etc.). The quarantine policy correctly prevented those guesses from entering the published tally.

## Implemented review workflow

- The browser tally is always visible at the top, starting at `0 / total` and `0 valid`.
- A row only becomes green after the reviewer completes every numeric field, enters a reviewer name, passes V01/V02/V03, and passes V07 where a certified stream register is available.
- Clicking **Save & mark reviewed** stamps the local row, turns its polling-stream cell green, adds it to the top candidate and valid-vote totals, labels it `HUMAN REVIEWED` in the ledger, and advances to the next unconfirmed stream.
- Editing a confirmed row removes its green/confirmed state until the edited arithmetic is checked and explicitly saved again.
- Raw OCR checks and checks calculated from the human-edited values are displayed separately.
- This remains a browser-local provisional tally. CSV export plus `archive-import` and the existing independent verification gate are still required for publication.

The implementation is election-generic and therefore applies to both `banissa-2025` and `ol-kalou-2026`. Ol Kalou permits a local review with V07 marked `NOT_RUN` while its atomic registered-voter reference is unresolved, but the server-side importer continues to block publication until that reference is certified.

## Implemented OCR changes

The OCR pipeline is now versioned as `2026.07.14-layout-v2`. An older summary/extraction automatically triggers a rebuild during the next sync.

For every Form 35A page, the new local stage:

1. renders the page at 4× resolution;
2. deskews and denoises the scan;
3. locates printed candidate and control labels;
4. crops only the right-hand handwritten numeric cell;
5. removes table lines and runs three complementary digit passes;
6. excludes shared surnames as standalone anchors;
7. reconciles candidate alternatives against the stated valid-vote total;
8. derives total cast from valid plus rejected where the form has no separate cast row;
9. uses the certified register only as a weak, visibly tagged hint against obvious row-number hallucinations; and
10. keeps every result as review-only, with no OCR auto-publication.

The workflow now installs OpenCV. The three-pass cell strategy is bounded so a 144-stream Ol Kalou rebuild remains practical within the scheduled job window. Google Vision or Textract can still be enabled through repository secrets; they supplement the full-page reading while the local layout stage provides field isolation and arithmetic reconciliation.

## Download completeness changes

An unchanged (`304 Not Modified`) portal index no longer ends the run before incomplete binaries are considered. Manifest rows with a missing archive file are retried, including an unconditional retry when the server returns 304 for a locally missing file.

The public payload and readiness panel now distinguish:

- portal form assignments downloaded;
- unique source PDFs;
- duplicate portal assignments;
- failed or missing downloads; and
- portal downloads unmatched to a stream.

This prevents duplicate content from being presented as a simple “missing upload” problem and makes the remaining manual matching work explicit.

## Validation

- Python: 110 tests passed.
- Frontend review workbench: execution test passed in jsdom.
- Added tests for row-number rejection/arithmetic reconciliation and retrying a missing form when the portal index is unchanged.
- Package installation/import smoke test passed.
