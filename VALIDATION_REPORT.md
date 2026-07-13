# Validation report — Banissa and Ol Kalou hierarchy update

## Scope

This package updates the existing repository `dansamuka/2_Elections_tallying_educational` and adds Ol Kalou to the same five-minute IEBC portal/OCR workflow already used for Banissa.

## Automated checks

- 57 pytest tests passed.
- Ruff static analysis passed for `src`, `tests`, and `scripts`.
- Python bytecode compilation passed.
- `frontend/app.js`, `frontend/archive.js`, and `frontend/config.js` passed Node syntax checks.
- Banissa public payload rebuilt: 81 expected forms, certified historical reference retained.
- Ol Kalou public payload rebuilt: 144 expected forms, five ward totals, `LIVE / PRE_POLL`, reference gate closed.
- Existing-repository updater remains locked to `dansamuka/2_Elections_tallying_educational` and contains no repository-creation command.
- Windows PowerShell updater retains UTF-8 BOM and ASCII-only executable content.

## New regression coverage

- Ol Kalou `0 of 144` index count parsing.
- Kenya → Nyandarua county selection.
- Nyandarua → Ol Kalou constituency selection.
- Ol Kalou row id `141` preservation.
- Five-ward traversal: Rurii 33, Kanjuiri Range 32, Karau 27, Kaimbaga 27, Mirangine 25.
- Individual cloud download accepted at polling-stream leaf.
- Eye/preview and Download All controls rejected.
- Date text no longer corrupts leaf stream-number extraction.
- Ol Kalou incomplete atomic reference accepted for source archiving but blocked from publication.
- Banissa profile and 81-form behavior remain valid.

## Safety conclusion

The package is ready to push as a portal-archive and OCR-review update. Ol Kalou figures must remain unpublished until the certified atomic stream register, final candidate legal names/Form 35A order, independent review, and statutory validation are complete.
