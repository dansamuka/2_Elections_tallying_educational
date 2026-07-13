# IEBC Sync Run #1 Fix

## What failed

The IEBC national MNA index reported `BANISSA 81 of 81`, but its constituency row uses JavaScript string concatenation:

```javascript
let id = "90";
location.href = "/index.php?r=site%2Findex&id=" + id + "&ft=" + "" + "&p=2" + "&es=";
```

The previous parser extracted only a quoted URL fragment and lost the row id. The request therefore returned to the national index, where one national **Download All** control was incorrectly seen as a constituency-scoped link. The completeness guard correctly rejected `1` discovered link against `81` reported forms.

## Fixes

- Reconstruct JavaScript `location.href` expressions using the table row id.
- Prefer the exact constituency `<tr>` instead of walking up to the national table toolbar.
- Configure Banissa's known IEBC detail URL (`id=90`) as a deterministic fallback.
- Require the final detail response URL to retain the requested constituency row id.
- Permit a constituency-scoped **Download All** ZIP as an alternative to 81 separate links.
- Validate the ZIP before archiving: it must contain exactly 81 supported Form 35A files.
- Reject national or malformed bundles before they can enter the repository.
- Count verified ZIP members as discovered/downloaded forms on the dashboard.

## Safety posture

OCR remains review-only. Downloading and OCR processing may update archive coverage and review queues, but no candidate total is published until human verification and statutory validation pass.

## Validation

- 44 tests passed.
- Ruff passed.
- Python compilation passed.
- Frontend JavaScript syntax checks passed.
- Regression tests cover the exact IEBC JavaScript row pattern, redirect-to-national-index rejection, correct 81-file bundle acceptance, and wrong-sized bundle rejection before archival.
