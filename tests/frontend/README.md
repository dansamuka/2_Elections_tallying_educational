# Frontend execution tests

Tests `frontend/archive.js`'s review workbench (OCR prefill display,
editable draft inputs, localStorage persistence, CSV export) by loading the
real `archive.html`/`archive.js`/`config.js` into jsdom and driving them
through actual DOM events -- clicks, input changes -- the same way a
browser would. Not a syntax check (`node --check`, run separately in CI)
and not testing a reimplementation of the logic: the exact shipped code.

## Run it

```
cd tests/frontend
npm install
npm test
```

Scoped to this directory on purpose -- the deployed site itself is plain
`<script>` tags with no build step and no runtime dependency on Node or
npm. Nothing here affects how the site actually runs; it only tests it.

## What it covers

- The "Source documents inventoried" stat used to compare a number against
  itself (always 100%) instead of against the expected total -- fixed, and
  pinned here so it can't quietly come back.
- The old `Math.max(forms_archived, portal_downloaded)` hack that made the
  top-of-page stat say "81/81" while the readiness list further down
  honestly said "72/81" for the same concept -- fixed, and pinned here.
- OCR-extracted per-candidate figures render correctly in the review modal,
  pre-filling editable inputs.
- Editing a field persists a draft to `localStorage`, scoped per election,
  and a correction to one field doesn't lose the OCR value in an untouched
  field.
- Re-opening a stream shows the saved correction, not the original OCR
  reading.
- A stream with no OCR record at all, and an already-`PUBLISHED` (verified)
  stream, both render correctly without crashing or offering to edit
  something that's already settled.
- The exported CSV has the exact column order `import_verified_results()`
  (in `archive.py`) requires, contains corrections rather than raw OCR
  values, and omits streams nobody has drafted.
