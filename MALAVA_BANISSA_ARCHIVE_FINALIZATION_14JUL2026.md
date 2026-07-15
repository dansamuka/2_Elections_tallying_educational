# Malava hierarchy and Banissa PDF finalization — 14 July 2026

## Incident diagnosis

The successful long OCR run produced a valid historical snapshot at commit:

`b81eab0841661e5dc3deb86396b966181eac019a`

That snapshot contained:

- Banissa: 81 portal assignments, 72 unique source PDFs, 72 OCR pages and 70 matched streams.
- Malava: 198 portal assignments, 198 archived PDFs, 198 OCR pages and a complete 198-row portal-bootstrap roster.

A later queued workflow started from an older triggering SHA and published the whole `data/elections` and `data/public/elections` trees. It therefore restored stale empty historical files over the successful snapshot. This is why the current page can show browser-local green review cells while its server metrics show zero archived forms.

## Finalized implementation

### Malava hierarchy

1. The IEBC crawler now carries county, constituency, ward and polling-centre context through the hierarchy.
2. Portal hierarchy metadata is stored with each manifest item.
3. Bootstrap rows use the portal ward and polling-centre labels where available.
4. Printed Form 35A header identities are parsed using the 15-digit station code:
   - county: 3 digits;
   - constituency: 3 digits;
   - ward: 4 digits;
   - polling centre: 3 digits;
   - stream: 2 digits.
5. Synthetic Malava stream keys are remapped to official-style keys such as `201-1002-001-01`.
6. Cached OCR output can be remapped without re-running the expensive OCR operation.
7. The archive grid now renders `Ward → Polling centre → Stream` rather than one undifferentiated list.
8. The table and review dialog show both ward and polling centre.

The reconstructed hierarchy remains review-only until the certified Malava stream register is loaded. It improves navigation and provenance but does not certify registered-voter values or publish a result.

### Banissa PDFs

1. The public stream payload now prefers the stream-specific manifest PDF URL.
2. Relative archive URLs are normalized by the browser, rather than relying solely on a Pages-build text substitution.
3. Each stream also carries the original IEBC source URL as a fallback.
4. The Pages workflow validates every local Form 35A link before deployment.
5. The restore workflow returns the 72 unique Banissa PDF files and OCR outputs from the known-good snapshot.

### Workflow safety

1. Every queued run resets to the latest `origin/main` before generating data.
2. Manual sync defaults to `ol-kalou-2026`, not `all`.
3. A single-election run commits only that election's data paths.
4. Banissa or Malava runs cannot overwrite the other election or Ol Kalou.
5. Live `live.json` is rebuilt only for Ol Kalou or an explicit `all` run.
6. OCR logs visible progress every ten pages.
7. A dedicated restore workflow can recover the last good Banissa/Malava snapshot and deploy it.

## Deployment

### Recommended one-command path

Extract the overlay into the repository root and run:

```bat
APPLY_MALAVA_BANISSA_FINALIZATION.cmd
```

The script commits and pushes the code changes, then dispatches:

`Restore Banissa and Malava archive`

using the known-good snapshot commit.

### GitHub UI path

After pushing the overlay:

1. Open **Actions**.
2. Select **Restore Banissa and Malava archive**.
3. Select **Run workflow**.
4. Leave the snapshot SHA as `b81eab0841661e5dc3deb86396b966181eac019a`.
5. Run it once.

The workflow restores only Banissa and Malava data, remaps Malava from cached Form 35A header OCR, rebuilds both payloads, validates all PDF links and redeploys GitHub Pages. It does not replace Ol Kalou data.

## Expected post-restore state

### Banissa

- portal assignments: 81/81;
- unique PDFs: 72;
- OCR pages: 72;
- OCR matched streams: approximately 70;
- Form 35A links visible in the table and review dialog.

### Malava

- portal assignments: 198/198;
- archived forms: 198;
- OCR pages: 198;
- named ward sections;
- named polling-centre sections inside each ward;
- clickable stream boxes;
- PDF displayed in the review dialog;
- unresolved scans clearly retained under a review-only fallback group rather than being discarded.

## Validation completed in the package

- 121 Python tests passed.
- Python compilation passed.
- Frontend JavaScript syntax passed.
- Workflow YAML parsed successfully.
- Form-header identity test confirmed `037201100200101` maps to `201-1002-001-01`, ward `WEST KABRAS`, polling centre `MUTSUMA PRIMARY SCHOOL`.
