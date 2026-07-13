# Five-minute IEBC portal sync update

This release updates the existing repository only:

`dansamuka/2_Elections_tallying_educational`

## Apply the update

1. Extract the ZIP.
2. Double-click `PUSH_TO_GITHUB.cmd`.
3. Complete GitHub login if requested.
4. Wait for validation, commit and push to finish.
5. Open the repository Actions tab and confirm `Sync IEBC forms and OCR` is enabled.

The updater refuses to create a different repository.

## Automated operation

The workflow checks the configured IEBC portal elections every five minutes. It follows the constituency detail view and pagination, downloads new or amended Form 35A/35B files, archives each SHA-256 version, runs embedded-text/Tesseract OCR, rebuilds the historical payload, commits meaningful changes and deploys the updated Pages site.

## Manual operation

- On the archive webpage, click **Update now**, then select **Run workflow** in GitHub Actions.
- On Windows, double-click `UPDATE_IEBC_FORMS_NOW.cmd` for an authenticated direct workflow dispatch.

## Publication gate

OCR is still a pre-fill only. New scans may change archive coverage and add `OCR_REVIEW` rows, but they cannot change candidate totals until reviewed and imported through the statutory validation gate.
