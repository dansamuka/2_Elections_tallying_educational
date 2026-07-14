# Malava pending-roster and CI fix · 14 July 2026

## Root causes

1. The Malava public payload correctly declared 198 expected Form 35A assignments, but its
   `streams` array was still empty because the first IEBC portal bootstrap had not run.
   The old grid renderer only drew boxes for loaded stream rows, so the whole panel appeared empty.
2. `replay_available=false` was rendered generically as `WITHHELD`. Malava is an OCR truth-set
   benchmark rather than a count replay, so that wording was accurate for replay but misleading
   for the intended workflow.
3. `tests/frontend/package-lock.json` had been generated against an internal packaging registry.
   GitHub Actions could not resolve those tarball URLs. `npm install` retried for nearly eight
   minutes and then npm itself terminated with `Exit handler never called`.

## Implemented

- The Malava benchmark now shows all 198 expected boxes immediately as disabled placeholders.
  They are visibly labelled as a pending portal roster and cannot be opened or reviewed until
  each box has a real source identity.
- After the first successful portal sync, the placeholders are automatically replaced by the
  real named polling-centre/stream boxes.
- The status tile now reads `OCR BENCHMARK / AWAITING FORMS` or `REVIEW READY`, rather than
  `REPLAY / WITHHELD`.
- The replay panel now explains the OCR benchmark workflow and the local green truth-set tally.
- The ledger and gap panel explain why the real rows are not yet clickable.
- Added an execution test covering the 198-placeholder pre-sync state.
- Replaced all internal npm tarball URLs with `registry.npmjs.org`, pinned jsdom 26.1.0,
  switched CI to Node 20, and changed dependency installation to deterministic `npm ci`.
- Added npm cache configuration, explicit public registry, bounded retries and step timeouts.
- Added a push trigger for crawler/OCR configuration changes so this deployment starts the
  first portal sync immediately rather than waiting for the scheduler.
- Increased the one-time historical sync allowance to 180 minutes.
- Reordered the scheduled plan to process Ol Kalou first, then Banissa, then the larger Malava
  benchmark, so the live/pre-poll target is not delayed.

## Validation

- 115 Python tests passed.
- Python compileall passed.
- `frontend/archive.js` and the new browser test pass `node --check`.
- JSON and workflow YAML parse successfully.
- The jsdom execution suite could not be installed in the offline packaging container; GitHub CI
  now installs it from the public npm registry with `npm ci`.
